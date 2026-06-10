"""Cross-platform supervisor / watchdog for the Zeiterfassung server.

This is what the autostart entry (systemd on Debian, Scheduled Task on Windows)
launches — NOT run.py directly. It runs the server in a loop and reacts to the
process exit code:

    exit 0   -> clean shutdown requested, stop the loop and quit.
    exit 42  -> an update was staged; apply it (swap files + pip install),
                then restart with the new code.
    other    -> the server crashed; wait briefly and restart it.

Because the file-swap of an update happens HERE (while the server process is
gone), there are no locked-file problems, and the same mechanism gives us
"restart on crash" and "self-restart after update" for free on both platforms.
"""
import os
import sys
import time
import shutil
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
STAGING_DIR = DATA_DIR / "_update_staging"
MARKER = DATA_DIR / ".update_pending"

EXIT_CLEAN = 0
EXIT_UPDATE = 42

# files/dirs in the install that must NEVER be overwritten by an update
PROTECT = {"data", ".venv", "venv", ".git", "__pycache__"}

# On Windows, keep the server subprocess from popping up its own console window
# (the supervisor itself runs windowless via pythonw). Harmless no-op elsewhere.
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _python():
    """The interpreter to run the server with (prefer the project venv)."""
    if os.name == "nt":
        venv = BASE_DIR / ".venv" / "Scripts" / "python.exe"
    else:
        venv = BASE_DIR / ".venv" / "bin" / "python"
    return str(venv) if venv.exists() else sys.executable


def _apply_staged_update():
    """Copy the extracted new version over the install dir, then reinstall
    dependencies. Returns True on success."""
    if not MARKER.exists():
        return False
    src_root = Path(MARKER.read_text(encoding="utf-8").strip() or str(STAGING_DIR))
    if not src_root.exists():
        _cleanup()
        return False
    print(f"[supervisor] applying update from {src_root}")
    try:
        for item in src_root.iterdir():
            if item.name in PROTECT:
                continue
            dest = BASE_DIR / item.name
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)
        # refresh dependencies (no-op if nothing changed)
        req = BASE_DIR / "requirements.txt"
        if req.exists():
            subprocess.run([_python(), "-m", "pip", "install", "-q", "-r", str(req)],
                           cwd=str(BASE_DIR), creationflags=_NO_WINDOW)
        print("[supervisor] update applied")
        return True
    except Exception as e:  # noqa: BLE001 - never let an update crash the loop
        print(f"[supervisor] update FAILED: {e}")
        return False
    finally:
        _cleanup()


def _cleanup():
    try:
        if STAGING_DIR.exists():
            shutil.rmtree(STAGING_DIR, ignore_errors=True)
        if MARKER.exists():
            MARKER.unlink()
    except OSError:
        pass


def main():
    # if a previous run left a staged update (e.g. machine rebooted mid-update)
    if MARKER.exists():
        _apply_staged_update()

    while True:
        proc = subprocess.run([_python(), str(BASE_DIR / "run.py")], cwd=str(BASE_DIR),
                              creationflags=_NO_WINDOW)
        code = proc.returncode
        if code == EXIT_CLEAN:
            print("[supervisor] clean shutdown, stopping.")
            break
        if code == EXIT_UPDATE:
            _apply_staged_update()
            print("[supervisor] restarting after update…")
            continue
        # crash / unexpected exit -> brief backoff then restart
        print(f"[supervisor] server exited with code {code}; restarting in 3s…")
        time.sleep(3)


if __name__ == "__main__":
    main()
