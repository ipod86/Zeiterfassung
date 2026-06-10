import random
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from ..db import get_db, log_activity

bp = Blueprint("auth", __name__)

PALETTE = ["#4f46e5", "#059669", "#dc2626", "#d97706", "#7c3aed",
           "#0891b2", "#db2777", "#65a30d", "#2563eb", "#ea580c"]


@bp.route("/login")
def login():
    users = get_db().execute(
        "SELECT * FROM users WHERE active=1 ORDER BY name"
    ).fetchall()
    return render_template("login.html", users=users)


@bp.route("/login", methods=["POST"])
def do_login():
    user_id = request.form.get("user_id", type=int)
    user = get_db().execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        flash("Bitte einen Nutzer wählen.", "error")
        return redirect(url_for("auth.login"))
    session["user_id"] = user["id"]
    session["user_name"] = user["name"]
    session.permanent = True
    return redirect(url_for("main.index"))


@bp.route("/users/add", methods=["POST"], endpoint="add_user")
def add_user():
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Name fehlt.", "error")
        return redirect(url_for("auth.login"))
    db = get_db()
    exists = db.execute("SELECT id FROM users WHERE name=?", (name,)).fetchone()
    if exists:
        flash("Name existiert bereits.", "error")
        return redirect(url_for("auth.login"))
    color = random.choice(PALETTE)
    cur = db.execute("INSERT INTO users(name, color) VALUES(?, ?)", (name, color))
    db.commit()
    session["user_id"] = cur.lastrowid
    session["user_name"] = name
    log_activity("nutzer_angelegt", "user", cur.lastrowid, name)
    return redirect(url_for("main.index"))


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
