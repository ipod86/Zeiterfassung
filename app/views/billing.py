import csv
import io
from datetime import date
from pathlib import Path
from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, session, send_file, Response, abort)
from ..db import get_db, get_settings, log_activity, DATA_DIR
from ..util import (duration_seconds, worked_seconds, round_seconds,
                    fmt_hours, money, safe_filename)

bp = Blueprint("billing", __name__, url_prefix="/abrechnen")


def _collect_entries(db, customer_id, project_id, dfrom, dto):
    """Unbilled, completed entries matching the filter."""
    sql = """SELECT t.*, p.name AS project_name
             FROM time_entries t
             JOIN projects p ON p.id=t.project_id
             WHERE p.customer_id=? AND t.billed=0 AND t.end_ts IS NOT NULL"""
    args = [customer_id]
    if project_id:
        sql += " AND t.project_id=?"
        args.append(project_id)
    if dfrom:
        sql += " AND date(t.start_ts) >= ?"
        args.append(dfrom)
    if dto:
        sql += " AND date(t.start_ts) <= ?"
        args.append(dto)
    sql += " ORDER BY t.start_ts"
    rows = db.execute(sql, args).fetchall()
    s = get_settings()
    rm = s.get("rounding_minutes", "0")
    out = []
    for r in rows:
        secs = round_seconds(
            worked_seconds(r["start_ts"], r["end_ts"],
                           r["paused_seconds"], r["pause_started_at"]), rm)
        out.append({
            "id": r["id"],
            "day": r["start_ts"][:10],
            "task": r["task"],
            "project_name": r["project_name"],
            "user_name": r["user_name"],
            "rate": r["rate"],
            "secs": secs,
            "amount": fmt_hours(secs) * r["rate"],
        })
    return out


@bp.route("/")
def index():
    db = get_db()
    customers = db.execute(
        "SELECT * FROM customers WHERE archived=0 ORDER BY name"
    ).fetchall()

    customer_id = request.args.get("customer_id", type=int)
    project_id = request.args.get("project_id", type=int)
    dfrom = request.args.get("from") or ""
    dto = request.args.get("to") or ""
    typ = request.args.get("type") or "zwischen"

    projects = []
    entries = []
    customer = None
    subtotal = tax_amount = total = 0.0
    s = get_settings()
    tax_rate = float(s.get("tax_rate") or 0)

    if customer_id:
        customer = db.execute("SELECT * FROM customers WHERE id=?",
                              (customer_id,)).fetchone()
        projects = db.execute(
            "SELECT * FROM projects WHERE customer_id=? ORDER BY name",
            (customer_id,)
        ).fetchall()
        entries = _collect_entries(db, customer_id, project_id, dfrom, dto)
        subtotal = sum(e["amount"] for e in entries)
        tax_amount = subtotal * tax_rate / 100.0
        total = subtotal + tax_amount

    # customers with open balances (unbilled, completed entries across all projects)
    rm = s.get("rounding_minutes", "0")
    open_rows = db.execute(
        """SELECT c.id AS cid, c.name AS cname, t.start_ts, t.end_ts, t.rate,
                  t.paused_seconds, t.pause_started_at
           FROM time_entries t
           JOIN projects p ON p.id=t.project_id
           JOIN customers c ON c.id=p.customer_id
           WHERE t.billed=0 AND t.end_ts IS NOT NULL AND c.archived=0"""
    ).fetchall()
    open_map = {}
    for r in open_rows:
        secs = round_seconds(
            worked_seconds(r["start_ts"], r["end_ts"],
                           r["paused_seconds"], r["pause_started_at"]), rm)
        o = open_map.setdefault(r["cid"],
                                {"id": r["cid"], "name": r["cname"],
                                 "secs": 0, "amount": 0.0})
        o["secs"] += secs
        o["amount"] += fmt_hours(secs) * r["rate"]
    open_balances = sorted(open_map.values(),
                           key=lambda x: x["amount"], reverse=True)
    open_total = sum(o["amount"] for o in open_balances)

    invoices = db.execute(
        """SELECT i.*, c.name AS customer_name, u.name AS by_name,
                  p.name AS project_name
           FROM invoices i
           LEFT JOIN customers c ON c.id=i.customer_id
           LEFT JOIN users u ON u.id=i.created_by
           LEFT JOIN projects p ON p.id=i.project_id
           ORDER BY i.id DESC LIMIT 50"""
    ).fetchall()

    return render_template(
        "billing.html", customers=customers, projects=projects,
        entries=entries, customer=customer, customer_id=customer_id,
        project_id=project_id, dfrom=dfrom, dto=dto, typ=typ,
        subtotal=subtotal, tax_amount=tax_amount, total=total,
        tax_rate=tax_rate, invoices=invoices,
        open_balances=open_balances, open_total=open_total,
    )


@bp.route("/erstellen", methods=["POST"])
def create():
    db = get_db()
    f = request.form
    customer_id = f.get("customer_id", type=int)
    project_id = f.get("project_id", type=int)
    dfrom = f.get("from") or ""
    dto = f.get("to") or ""
    typ = f.get("type") or "zwischen"
    if not customer_id:
        flash("Kein Kunde gewählt.", "error")
        return redirect(url_for("billing.index"))

    customer = db.execute("SELECT * FROM customers WHERE id=?",
                          (customer_id,)).fetchone()
    entries = _collect_entries(db, customer_id, project_id, dfrom, dto)
    if not entries:
        flash("Keine abrechenbaren Buchungen im Zeitraum.", "error")
        return redirect(url_for("billing.index", customer_id=customer_id,
                                project_id=project_id, **{"from": dfrom, "to": dto}))

    s = get_settings()
    tax_rate = float(s.get("tax_rate") or 0)
    subtotal = sum(e["amount"] for e in entries)
    tax_amount = subtotal * tax_rate / 100.0
    total = subtotal + tax_amount

    cur = db.execute(
        """INSERT INTO invoices(customer_id, project_id, type, created_by,
           period_from, period_to, subtotal, tax_rate, tax_amount, total)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (customer_id, project_id or None, typ, session["user_id"],
         dfrom or None, dto or None, subtotal, tax_rate, tax_amount, total),
    )
    invoice_id = cur.lastrowid
    ids = [e["id"] for e in entries]
    db.executemany(
        "UPDATE time_entries SET billed=1, invoice_id=? WHERE id=?",
        [(invoice_id, eid) for eid in ids],
    )

    meta = {
        "type": typ, "tax_rate": tax_rate,
        "created_at": date.today().strftime("%d.%m.%Y"),
        "period_from": dfrom, "period_to": dto,
    }
    from ..pdf import generate_invoice_pdf
    pdf_path = DATA_DIR / "invoices" / f"Leistungsnachweis-{invoice_id}.pdf"
    generate_invoice_pdf(pdf_path, s, customer, meta, entries)
    db.execute("UPDATE invoices SET pdf_path=? WHERE id=?", (str(pdf_path), invoice_id))
    db.commit()
    log_activity("abgerechnet", "invoice", invoice_id,
                 f"{customer['name']} · {money(total, s['currency'])}")
    flash("Aufstellung erstellt.", "ok")
    return redirect(url_for("billing.pdf", invoice_id=invoice_id))


def _regenerate_pdf(db, inv):
    """Rebuild the PDF from the stored entries (e.g. after the file was lost)."""
    s = get_settings()
    customer = db.execute("SELECT * FROM customers WHERE id=?",
                          (inv["customer_id"],)).fetchone()
    rows = db.execute(
        """SELECT t.*, p.name AS project_name
           FROM time_entries t JOIN projects p ON p.id=t.project_id
           WHERE t.invoice_id=? ORDER BY t.start_ts""", (inv["id"],)
    ).fetchall()
    rm = s.get("rounding_minutes", "0")
    entries = []
    for r in rows:
        secs = round_seconds(
            worked_seconds(r["start_ts"], r["end_ts"],
                           r["paused_seconds"], r["pause_started_at"]), rm)
        entries.append({
            "day": r["start_ts"][:10], "task": r["task"],
            "project_name": r["project_name"], "rate": r["rate"], "secs": secs,
        })
    meta = {
        "type": inv["type"], "tax_rate": inv["tax_rate"],
        "created_at": (inv["created_at"] or "")[:10],
        "period_from": inv["period_from"], "period_to": inv["period_to"],
    }
    from ..pdf import generate_invoice_pdf
    pdf_path = inv["pdf_path"] or str(DATA_DIR / "invoices" / f"Leistungsnachweis-{inv['id']}.pdf")
    generate_invoice_pdf(pdf_path, s, customer, meta, entries)
    if not inv["pdf_path"]:
        db.execute("UPDATE invoices SET pdf_path=? WHERE id=?", (pdf_path, inv["id"]))
        db.commit()
    return pdf_path


def _download_basename(db, inv):
    cust = db.execute("SELECT name FROM customers WHERE id=?",
                      (inv["customer_id"],)).fetchone()
    name = cust["name"] if cust else f"Kunde-{inv['customer_id']}"
    parts = ["Leistungsnachweis", safe_filename(name)]
    if inv["project_id"]:
        proj = db.execute("SELECT name FROM projects WHERE id=?",
                          (inv["project_id"],)).fetchone()
        if proj:
            parts.append(safe_filename(proj["name"]))
    datum = (inv["created_at"] or "")[:10]
    if datum:
        parts.append(datum)
    return "_".join(parts)


@bp.route("/rechnung/<int:invoice_id>/<fname>.pdf")
@bp.route("/rechnung/<int:invoice_id>/pdf")
def pdf(invoice_id, fname=None):
    db = get_db()
    inv = db.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    if not inv:
        abort(404)
    path = inv["pdf_path"]
    if not path or not Path(path).exists():
        path = _regenerate_pdf(db, inv)
    return send_file(path, as_attachment=False,
                     download_name=f"{_download_basename(db, inv)}.pdf")


@bp.route("/rechnung/<int:invoice_id>/<fname>.csv")
@bp.route("/rechnung/<int:invoice_id>/csv")
def csv_export(invoice_id, fname=None):
    db = get_db()
    inv = db.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    if not inv:
        abort(404)
    rows = db.execute(
        """SELECT t.*, p.name AS project_name
           FROM time_entries t JOIN projects p ON p.id=t.project_id
           WHERE t.invoice_id=? ORDER BY t.start_ts""", (invoice_id,)
    ).fetchall()
    rm = get_settings().get("rounding_minutes", "0")
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Datum", "Start", "Ende", "Projekt", "Mitarbeiter", "Aufgabe",
                "Stunden", "Satz", "Betrag"])
    for r in rows:
        secs = round_seconds(
            worked_seconds(r["start_ts"], r["end_ts"],
                           r["paused_seconds"], r["pause_started_at"]), rm)
        hours = fmt_hours(secs)
        w.writerow([r["start_ts"][:10], r["start_ts"][11:16],
                    (r["end_ts"] or "")[11:16], r["project_name"], r["user_name"],
                    r["task"] or "", f"{hours:.2f}".replace(".", ","),
                    f"{r['rate']:.2f}".replace(".", ","),
                    f"{hours * r['rate']:.2f}".replace(".", ",")])
    out = buf.getvalue().encode("utf-8-sig")
    return Response(
        out, mimetype="text/csv",
        headers={"Content-Disposition":
                 f"attachment; filename={_download_basename(db, inv)}.csv"},
    )


@bp.route("/rechnung/<int:invoice_id>/storno", methods=["POST"])
def storno(invoice_id):
    db = get_db()
    inv = db.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    if not inv:
        abort(404)
    db.execute("UPDATE time_entries SET billed=0, invoice_id=NULL WHERE invoice_id=?",
               (invoice_id,))
    if inv["pdf_path"] and Path(inv["pdf_path"]).exists():
        try:
            Path(inv["pdf_path"]).unlink()
        except OSError:
            pass
    db.execute("DELETE FROM invoices WHERE id=?", (invoice_id,))
    db.commit()
    log_activity("aufstellung_geloescht", "invoice", invoice_id)
    flash("Aufstellung gelöscht, Buchungen wieder offen.", "ok")
    return redirect(url_for("billing.index"))
