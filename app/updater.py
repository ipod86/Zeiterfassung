"""Self-update against the public GitHub repo.

Flow:
  * ``check()``         – compare local VERSION with the one on GitHub.
  * a daemon thread    – re-checks periodically so the UI can show a badge.
  * ``stage_update()`` – download the repo ZIP, extract it next to the app and
                         drop a marker file. The actual file-swap + restart is
                         done by ``supervisor.py`` once the server exits with
                         code 42 (see ``request_restart``).

Everything uses only the stdlib (urllib, zipfile) so there is no extra
dependency, and the repo being public means no token is needed on the machine.
"""
import os
import io
import json
import time
import zipfile
import threading
import urllib.request
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
VERSION_FILE = BASE_DIR / "VERSION"
DATA_DIR = BASE_DIR / "data"
STAGING_DIR = DATA_DIR / "_update_staging"
MARKER = DATA_DIR / ".update_pending"

GITHUB_OWNER = "ipod86"
GITHUB_REPO = "Zeiterfassung"
GITHUB_BRANCH = "main"
RAW_VERSION_URL = (f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/"
                   f"{GITHUB_BRANCH}/VERSION")
ZIP_URL = (f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/archive/refs/heads/"
           f"{GITHUB_BRANCH}.zip")

EXIT_UPDATE = 42
CHECK_INTERVAL = 6 * 3600  # re-check every 6 hours

_CACHE = {"current": None, "latest": None, "update_available": False,
          "checked_at": None, "error": None}
_LOCK = threading.Lock()


def current_version():
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


def _parse(v):
    parts = []
    for chunk in str(v).strip().split("."):
        num = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(num) if num else 0)
    return tuple(parts) or (0,)


def is_newer(latest, current):
    return _parse(latest) > _parse(current)


def _http_get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "Zeiterfassung-Updater"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def cached():
    """Return the last known status WITHOUT hitting the network (for fast page
    loads). The periodic daemon keeps this reasonably fresh."""
    with _LOCK:
        _CACHE["current"] = current_version()
        return {k: v for k, v in _CACHE.items() if not k.startswith("_")}


def check(force=False):
    """Return the cached status, refreshing it from GitHub when stale/forced."""
    with _LOCK:
        cur = current_version()
        _CACHE["current"] = cur
        fresh = (_CACHE["checked_at"] and not force and
                 (time.time() - _CACHE["_ts"]) < 300) if "_ts" in _CACHE else False
    if fresh:
        return dict(_CACHE)
    latest, error = None, None
    try:
        latest = _http_get(RAW_VERSION_URL).decode("utf-8").strip().splitlines()[0].strip()
    except Exception as e:  # noqa: BLE001
        error = f"{type(e).__name__}: {e}"
    with _LOCK:
        _CACHE["current"] = current_version()
        _CACHE["latest"] = latest or _CACHE.get("latest")
        _CACHE["update_available"] = bool(latest and is_newer(latest, _CACHE["current"]))
        _CACHE["checked_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        _CACHE["error"] = error
        _CACHE["_ts"] = time.time()
        result = {k: v for k, v in _CACHE.items() if not k.startswith("_")}
    return result


def stage_update():
    """Download the repo ZIP, extract it to the staging dir and write the marker
    file the supervisor looks for. Returns (ok, message)."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if STAGING_DIR.exists():
            import shutil
            shutil.rmtree(STAGING_DIR, ignore_errors=True)
        STAGING_DIR.mkdir(parents=True, exist_ok=True)
        raw = _http_get(ZIP_URL, timeout=60)
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            zf.extractall(STAGING_DIR)
        # the GitHub archive wraps everything in a single top folder
        roots = [p for p in STAGING_DIR.iterdir() if p.is_dir()]
        if not roots:
            return False, "Archiv leer oder ungültig."
        src_root = roots[0]
        if not (src_root / "run.py").exists() or not (src_root / "app").exists():
            return False, "Heruntergeladenes Archiv sieht nicht wie die App aus."
        MARKER.write_text(str(src_root), encoding="utf-8")
        return True, "Update heruntergeladen und vorbereitet."
    except Exception as e:  # noqa: BLE001
        return False, f"Download fehlgeschlagen: {type(e).__name__}: {e}"


def request_restart(delay=1.5):
    """Exit the process with the update sentinel so the supervisor applies the
    staged files and restarts. Delayed so the HTTP response can flush first."""
    def _bye():
        time.sleep(delay)
        os._exit(EXIT_UPDATE)
    threading.Thread(target=_bye, name="update-restart", daemon=True).start()


def _loop():
    time.sleep(20)  # let the server settle before the first check
    while True:
        try:
            check(force=True)
        except Exception:  # noqa: BLE001
            pass
        time.sleep(CHECK_INTERVAL)


def start_update_checker():
    """Start the periodic update-check daemon thread (idempotent per process)."""
    for t in threading.enumerate():
        if t.name == "update-checker":
            return t
    t = threading.Thread(target=_loop, name="update-checker", daemon=True)
    t.start()
    return t
