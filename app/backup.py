"""Backup helpers: build a backup ZIP and run a daily auto-backup scheduler.

The ZIP contains the SQLite database plus all uploaded files (logo). Automatic
backups land in ``data/backups/`` and are pruned after a configurable number of
days (default 14). The scheduler is a daemon thread that checks hourly, so a
machine that is not running 24/7 still gets today's backup the next time the
app is up.
"""
import io
import time
import sqlite3
import zipfile
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

from .db import DB_PATH, DATA_DIR

UPLOAD_DIR = DATA_DIR / "uploads"
BACKUP_DIR = DATA_DIR / "backups"
DEFAULT_KEEP_DAYS = 14
_CHECK_INTERVAL = 3600  # re-check once per hour


def build_backup_zip():
    """Return an in-memory ZIP (BytesIO) of the database + uploaded files."""
    # flush the WAL into the main db file so the copy is complete
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.DatabaseError:
        pass
    finally:
        conn.close()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        if DB_PATH.exists():
            z.write(DB_PATH, "zeiterfassung.db")
        if UPLOAD_DIR.exists():
            for f in UPLOAD_DIR.iterdir():
                if f.is_file():
                    z.write(f, f"uploads/{f.name}")
    buf.seek(0)
    return buf


def write_daily_backup(keep_days=DEFAULT_KEEP_DAYS):
    """Create today's backup (if missing) and prune old ones. Returns the path."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    dest = BACKUP_DIR / f"zeiterfassung-backup-{date.today():%Y-%m-%d}.zip"
    if not dest.exists():
        dest.write_bytes(build_backup_zip().getvalue())
    prune_backups(keep_days)
    return dest


def prune_backups(keep_days=DEFAULT_KEEP_DAYS):
    """Delete automatic backups older than ``keep_days`` days."""
    if not BACKUP_DIR.exists():
        return
    cutoff = datetime.now() - timedelta(days=keep_days)
    for f in BACKUP_DIR.glob("zeiterfassung-backup-*.zip"):
        try:
            if datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
                f.unlink()
        except OSError:
            pass


def list_backups():
    """Newest-first list of automatic backups: dicts with name/size/mtime."""
    if not BACKUP_DIR.exists():
        return []
    out = []
    for f in BACKUP_DIR.glob("zeiterfassung-backup-*.zip"):
        try:
            st = f.stat()
            out.append({"name": f.name, "size": st.st_size,
                        "mtime": datetime.fromtimestamp(st.st_mtime)})
        except OSError:
            pass
    out.sort(key=lambda x: x["name"], reverse=True)
    return out


def _read_setting(key):
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        conn.close()
        return row[0] if row else None
    except sqlite3.DatabaseError:
        return None


def _read_keep_days():
    val = _read_setting("backup_keep_days")
    try:
        if val:
            return max(1, int(val))
    except (ValueError, TypeError):
        pass
    return DEFAULT_KEEP_DAYS


def _should_run_now():
    """True if today's backup may be created now. With an optional fixed time
    set, wait until that time of day has passed (still catches up later)."""
    val = (_read_setting("backup_time") or "").strip()
    if not val:
        return True
    try:
        hh, mm = (int(x) for x in val.split(":")[:2])
    except (ValueError, TypeError):
        return True
    now = datetime.now()
    return (now.hour, now.minute) >= (hh, mm)


def _loop():
    while True:
        try:
            keep = _read_keep_days()
            if _should_run_now():
                write_daily_backup(keep)
            else:
                prune_backups(keep)
        except Exception:
            pass
        time.sleep(_CHECK_INTERVAL)


def start_scheduler():
    """Start the daily-backup daemon thread (idempotent per process)."""
    for t in threading.enumerate():
        if t.name == "backup-scheduler":
            return t
    t = threading.Thread(target=_loop, name="backup-scheduler", daemon=True)
    t.start()
    return t
