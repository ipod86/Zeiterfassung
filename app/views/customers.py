import csv
import io
from pathlib import Path
from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, session, send_file, abort, Response)
from ..db import (get_db, get_settings, log_activity, get_rates,
                  get_recurring_tasks, DATA_DIR)
from ..util import duration_seconds, worked_seconds, safe_filename, fmt_hours
from .billing import _collect_entries


def _rate_amount(db, rate_id):
    if not rate_id:
        return 0
    r = db.execute("SELECT amount FROM rates WHERE id=?", (rate_id,)).fetchone()
    return r["amount"] if r else 0

bp = Blueprint("customers", __name__, url_prefix="/uebersicht")


@bp.route("/")
def overview():
    db = get_db()
    show_archived = request.args.get("archiviert") == "1"
    cust_filter = "" if show_archived else "WHERE archived=0"
    customers = db.execute(
        f"SELECT * FROM customers {cust_filter} ORDER BY name"
    ).fetchall()

    projects = db.execute(
        """SELECT p.*, c.name AS customer_name FROM projects p
           JOIN customers c ON c.id=p.customer_id"""
    ).fetchall()

    # aggregate hours/amount per project + collect individual bookings
    entries = db.execute("SELECT t.* FROM time_entries t").fetchall()
    agg = {}
    bookings = {}
    for e in entries:
        secs = worked_seconds(e["start_ts"], e["end_ts"],
                              e["paused_seconds"], e["pause_started_at"])
        a = agg.setdefault(e["project_id"], {"secs": 0, "amount": 0.0,
                                             "open_secs": 0, "open_amount": 0.0})
        a["secs"] += secs
        a["amount"] += secs / 3600.0 * e["rate"]
        if not e["billed"]:
            a["open_secs"] += secs
            a["open_amount"] += secs / 3600.0 * e["rate"]
        bookings.setdefault(e["project_id"], []).append({
            "id": e["id"],
            "day": e["start_ts"][:10],
            "start": e["start_ts"],
            "start_hm": e["start_ts"][11:16],
            "end_hm": (e["end_ts"] or "")[11:16],
            "user_name": e["user_name"],
            "task": e["task"] or "",
            "secs": secs,
            "rate": e["rate"],
            "amount": secs / 3600.0 * e["rate"],
            "billed": e["billed"],
            "running": e["end_ts"] is None,
            "paused_min": (int(e["paused_seconds"] or 0) // 60),
        })
    for lst in bookings.values():
        lst.sort(key=lambda b: b["start"], reverse=True)

    by_customer = {}
    for p in projects:
        by_customer.setdefault(p["customer_id"], []).append(
            {"p": p, "agg": agg.get(p["id"], {"secs": 0, "amount": 0.0,
                                              "open_secs": 0, "open_amount": 0.0}),
             "bookings": bookings.get(p["id"], [])}
        )

    return render_template("overview.html", customers=customers,
                           by_customer=by_customer, show_archived=show_archived,
                           rates=get_rates(),
                           recurring_tasks=get_recurring_tasks())


# ---------- Customers ----------

@bp.route("/kunde/neu", methods=["POST"])
def customer_new():
    db = get_db()
    f = request.form
    name = (f.get("name") or "").strip()
    if not name:
        flash("Kundenname fehlt.", "error")
        return redirect(url_for("customers.overview"))
    cur = db.execute(
        """INSERT INTO customers(name, customer_no, contact, address, email, phone, vat_id, note)
           VALUES(?,?,?,?,?,?,?,?)""",
        (name, f.get("customer_no"), f.get("contact"), f.get("address"),
         f.get("email"), f.get("phone"), f.get("vat_id"), f.get("note")),
    )
    db.commit()
    log_activity("kunde_angelegt", "customer", cur.lastrowid, name)
    flash("Kunde angelegt.", "ok")
    return redirect(url_for("customers.overview"))


@bp.route("/kunde/<int:cid>/bearbeiten", methods=["POST"])
def customer_edit(cid):
    db = get_db()
    f = request.form
    db.execute(
        """UPDATE customers SET name=?, customer_no=?, contact=?, address=?, email=?,
           phone=?, vat_id=?, note=? WHERE id=?""",
        (f.get("name"), f.get("customer_no"), f.get("contact"), f.get("address"),
         f.get("email"), f.get("phone"), f.get("vat_id"), f.get("note"), cid),
    )
    db.commit()
    log_activity("kunde_bearbeitet", "customer", cid, f.get("name"))
    flash("Kunde gespeichert.", "ok")
    return redirect(url_for("customers.overview"))


@bp.route("/kunde/<int:cid>/loeschen", methods=["POST"])
def customer_delete(cid):
    db = get_db()
    n = db.execute(
        "SELECT COUNT(*) AS c FROM time_entries t JOIN projects p ON p.id=t.project_id "
        "WHERE p.customer_id=?", (cid,)
    ).fetchone()["c"]
    if n > 0:
        db.execute("UPDATE customers SET archived=1 WHERE id=?", (cid,))
        db.execute("UPDATE projects SET archived=1 WHERE customer_id=?", (cid,))
        msg = "Kunde hat Buchungen — archiviert statt gelöscht."
    else:
        db.execute("DELETE FROM projects WHERE customer_id=?", (cid,))
        db.execute("DELETE FROM customers WHERE id=?", (cid,))
        msg = "Kunde gelöscht."
    db.commit()
    log_activity("kunde_geloescht", "customer", cid)
    flash(msg, "ok")
    return redirect(url_for("customers.overview"))


@bp.route("/kunde/<int:cid>/reaktivieren", methods=["POST"])
def customer_restore(cid):
    db = get_db()
    db.execute("UPDATE customers SET archived=0 WHERE id=?", (cid,))
    db.commit()
    log_activity("kunde_reaktiviert", "customer", cid)
    return redirect(url_for("customers.overview", archiviert=1))


# ---------- Projects ----------

@bp.route("/projekt/neu", methods=["POST"])
def project_new():
    db = get_db()
    f = request.form
    name = (f.get("name") or "").strip()
    customer_id = f.get("customer_id", type=int)
    if not name or not customer_id:
        flash("Projektname und Kunde nötig.", "error")
        return redirect(url_for("customers.overview"))
    rate_id = f.get("default_rate_id", type=int)
    rate = _rate_amount(db, rate_id)
    budget = f.get("budget")
    budget = float(budget) if budget else None
    cur = db.execute(
        """INSERT INTO projects(customer_id, name, rate, default_rate_id, description, budget, color)
           VALUES(?,?,?,?,?,?,?)""",
        (customer_id, name, rate, rate_id or None, f.get("description"), budget, f.get("color")),
    )
    db.commit()
    log_activity("projekt_angelegt", "project", cur.lastrowid, name)
    flash("Projekt angelegt.", "ok")
    return redirect(url_for("customers.overview"))


@bp.route("/projekt/<int:pid>/bearbeiten", methods=["POST"])
def project_edit(pid):
    db = get_db()
    f = request.form
    rate_id = f.get("default_rate_id", type=int)
    rate = _rate_amount(db, rate_id)
    budget = f.get("budget")
    budget = float(budget) if budget else None
    db.execute(
        """UPDATE projects SET name=?, rate=?, default_rate_id=?, description=?,
           status=?, budget=?, color=? WHERE id=?""",
        (f.get("name"), rate, rate_id or None, f.get("description"),
         f.get("status") or "offen", budget, f.get("color"), pid),
    )
    db.commit()
    log_activity("projekt_bearbeitet", "project", pid, f.get("name"))
    flash("Projekt gespeichert.", "ok")
    return redirect(url_for("customers.overview"))


@bp.route("/projekt/<int:pid>/loeschen", methods=["POST"])
def project_delete(pid):
    db = get_db()
    n = db.execute("SELECT COUNT(*) AS c FROM time_entries WHERE project_id=?",
                   (pid,)).fetchone()["c"]
    if n > 0:
        db.execute("UPDATE projects SET archived=1 WHERE id=?", (pid,))
        msg = "Projekt hat Buchungen — archiviert statt gelöscht."
    else:
        db.execute("DELETE FROM projects WHERE id=?", (pid,))
        msg = "Projekt gelöscht."
    db.commit()
    log_activity("projekt_geloescht", "project", pid)
    flash(msg, "ok")
    return redirect(url_for("customers.overview"))


@bp.route("/projekt/<int:pid>/reaktivieren", methods=["POST"])
def project_restore(pid):
    db = get_db()
    db.execute("UPDATE projects SET archived=0 WHERE id=?", (pid,))
    db.commit()
    return redirect(url_for("customers.overview", archiviert=1))


# ---------- Open-bookings overview PDF ----------

def _group_by_project(entries):
    groups, order = {}, []
    for e in entries:
        key = e["project_name"]
        if key not in groups:
            groups[key] = {"project": key, "entries": [], "secs": 0, "amount": 0.0}
            order.append(key)
        g = groups[key]
        g["entries"].append(e)
        g["secs"] += e["secs"]
        g["amount"] += e["amount"]
    return [groups[k] for k in sorted(order, key=str.lower)]


@bp.route("/kunde/<int:cid>/offen/<fname>.pdf")
@bp.route("/kunde/<int:cid>/offen.pdf")
def customer_open_pdf(cid, fname=None):
    db = get_db()
    customer = db.execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone()
    if not customer:
        abort(404)
    entries = _collect_entries(db, cid, None, "", "")
    groups = _group_by_project(entries)
    from ..pdf import generate_open_overview_pdf
    out = DATA_DIR / "open" / f"offen-kunde-{cid}.pdf"
    generate_open_overview_pdf(out, get_settings(), customer, "alle Projekte", groups)
    return send_file(out, as_attachment=False,
                     download_name=f"Offene_Buchungen_{safe_filename(customer['name'])}.pdf")


@bp.route("/projekt/<int:pid>/offen/<fname>.pdf")
@bp.route("/projekt/<int:pid>/offen.pdf")
def project_open_pdf(pid, fname=None):
    db = get_db()
    p = db.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    if not p:
        abort(404)
    customer = db.execute("SELECT * FROM customers WHERE id=?",
                          (p["customer_id"],)).fetchone()
    entries = _collect_entries(db, p["customer_id"], pid, "", "")
    groups = _group_by_project(entries)
    from ..pdf import generate_open_overview_pdf
    out = DATA_DIR / "open" / f"offen-projekt-{pid}.pdf"
    generate_open_overview_pdf(out, get_settings(), customer, p["name"], groups)
    return send_file(out, as_attachment=False,
                     download_name=f"Offene_Buchungen_{safe_filename(customer['name'])}_"
                                   f"{safe_filename(p['name'])}.pdf")


def _open_csv_response(groups, basename):
    cur = get_settings().get("currency", "€")
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Projekt", "Datum", "Mitarbeiter", "Aufgabe",
                "Stunden", "Satz", "Betrag", "Währung"])
    for g in groups:
        for e in g["entries"]:
            hours = fmt_hours(e["secs"])
            w.writerow([g["project"], e["day"], e["user_name"] or "",
                        e["task"] or "", f"{hours:.2f}".replace(".", ","),
                        f"{e['rate']:.2f}".replace(".", ","),
                        f"{e['amount']:.2f}".replace(".", ","), cur])
    out = buf.getvalue().encode("utf-8-sig")
    return Response(
        out, mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={basename}.csv"},
    )


@bp.route("/kunde/<int:cid>/offen.csv")
def customer_open_csv(cid):
    db = get_db()
    customer = db.execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone()
    if not customer:
        abort(404)
    groups = _group_by_project(_collect_entries(db, cid, None, "", ""))
    return _open_csv_response(groups, f"Offene_Buchungen_{safe_filename(customer['name'])}")


@bp.route("/projekt/<int:pid>/offen.csv")
def project_open_csv(pid):
    db = get_db()
    p = db.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    if not p:
        abort(404)
    customer = db.execute("SELECT * FROM customers WHERE id=?",
                          (p["customer_id"],)).fetchone()
    groups = _group_by_project(_collect_entries(db, p["customer_id"], pid, "", ""))
    return _open_csv_response(
        groups, f"Offene_Buchungen_{safe_filename(customer['name'])}_{safe_filename(p['name'])}")
