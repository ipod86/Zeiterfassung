from datetime import datetime, date, timedelta
from flask import (Blueprint, render_template, request, jsonify, session,
                   redirect, url_for, flash)
from ..db import get_db, log_activity, get_rates, get_recurring_tasks, get_settings
from ..util import (now_str, duration_seconds, worked_seconds, parse,
                    round_end_ts, round_seconds, FMT)
from .. import feedback_store


def _rounding_minutes():
    return get_settings().get("rounding_minutes", "0")


def _finalize_stop(db, row, ts):
    """Close a booking at ``ts``: fold any open pause into paused_seconds, round
    the NET worked time up, and set end_ts so that end - start - pause equals the
    rounded worked time (keeps displayed time, duration and amount consistent).
    Returns the rounded worked seconds."""
    paused = int(row["paused_seconds"] or 0)
    if row["pause_started_at"]:
        # round each pause phase up to a full minute (kurze Pausen >0 -> 1 Min)
        paused += round_seconds(duration_seconds(row["pause_started_at"], ts), 1)
    raw_worked = max(0, duration_seconds(row["start_ts"], ts) - paused)
    rounded = round_seconds(raw_worked, _rounding_minutes())
    end_ts = (parse(row["start_ts"]) + timedelta(seconds=paused + rounded)).strftime(FMT)
    db.execute(
        "UPDATE time_entries SET end_ts=?, paused_seconds=?, pause_started_at=NULL, "
        "updated_at=? WHERE id=? AND end_ts IS NULL",
        (end_ts, paused, ts, row["id"]),
    )
    return rounded

bp = Blueprint("main", __name__)


def _running_entry(db, user_id, project_id):
    return db.execute(
        "SELECT * FROM time_entries WHERE user_id=? AND project_id=? AND end_ts IS NULL",
        (user_id, project_id),
    ).fetchone()


def _resolve_rate(value, fallback):
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback or 0


def _stop_all_running(db, user_id):
    """Finalize the user's currently *running* timer(s).

    Only one timer may actively run at a time, but *paused* timers are left
    untouched so the user can interleave a short task and later resume the
    paused one as a single booking (avoiding a second rounding block)."""
    running = db.execute(
        "SELECT * FROM time_entries WHERE user_id=? AND end_ts IS NULL "
        "AND pause_started_at IS NULL", (user_id,)
    ).fetchall()
    ts = now_str()
    for r in running:
        _finalize_stop(db, r, ts)
    return running


def _now_active(db):
    """All currently running timers (any user) for the 'Jetzt aktiv' banner."""
    rows = db.execute(
        """SELECT t.id, t.start_ts, t.task, t.paused_seconds, t.pause_started_at,
                  u.name AS user_name, u.color,
                  p.name AS project_name, c.name AS customer_name
           FROM time_entries t
           JOIN users u ON u.id=t.user_id
           JOIN projects p ON p.id=t.project_id
           JOIN customers c ON c.id=p.customer_id
           WHERE t.end_ts IS NULL ORDER BY t.start_ts""",
    ).fetchall()
    return [dict(r,
                 elapsed=worked_seconds(r["start_ts"], None,
                                        r["paused_seconds"], r["pause_started_at"]),
                 paused=bool(r["pause_started_at"]))
            for r in rows]


def _build_board(db, uid):
    """Assemble the Erfassen rows for one user: split into the up-to-5
    most-recently-touched customers (``top``) and the alphabetical ``rest``,
    plus per-project consumed seconds for the budget bars. Shared by the full
    page and the /api/grid in-place refresh so the sorting stays identical."""
    today = date.today().strftime("%Y-%m-%d")
    customers = db.execute(
        "SELECT * FROM customers WHERE archived=0 ORDER BY name"
    ).fetchall()
    projects = db.execute(
        "SELECT * FROM projects WHERE archived=0 ORDER BY name"
    ).fetchall()
    projects_by_customer = {}
    project_lookup = {}
    for p in projects:
        projects_by_customer.setdefault(p["customer_id"], []).append(p)
        project_lookup[p["id"]] = p

    # There can be several open entries per user now: at most one actively
    # running, plus any number that are paused. Map them per customer so each
    # affected row renders its own running/paused controls. If a customer has
    # both, prefer the actively running one (so it stays controllable).
    open_by_customer = {}
    for o in db.execute(
        "SELECT * FROM time_entries WHERE user_id=? AND end_ts IS NULL", (uid,)
    ).fetchall():
        if o["project_id"] not in project_lookup:
            continue
        cid = project_lookup[o["project_id"]]["customer_id"]
        cur = open_by_customer.get(cid)
        if cur is None or (cur["pause_started_at"] and not o["pause_started_at"]):
            open_by_customer[cid] = o

    rows_act = db.execute(
        """SELECT t.project_id, t.task, t.rate, t.start_ts, t.end_ts, t.updated_at,
                  t.paused_seconds, t.pause_started_at, p.customer_id
           FROM time_entries t JOIN projects p ON p.id=t.project_id
           WHERE t.user_id=?""",
        (uid,),
    ).fetchall()
    last_act, today_secs, last_entry = {}, {}, {}
    for e in rows_act:
        cid = e["customer_id"]
        if not last_act.get(cid) or e["updated_at"] > last_act[cid]:
            last_act[cid] = e["updated_at"]
            last_entry[cid] = e
        if e["start_ts"][:10] == today:
            today_secs[cid] = today_secs.get(cid, 0) + \
                worked_seconds(e["start_ts"], e["end_ts"],
                               e["paused_seconds"], e["pause_started_at"])

    rows = []
    for c in customers:
        run = open_by_customer.get(c["id"])
        run_project = project_lookup.get(run["project_id"]) if run else None
        le = last_entry.get(c["id"])
        rows.append({
            "customer": c,
            "projects": projects_by_customer.get(c["id"], []),
            "running": run,
            "running_project": run_project,
            "running_elapsed": worked_seconds(
                run["start_ts"], None, run["paused_seconds"],
                run["pause_started_at"]) if run else 0,
            "running_paused": bool(run["pause_started_at"]) if run else False,
            "running_paused_min": (int(run["paused_seconds"] or 0) // 60) if run else 0,
            "last_activity": last_act.get(c["id"]),
            "today_secs": today_secs.get(c["id"], 0),
            "last_project_id": le["project_id"] if le else None,
            "last_rate": le["rate"] if le else None,
            "last_task": le["task"] if le else "",
        })

    touched = [r for r in rows if r["last_activity"]]
    touched.sort(key=lambda r: r["last_activity"], reverse=True)
    top = touched[:5]
    top_ids = {r["customer"]["id"] for r in top}
    rest = [r for r in rows if r["customer"]["id"] not in top_ids]
    rest.sort(key=lambda r: r["customer"]["name"].lower())

    proj_used = {}
    for e in db.execute(
        "SELECT project_id, start_ts, end_ts, paused_seconds, pause_started_at "
        "FROM time_entries"
    ).fetchall():
        proj_used[e["project_id"]] = proj_used.get(e["project_id"], 0) + \
            worked_seconds(e["start_ts"], e["end_ts"],
                           e["paused_seconds"], e["pause_started_at"])

    return {"customers": customers, "projects": projects,
            "top": top, "rest": rest, "proj_used": proj_used}


@bp.route("/")
def index():
    db = get_db()
    uid = session["user_id"]
    board = _build_board(db, uid)
    proj_used = board["proj_used"]

    try:
        warn_pct = float(get_settings().get("budget_warn_pct") or 80)
    except (TypeError, ValueError):
        warn_pct = 80.0
    cust_name = {c["id"]: c["name"] for c in board["customers"]}
    budget_alerts = []
    for p in board["projects"]:
        if p["budget"] and p["budget"] > 0:
            used_h = proj_used.get(p["id"], 0) / 3600.0
            pct = used_h / p["budget"] * 100
            if pct >= warn_pct:
                budget_alerts.append({
                    "id": p["id"], "name": p["name"],
                    "customer": cust_name.get(p["customer_id"], ""),
                    "used_h": round(used_h, 1), "budget": round(p["budget"], 1),
                    "pct": round(pct), "stage": 2 if pct >= 100 else 1,
                })

    return render_template("index.html", top=board["top"], rest=board["rest"],
                           customers=board["customers"], rates=get_rates(),
                           now_active=_now_active(db),
                           recurring_tasks=get_recurring_tasks(),
                           proj_used=proj_used, budget_alerts=budget_alerts,
                           warn_pct=warn_pct)


# ---------- API ----------

@bp.route("/api/timer/start", methods=["POST"])
def api_start():
    db = get_db()
    uid = session["user_id"]
    project_id = request.json.get("project_id")
    task = (request.json.get("task") or "").strip()
    p = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if not p:
        return jsonify(error="Projekt nicht gefunden"), 404
    rate = _resolve_rate(request.json.get("rate"), p["rate"])
    _stop_all_running(db, uid)  # single active timer per user
    ts = now_str()
    cur = db.execute(
        "INSERT INTO time_entries(user_id, user_name, project_id, task, rate, start_ts) "
        "VALUES(?,?,?,?,?,?)",
        (uid, session.get("user_name"), project_id, task, rate, ts),
    )
    db.commit()
    log_activity("timer_start", "entry", cur.lastrowid,
                 f"{p['name']}: {task}")
    return jsonify(ok=True, entry_id=cur.lastrowid, start_ts=ts)


@bp.route("/api/grid")
def api_grid():
    """Re-render the full, correctly-sorted Erfassen table body (+ refreshed
    'Jetzt aktiv' banner) so the client can swap it in place after
    start/stop/pause without a full page reload — keeping the top-5/alphabetical
    ordering identical to a fresh load."""
    db = get_db()
    uid = session["user_id"]
    board = _build_board(db, uid)
    html = render_template(
        "_grid_body.html", top=board["top"], rest=board["rest"],
        rates=get_rates(), recurring_tasks=get_recurring_tasks(),
        proj_used=board["proj_used"])
    banner = render_template("_active_banner.html", now_active=_now_active(db))
    return jsonify(ok=True, html=html, banner=banner)


@bp.route("/api/feedback", methods=["GET"])
def api_feedback_list():
    return jsonify(ok=True, items=feedback_store.all_items())


@bp.route("/api/feedback", methods=["POST"])
def api_feedback_add():
    d = request.json or {}
    kind = d.get("type")
    if kind not in ("bug", "feature"):
        return jsonify(error="Ungültiger Typ"), 400
    item = feedback_store.add(kind, session.get("user_name"), d.get("message"))
    if not item:
        return jsonify(error="Bitte eine Beschreibung eingeben."), 400
    log_activity("feedback", "feedback", item["id"], f"{item['type']}: {item['message']}")
    return jsonify(ok=True, item=item)


@bp.route("/api/feedback/<int:item_id>/toggle", methods=["POST"])
def api_feedback_toggle(item_id):
    d = request.json or {}
    state = feedback_store.toggle(item_id, d.get("done"))
    if state is None:
        return jsonify(error="Eintrag nicht gefunden"), 404
    return jsonify(ok=True, done=state)


@bp.route("/api/timer/stop", methods=["POST"])
def api_stop():
    db = get_db()
    uid = session["user_id"]
    entry_id = request.json.get("entry_id")
    e = db.execute(
        "SELECT * FROM time_entries WHERE id=? AND user_id=?", (entry_id, uid)
    ).fetchone()
    if not e:
        return jsonify(error="Buchung nicht gefunden"), 404
    # Already stopped (e.g. from another machine) — don't overwrite the end time.
    if e["end_ts"]:
        return jsonify(ok=True, already_stopped=True,
                       seconds=worked_seconds(e["start_ts"], e["end_ts"],
                                              e["paused_seconds"], e["pause_started_at"]))
    ts = now_str()
    secs = _finalize_stop(db, e, ts)
    db.commit()
    log_activity("timer_stop", "entry", entry_id, f"{secs}s")
    return jsonify(ok=True, seconds=secs)


@bp.route("/api/timer/pause", methods=["POST"])
def api_pause():
    db = get_db()
    uid = session["user_id"]
    entry_id = request.json.get("entry_id")
    e = db.execute("SELECT * FROM time_entries WHERE id=? AND user_id=?",
                   (entry_id, uid)).fetchone()
    if not e:
        return jsonify(error="Buchung nicht gefunden"), 404
    if e["end_ts"]:
        return jsonify(error="Buchung bereits beendet"), 400
    if e["pause_started_at"]:
        return jsonify(ok=True, paused=True)  # already paused
    ts = now_str()
    db.execute("UPDATE time_entries SET pause_started_at=?, updated_at=? "
               "WHERE id=? AND end_ts IS NULL", (ts, ts, entry_id))
    db.commit()
    log_activity("timer_pause", "entry", entry_id)
    return jsonify(ok=True, paused=True)


@bp.route("/api/timer/resume", methods=["POST"])
def api_resume():
    db = get_db()
    uid = session["user_id"]
    entry_id = request.json.get("entry_id")
    e = db.execute("SELECT * FROM time_entries WHERE id=? AND user_id=?",
                   (entry_id, uid)).fetchone()
    if not e:
        return jsonify(error="Buchung nicht gefunden"), 404
    if e["end_ts"]:
        return jsonify(error="Buchung bereits beendet"), 400
    if not e["pause_started_at"]:
        return jsonify(ok=True, paused=False)  # not paused
    # Only one timer may run at a time: stop any other running (non-paused)
    # timer before resuming this one.
    _stop_all_running(db, uid)
    ts = now_str()
    # round each pause phase up to a full minute (kurze Pausen >0 -> 1 Min)
    paused = int(e["paused_seconds"] or 0) + round_seconds(
        duration_seconds(e["pause_started_at"], ts), 1)
    db.execute("UPDATE time_entries SET paused_seconds=?, pause_started_at=NULL, "
               "updated_at=? WHERE id=? AND end_ts IS NULL", (paused, ts, entry_id))
    db.commit()
    log_activity("timer_resume", "entry", entry_id)
    return jsonify(ok=True, paused=False, paused_seconds=paused)


@bp.route("/api/entry/manual", methods=["POST"])
def api_manual():
    db = get_db()
    uid = session["user_id"]
    d = request.json
    project_id = d.get("project_id")
    day = d.get("date")
    start = d.get("start")
    end = d.get("end")
    task = (d.get("task") or "").strip()
    p = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if not p:
        return jsonify(error="Projekt nicht gefunden"), 404
    rate = _resolve_rate(d.get("rate"), p["rate"])
    try:
        start_ts = f"{day} {start}:00"
        end_ts = f"{day} {end}:00"
        if parse(end_ts) <= parse(start_ts):
            return jsonify(error="Ende muss nach Start liegen"), 400
    except Exception:
        return jsonify(error="Ungültige Zeitangabe"), 400
    end_ts = round_end_ts(start_ts, end_ts, _rounding_minutes())
    cur = db.execute(
        "INSERT INTO time_entries(user_id, user_name, project_id, task, rate, start_ts, end_ts, manual) "
        "VALUES(?,?,?,?,?,?,?,1)",
        (uid, session.get("user_name"), project_id, task, rate, start_ts, end_ts),
    )
    db.commit()
    log_activity("nachtrag", "entry", cur.lastrowid, f"{p['name']}: {task}")
    return jsonify(ok=True, entry_id=cur.lastrowid)


@bp.route("/api/project/quick", methods=["POST"])
def api_quick_project():
    db = get_db()
    d = request.json
    name = (d.get("name") or "").strip()
    customer_id = d.get("customer_id")
    new_customer = (d.get("new_customer") or "").strip()
    default_rate_id = d.get("default_rate_id")
    if not name:
        return jsonify(error="Projektname fehlt"), 400
    if new_customer:
        cur = db.execute("INSERT INTO customers(name) VALUES(?)", (new_customer,))
        customer_id = cur.lastrowid
        log_activity("kunde_angelegt", "customer", customer_id, new_customer)
    if not customer_id:
        return jsonify(error="Kunde fehlt"), 400
    rate = 0
    if default_rate_id:
        r = db.execute("SELECT amount FROM rates WHERE id=?", (default_rate_id,)).fetchone()
        if r:
            rate = r["amount"]
    cur = db.execute(
        "INSERT INTO projects(customer_id, name, rate, default_rate_id) VALUES(?,?,?,?)",
        (customer_id, name, rate, default_rate_id or None),
    )
    db.commit()
    log_activity("projekt_angelegt", "project", cur.lastrowid, name)
    return jsonify(ok=True, project_id=cur.lastrowid,
                   rate=rate, default_rate_id=default_rate_id)


@bp.route("/api/state")
def api_state():
    """Lightweight poll so users see each other's live activity."""
    db = get_db()
    uid = session["user_id"]
    mine = db.execute(
        "SELECT id, project_id, start_ts, paused_seconds, pause_started_at "
        "FROM time_entries WHERE user_id=? AND end_ts IS NULL", (uid,)
    ).fetchall()
    now_active = db.execute(
        """SELECT t.id, t.start_ts, t.task, t.paused_seconds, t.pause_started_at,
                  u.name AS user_name, u.color,
                  p.name AS project_name, c.name AS customer_name
           FROM time_entries t
           JOIN users u ON u.id=t.user_id
           JOIN projects p ON p.id=t.project_id
           JOIN customers c ON c.id=p.customer_id
           WHERE t.end_ts IS NULL ORDER BY t.start_ts""",
    ).fetchall()
    return jsonify(
        mine=[dict(m, elapsed=worked_seconds(m["start_ts"], None,
                                             m["paused_seconds"], m["pause_started_at"]),
                   paused=bool(m["pause_started_at"])) for m in mine],
        now_active=[dict(r, elapsed=worked_seconds(r["start_ts"], None,
                                                   r["paused_seconds"], r["pause_started_at"]),
                         paused=bool(r["pause_started_at"]))
                    for r in now_active],
    )


@bp.route("/api/entry/<int:entry_id>/delete", methods=["POST"])
def api_delete_entry(entry_id):
    db = get_db()
    e = db.execute("SELECT * FROM time_entries WHERE id=?", (entry_id,)).fetchone()
    if not e:
        return jsonify(error="nicht gefunden"), 404
    if e["billed"]:
        return jsonify(error="Bereits abgerechnet"), 400
    db.execute("DELETE FROM time_entries WHERE id=?", (entry_id,))
    db.commit()
    log_activity("buchung_geloescht", "entry", entry_id)
    return jsonify(ok=True)


@bp.route("/api/entry/<int:entry_id>/edit", methods=["POST"])
def api_edit_entry(entry_id):
    db = get_db()
    e = db.execute("SELECT * FROM time_entries WHERE id=?", (entry_id,)).fetchone()
    if not e:
        return jsonify(error="nicht gefunden"), 404
    if e["billed"]:
        return jsonify(error="Bereits abgerechnet"), 400
    if e["end_ts"] is None:
        return jsonify(error="Laufende Buchung — erst stoppen"), 400
    d = request.json
    task = (d.get("task") or "").strip()
    rate = _resolve_rate(d.get("rate"), e["rate"])
    try:
        start_ts = f"{d.get('date')} {d.get('start')}:00"
        end_ts = f"{d.get('date')} {d.get('end')}:00"
        if parse(end_ts) <= parse(start_ts):
            return jsonify(error="Ende muss nach Start liegen"), 400
    except Exception:
        return jsonify(error="Ungültige Zeitangabe"), 400
    # pause is editable here (minutes); fall back to the stored value if omitted
    if d.get("pause") in (None, ""):
        paused = int(e["paused_seconds"] or 0)
    else:
        try:
            paused = max(0, int(float(d.get("pause")))) * 60
        except (TypeError, ValueError):
            return jsonify(error="Ungültige Pausenangabe"), 400
    # round the NET worked time and shift end accordingly
    raw_worked = duration_seconds(start_ts, end_ts) - paused
    if raw_worked <= 0:
        return jsonify(error="Zeitraum kürzer als die Pause"), 400
    rounded = round_seconds(raw_worked, _rounding_minutes())
    end_ts = (parse(start_ts) + timedelta(seconds=paused + rounded)).strftime(FMT)
    db.execute(
        "UPDATE time_entries SET task=?, rate=?, start_ts=?, end_ts=?, "
        "paused_seconds=?, pause_started_at=NULL, updated_at=? WHERE id=?",
        (task, rate, start_ts, end_ts, paused, now_str(), entry_id),
    )
    db.commit()
    log_activity("buchung_bearbeitet", "entry", entry_id, task)
    return jsonify(ok=True)
