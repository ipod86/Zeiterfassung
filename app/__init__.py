from pathlib import Path
from flask import Flask, session, redirect, url_for, request, g

from . import db
from .util import fmt_hms, fmt_hours, fmt_hm, money, safe_filename


def create_app():
    app = Flask(__name__, instance_relative_config=False)
    app.config["SECRET_KEY"] = "zeiterfassung-local-secret-change-if-you-like"
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024  # logo upload + backup restore (ZIP)
    app.config["UPLOAD_DIR"] = str(db.DATA_DIR / "uploads")
    Path(app.config["UPLOAD_DIR"]).mkdir(parents=True, exist_ok=True)

    db.init_db(app)
    app.teardown_appcontext(db.close_db)

    # template helpers
    app.jinja_env.filters["hms"] = fmt_hms
    app.jinja_env.filters["hours"] = fmt_hours
    app.jinja_env.filters["hm"] = fmt_hm
    app.jinja_env.filters["safe_filename"] = safe_filename

    @app.context_processor
    def inject_globals():
        s = db.get_settings()
        # theme (hell/dunkel) is stored per user; fall back to the global default
        user_theme = s.get("theme_mode") or "light"
        uid = session.get("user_id")
        if uid:
            row = db.get_db().execute(
                "SELECT theme_mode FROM users WHERE id=?", (uid,)
            ).fetchone()
            if row and row["theme_mode"]:
                user_theme = row["theme_mode"]
        return {
            "settings": s,
            "user_theme": user_theme,
            "current_user_id": uid,
            "current_user_name": session.get("user_name"),
            "money": lambda v: money(v, s.get("currency", "€")),
        }

    # auth gate: require a selected user for everything except login + static
    @app.before_request
    def require_user():
        endpoint = request.endpoint or ""
        if endpoint in ("auth.login", "auth.do_login", "static", "auth.add_user"):
            return None
        if endpoint.startswith("uploads"):
            return None
        if "user_id" not in session:
            return redirect(url_for("auth.login"))
        return None

    from .views import auth, main, customers, billing, log, settings as settings_view
    app.register_blueprint(auth.bp)
    app.register_blueprint(main.bp)
    app.register_blueprint(customers.bp)
    app.register_blueprint(billing.bp)
    app.register_blueprint(log.bp)
    app.register_blueprint(settings_view.bp)

    # serve uploaded logo
    from flask import send_from_directory

    @app.route("/uploads/<path:filename>", endpoint="uploads")
    def uploads(filename):
        return send_from_directory(app.config["UPLOAD_DIR"], filename)

    return app
