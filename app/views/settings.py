import os
import io
import sqlite3
import tempfile
import zipfile
from datetime import date, datetime
from pathlib import Path
from werkzeug.utils import secure_filename
from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, current_app, send_file, session)
from ..db import (get_db, get_settings, set_setting, log_activity, get_rates,
                  get_recurring_tasks, DATA_DIR)
from ..util import image_size
from ..backup import build_backup_zip, list_backups, BACKUP_DIR

bp = Blueprint("settings", __name__, url_prefix="/einstellungen")

TEXT_KEYS = ["company_name", "company_address", "company_email", "company_phone",
             "company_vat", "currency", "tax_rate", "rounding_minutes",
             "budget_warn_pct", "backup_keep_days", "backup_time", "theme_primary"]
ALLOWED_LOGO = {".png", ".jpg", ".jpeg", ".gif"}


@bp.route("/")
def index():
    from flask import session
    db = get_db()
    users = db.execute("SELECT * FROM users ORDER BY name").fetchall()
    user_theme = "light"
    uid = session.get("user_id")
    if uid:
        row = db.execute("SELECT theme_mode FROM users WHERE id=?", (uid,)).fetchone()
        if row and row["theme_mode"]:
            user_theme = row["theme_mode"]
    return render_template("settings.html", users=users, s=get_settings(),
                           user_theme=user_theme,
                           rates=get_rates(active_only=False),
                           recurring_tasks=get_recurring_tasks(active_only=False),
                           auto_backups=list_backups())


@bp.route("/speichern", methods=["POST"])
def save():
    from flask import session
    f = request.form
    for key in TEXT_KEYS:
        if key in f:
            set_setting(key, f.get(key).strip())

    # theme mode (hell/dunkel) is stored per user, not globally
    mode = f.get("theme_mode")
    uid = session.get("user_id")
    if mode in ("light", "dark") and uid:
        get_db().execute("UPDATE users SET theme_mode=? WHERE id=?", (mode, uid))
        get_db().commit()

    file = request.files.get("logo")
    if file and file.filename:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext in ALLOWED_LOGO:
            fname = "logo" + ext
            dest = Path(current_app.config["UPLOAD_DIR"]) / fname
            file.save(dest)
            set_setting("logo_path", str(dest))
            set_setting("logo_file", fname)
            size = image_size(dest)
            set_setting("logo_w", str(size[0]) if size else "")
            set_setting("logo_h", str(size[1]) if size else "")
        else:
            flash("Logo muss PNG/JPG/GIF sein.", "error")
    log_activity("einstellungen_gespeichert", "settings")
    flash("Einstellungen gespeichert.", "ok")
    return redirect(url_for("settings.index"))


@bp.route("/logo/entfernen", methods=["POST"])
def remove_logo():
    s = get_settings()
    if s.get("logo_path") and Path(s["logo_path"]).exists():
        try:
            Path(s["logo_path"]).unlink()
        except OSError:
            pass
    set_setting("logo_path", "")
    set_setting("logo_file", "")
    set_setting("logo_w", "")
    set_setting("logo_h", "")
    flash("Logo entfernt.", "ok")
    return redirect(url_for("settings.index"))


@bp.route("/backup")
def backup():
    buf = build_backup_zip()
    fname = f"zeiterfassung-backup-{date.today():%Y-%m-%d}.zip"
    return send_file(buf, mimetype="application/zip",
                     as_attachment=True, download_name=fname)


@bp.route("/backup/auto/<name>")
def backup_auto(name):
    # only allow downloading files that match our auto-backup naming pattern
    safe = secure_filename(name)
    if (safe != name or not safe.startswith("zeiterfassung-backup-")
            or not safe.endswith(".zip")):
        flash("Ungültiger Dateiname.", "error")
        return redirect(url_for("settings.index"))
    path = BACKUP_DIR / safe
    if not path.exists():
        flash("Sicherung nicht gefunden.", "error")
        return redirect(url_for("settings.index"))
    return send_file(path, mimetype="application/zip",
                     as_attachment=True, download_name=safe)


REQUIRED_TABLES = {"users", "customers", "projects", "time_entries", "settings"}


@bp.route("/restore", methods=["POST"])
def restore():
    file = request.files.get("backup")
    if not file or not file.filename:
        flash("Keine Datei gewählt.", "error")
        return redirect(url_for("settings.index"))
    if not file.filename.lower().endswith(".zip"):
        flash("Bitte die heruntergeladene ZIP-Datei hochladen.", "error")
        return redirect(url_for("settings.index"))

    try:
        zf = zipfile.ZipFile(io.BytesIO(file.read()))
    except zipfile.BadZipFile:
        flash("Datei ist kein gültiges ZIP.", "error")
        return redirect(url_for("settings.index"))
    names = zf.namelist()
    if "zeiterfassung.db" not in names:
        flash("ZIP enthält keine zeiterfassung.db — kein gültiges Backup.", "error")
        return redirect(url_for("settings.index"))

    with tempfile.TemporaryDirectory() as td:
        tmp_db = Path(td) / "restore.db"
        tmp_db.write_bytes(zf.read("zeiterfassung.db"))
        # validate the uploaded database before touching anything live
        try:
            tcon = sqlite3.connect(str(tmp_db))
            ok = tcon.execute("PRAGMA integrity_check").fetchone()[0]
            tabs = {r[0] for r in tcon.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            tcon.close()
        except sqlite3.DatabaseError:
            ok, tabs = "fehlerhaft", set()
        if ok != "ok" or not REQUIRED_TABLES.issubset(tabs):
            flash("Backup-Datenbank ist beschädigt oder unvollständig — "
                  "Restore abgebrochen, nichts geändert.", "error")
            return redirect(url_for("settings.index"))

        dest = get_db()
        # 1) safety copy of the CURRENT database (in case the restore is unwanted)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        bak_path = DATA_DIR / f"zeiterfassung-vor-restore-{stamp}.db"
        try:
            bcon = sqlite3.connect(str(bak_path))
            dest.backup(bcon)
            bcon.close()
        except sqlite3.DatabaseError:
            pass
        # 2) overwrite the live db contents in-place via SQLite's backup API
        #    (no file swap -> no Windows file-lock / WAL issues)
        src = sqlite3.connect(str(tmp_db))
        src.backup(dest)
        src.close()
        dest.commit()

        # 3) restore uploaded files (logo etc.)
        updir = Path(current_app.config["UPLOAD_DIR"])
        updir.mkdir(parents=True, exist_ok=True)
        for n in names:
            if n.startswith("uploads/") and not n.endswith("/"):
                safe = secure_filename(Path(n).name)
                if safe:
                    (updir / safe).write_bytes(zf.read(n))

    # the restored database has its own user set — force a fresh login
    session.clear()
    flash("Backup eingespielt. Eine Sicherung der vorherigen Datenbank wurde "
          f"als „{bak_path.name}“ im data-Ordner abgelegt. Bitte neu anmelden.", "ok")
    return redirect(url_for("auth.login"))


@bp.route("/satz/neu", methods=["POST"])
def rate_new():
    db = get_db()
    label = (request.form.get("label") or "").strip()
    try:
        amount = float(request.form.get("amount") or 0)
    except ValueError:
        amount = 0
    if not label:
        flash("Bezeichnung fehlt.", "error")
        return redirect(url_for("settings.index"))
    mx = db.execute("SELECT COALESCE(MAX(sort),0) AS m FROM rates").fetchone()["m"]
    db.execute("INSERT INTO rates(label, amount, sort) VALUES(?,?,?)",
               (label, amount, mx + 1))
    db.commit()
    log_activity("satz_angelegt", "rate", None, f"{label} {amount}")
    flash("Satz angelegt.", "ok")
    return redirect(url_for("settings.index"))


@bp.route("/satz/<int:rid>/bearbeiten", methods=["POST"])
def rate_edit(rid):
    db = get_db()
    label = (request.form.get("label") or "").strip()
    try:
        amount = float(request.form.get("amount") or 0)
    except ValueError:
        amount = 0
    active = 1 if request.form.get("active") else 0
    db.execute("UPDATE rates SET label=?, amount=?, active=? WHERE id=?",
               (label, amount, active, rid))
    db.commit()
    log_activity("satz_bearbeitet", "rate", rid, f"{label} {amount}")
    flash("Satz gespeichert.", "ok")
    return redirect(url_for("settings.index"))


@bp.route("/satz/<int:rid>/loeschen", methods=["POST"])
def rate_delete(rid):
    db = get_db()
    used = db.execute("SELECT COUNT(*) AS c FROM projects WHERE default_rate_id=?",
                      (rid,)).fetchone()["c"]
    if used:
        db.execute("UPDATE rates SET active=0 WHERE id=?", (rid,))
        flash("Satz wird von Projekten genutzt — deaktiviert statt gelöscht.", "ok")
    else:
        db.execute("DELETE FROM rates WHERE id=?", (rid,))
        flash("Satz gelöscht.", "ok")
    db.commit()
    log_activity("satz_geloescht", "rate", rid)
    return redirect(url_for("settings.index"))


@bp.route("/nutzer/neu", methods=["POST"])
def user_new():
    db = get_db()
    name = (request.form.get("name") or "").strip()
    color = request.form.get("color") or "#4f46e5"
    if not name:
        flash("Name fehlt.", "error")
        return redirect(url_for("settings.index"))
    if db.execute("SELECT id FROM users WHERE name=?", (name,)).fetchone():
        flash("Name existiert bereits.", "error")
        return redirect(url_for("settings.index"))
    cur = db.execute("INSERT INTO users(name, color) VALUES(?,?)", (name, color))
    db.commit()
    log_activity("nutzer_angelegt", "user", cur.lastrowid, name)
    flash("Nutzer angelegt.", "ok")
    return redirect(url_for("settings.index"))


@bp.route("/taetigkeit/neu", methods=["POST"])
def rectask_new():
    db = get_db()
    text = (request.form.get("text") or "").strip()
    if not text:
        flash("Text fehlt.", "error")
        return redirect(url_for("settings.index"))
    mx = db.execute("SELECT COALESCE(MAX(sort),0) AS m FROM recurring_tasks").fetchone()["m"]
    db.execute("INSERT INTO recurring_tasks(text, sort) VALUES(?,?)", (text, mx + 1))
    db.commit()
    log_activity("taetigkeit_angelegt", "recurring_task", None, text)
    flash("Tätigkeit angelegt.", "ok")
    return redirect(url_for("settings.index"))


@bp.route("/taetigkeit/<int:tid>/bearbeiten", methods=["POST"])
def rectask_edit(tid):
    db = get_db()
    text = (request.form.get("text") or "").strip()
    active = 1 if request.form.get("active") else 0
    db.execute("UPDATE recurring_tasks SET text=?, active=? WHERE id=?",
               (text, active, tid))
    db.commit()
    log_activity("taetigkeit_bearbeitet", "recurring_task", tid, text)
    flash("Tätigkeit gespeichert.", "ok")
    return redirect(url_for("settings.index"))


@bp.route("/taetigkeit/<int:tid>/loeschen", methods=["POST"])
def rectask_delete(tid):
    db = get_db()
    db.execute("DELETE FROM recurring_tasks WHERE id=?", (tid,))
    db.commit()
    log_activity("taetigkeit_geloescht", "recurring_task", tid)
    flash("Tätigkeit gelöscht.", "ok")
    return redirect(url_for("settings.index"))


@bp.route("/nutzer/<int:uid>/bearbeiten", methods=["POST"])
def user_edit(uid):
    db = get_db()
    name = (request.form.get("name") or "").strip()
    color = request.form.get("color") or "#4f46e5"
    active = 1 if request.form.get("active") else 0
    db.execute("UPDATE users SET name=?, color=?, active=? WHERE id=?",
               (name, color, active, uid))
    # keep denormalized names on bookings in sync after a rename
    if name:
        db.execute("UPDATE time_entries SET user_name=? WHERE user_id=?", (name, uid))
    db.commit()
    log_activity("nutzer_bearbeitet", "user", uid, name)
    flash("Nutzer gespeichert.", "ok")
    return redirect(url_for("settings.index"))


@bp.route("/nutzer/<int:uid>/loeschen", methods=["POST"])
def user_delete(uid):
    from flask import session
    from ..util import now_str
    db = get_db()
    u = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u:
        flash("Nutzer nicht gefunden.", "error")
        return redirect(url_for("settings.index"))
    if uid == session.get("user_id"):
        flash("Der aktuell angemeldete Nutzer kann nicht gelöscht werden.", "error")
        return redirect(url_for("settings.index"))
    if db.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"] <= 1:
        flash("Der letzte Nutzer kann nicht gelöscht werden.", "error")
        return redirect(url_for("settings.index"))
    ts = now_str()
    # stop any running timers and preserve the name on every booking
    db.execute("UPDATE time_entries SET end_ts=?, updated_at=? "
               "WHERE user_id=? AND end_ts IS NULL", (ts, ts, uid))
    db.execute("UPDATE time_entries SET user_name=COALESCE(user_name, ?) WHERE user_id=?",
               (u["name"], uid))
    # detach from invoices (FK without cascade) then hard-delete the user;
    # time_entries.user_id is set NULL via ON DELETE SET NULL, names stay intact
    db.execute("UPDATE invoices SET created_by=NULL WHERE created_by=?", (uid,))
    db.execute("DELETE FROM users WHERE id=?", (uid,))
    db.commit()
    log_activity("nutzer_geloescht", "user", uid, u["name"])
    flash("Nutzer gelöscht. Buchungen bleiben mit Namen erhalten.", "ok")
    return redirect(url_for("settings.index"))
