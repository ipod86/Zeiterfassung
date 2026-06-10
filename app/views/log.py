from datetime import date, timedelta
from flask import Blueprint, render_template, request
from ..db import get_db
from ..util import duration_seconds, fmt_hours

bp = Blueprint("log", __name__, url_prefix="/protokoll")


@bp.route("/")
def index():
    db = get_db()
    user_id = request.args.get("user_id", type=int)
    dfrom = request.args.get("from") or ""
    dto = request.args.get("to") or ""

    sql = "SELECT * FROM activity_log WHERE 1=1"
    args = []
    if user_id:
        sql += " AND user_id=?"
        args.append(user_id)
    if dfrom:
        sql += " AND date(created_at) >= ?"
        args.append(dfrom)
    if dto:
        sql += " AND date(created_at) <= ?"
        args.append(dto)
    sql += " ORDER BY id DESC LIMIT 500"
    rows = db.execute(sql, args).fetchall()

    users = db.execute("SELECT * FROM users ORDER BY name").fetchall()

    # mini dashboard: hours per user (last 7 days)
    since = (date.today() - timedelta(days=7)).strftime("%Y-%m-%d")
    entries = db.execute(
        """SELECT t.*, u.name AS user_name, u.color FROM time_entries t
           JOIN users u ON u.id=t.user_id WHERE date(t.start_ts) >= ?""",
        (since,),
    ).fetchall()
    stats = {}
    for e in entries:
        secs = duration_seconds(e["start_ts"], e["end_ts"])
        st = stats.setdefault(e["user_name"], {"secs": 0, "color": e["color"]})
        st["secs"] += secs
    stats = sorted(
        ({"name": k, "hours": fmt_hours(v["secs"]), "color": v["color"]}
         for k, v in stats.items()),
        key=lambda x: x["hours"], reverse=True,
    )

    return render_template("log.html", rows=rows, users=users,
                           user_id=user_id, dfrom=dfrom, dto=dto, stats=stats)
