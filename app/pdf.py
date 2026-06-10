from datetime import date
from pathlib import Path
from fpdf import FPDF
from .util import money, fmt_hours, fmt_hm_long


class InvoicePDF(FPDF):
    def __init__(self, settings, title):
        super().__init__(orientation="P", unit="mm", format="A4")
        # WinAnsi (cp1252) so € and the en-dash render with the core fonts
        self.core_fonts_encoding = "cp1252"
        self.settings = settings
        self.title_text = title
        self.set_title(title)
        if settings.get("company_name"):
            self.set_author(settings["company_name"])
        self.set_auto_page_break(auto=True, margin=20)

    def header(self):
        s = self.settings
        logo = s.get("logo_path")
        if logo:
            p = Path(logo)
            if p.exists():
                try:
                    h = 18
                    # right-align the logo to the right page margin
                    right_x = self.w - self.r_margin
                    try:
                        lw, lh = float(s.get("logo_w") or 0), float(s.get("logo_h") or 0)
                        disp_w = h * (lw / lh) if lw and lh else 35
                    except (ValueError, ZeroDivisionError):
                        disp_w = 35
                    self.image(str(p), x=right_x - disp_w, y=10, h=h)
                except Exception:
                    pass
        self.set_font("Helvetica", "B", 14)
        self.cell(0, 8, s.get("company_name", ""), ln=1)
        self.set_font("Helvetica", "", 9)
        for line in (s.get("company_address") or "").splitlines():
            self.cell(0, 5, line, ln=1)
        contact = " · ".join(x for x in [s.get("company_email"), s.get("company_phone")] if x)
        if contact:
            self.cell(0, 5, contact, ln=1)
        if s.get("company_vat"):
            self.cell(0, 5, f"USt-IdNr.: {s.get('company_vat')}", ln=1)
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(140, 140, 140)
        self.cell(0, 10, f"Seite {self.page_no()}", align="C")


def _txt(pdf, value):
    # fpdf2 core fonts use WinAnsi (cp1252) — keep € and German chars, degrade rest
    try:
        return str(value).encode("cp1252", "replace").decode("cp1252")
    except Exception:
        return str(value)


def generate_invoice_pdf(out_path, settings, customer, invoice_meta, entries):
    cur = settings.get("currency", "€")
    typ_label = "Leistungsnachweis"
    subtitle = "Zwischenstand" if invoice_meta["type"] == "zwischen" else "Abschluss"
    doc_title = f"{typ_label} {subtitle} – {customer['name']}"
    pdf = InvoicePDF(settings, doc_title)
    pdf.add_page()

    # customer block
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, _txt(pdf, "Für:"), ln=1)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 5, _txt(pdf, customer["name"]), ln=1)
    if customer["customer_no"]:
        pdf.cell(0, 5, _txt(pdf, f"Kundennr.: {customer['customer_no']}"), ln=1)
    if customer["contact"]:
        pdf.cell(0, 5, _txt(pdf, customer["contact"]), ln=1)
    for line in (customer["address"] or "").splitlines():
        pdf.cell(0, 5, _txt(pdf, line), ln=1)
    if customer["vat_id"]:
        pdf.cell(0, 5, _txt(pdf, f"USt-IdNr.: {customer['vat_id']}"), ln=1)
    pdf.ln(4)

    # document meta
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, _txt(pdf, f"{typ_label} – {subtitle}"), ln=1)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 5, _txt(pdf, f"Datum: {invoice_meta['created_at']}"), ln=1)
    if invoice_meta.get("period_from"):
        pdf.cell(0, 5, _txt(pdf, f"Zeitraum: {invoice_meta['period_from']} bis "
                                 f"{invoice_meta['period_to']}"), ln=1)
    pdf.ln(3)

    # table header
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(238, 240, 250)
    widths = [22, 52, 30, 30, 18, 26]
    headers = ["Datum", "Aufgabe", "Projekt", "Zeit", "Satz", "Betrag"]
    for w, h in zip(widths, headers):
        pdf.cell(w, 7, _txt(pdf, h), border=1, fill=True,
                 align="R" if h in ("Satz", "Betrag") else "L")
    pdf.ln()

    pdf.set_font("Helvetica", "", 8)
    subtotal = 0.0
    for e in entries:
        hours = fmt_hours(e["secs"])
        amount = hours * e["rate"]
        subtotal += amount
        task = (e["task"] or "").strip() or "—"
        if len(task) > 42:
            task = task[:41] + "…"
        cells = [
            (widths[0], e["day"], "L"),
            (widths[1], task, "L"),
            (widths[2], e["project_name"][:24], "L"),
            (widths[3], fmt_hm_long(e["secs"]), "L"),
            (widths[4], money(e["rate"], cur), "R"),
            (widths[5], money(amount, cur), "R"),
        ]
        for w, val, al in cells:
            pdf.cell(w, 6, _txt(pdf, str(val)), border="LR", align=al)
        pdf.ln()

    pdf.cell(sum(widths), 0, "", border="T", ln=1)
    pdf.ln(2)

    tax_rate = invoice_meta["tax_rate"]
    tax_amount = subtotal * tax_rate / 100.0
    total = subtotal + tax_amount

    def total_row(label, value, bold=False):
        pdf.set_font("Helvetica", "B" if bold else "", 10 if bold else 9)
        pdf.cell(sum(widths[:-2]), 6, "")
        pdf.cell(widths[-2] + 8, 6, _txt(pdf, label), align="R")
        pdf.cell(widths[-1] - 8, 6, _txt(pdf, money(value, cur)), align="R", ln=1)

    total_row("Zwischensumme", subtotal)
    total_row(f"zzgl. {tax_rate:.0f}% MwSt", tax_amount)
    total_row("Gesamt", total, bold=True)

    pdf.ln(8)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(120, 120, 120)
    pdf.multi_cell(0, 4, _txt(pdf, "Vielen Dank für die gute Zusammenarbeit."))

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out_path))
    return {"subtotal": subtotal, "tax_amount": tax_amount, "total": total}


def generate_open_overview_pdf(out_path, settings, customer, scope_label, groups):
    """Overview of open (unbilled) bookings, grouped by project."""
    cur = settings.get("currency", "€")
    doc_title = f"Offene Buchungen – {customer['name']} – {scope_label}"
    pdf = InvoicePDF(settings, doc_title)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, _txt(pdf, customer["name"]), ln=1)
    pdf.set_font("Helvetica", "", 9)
    if customer["customer_no"]:
        pdf.cell(0, 5, _txt(pdf, f"Kundennr.: {customer['customer_no']}"), ln=1)
    pdf.ln(2)

    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, _txt(pdf, f"Offene Buchungen – {scope_label}"), ln=1)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 5, _txt(pdf, f"Stand: {date.today():%d.%m.%Y}"), ln=1)
    pdf.ln(3)

    widths = [22, 34, 48, 30, 18, 26]
    headers = ["Datum", "Mitarbeiter", "Aufgabe", "Zeit", "Satz", "Betrag"]
    right = ("Satz", "Betrag")
    grand_secs = 0
    grand_amount = 0.0

    for g in groups:
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_fill_color(238, 240, 250)
        pdf.cell(sum(widths), 7, _txt(pdf, g["project"]), border=1, fill=True, ln=1)

        pdf.set_font("Helvetica", "B", 8)
        for w, h in zip(widths, headers):
            pdf.cell(w, 6, _txt(pdf, h), border="B",
                     align="R" if h in right else "L")
        pdf.ln()

        pdf.set_font("Helvetica", "", 8)
        for e in g["entries"]:
            task = (e["task"] or "").strip() or "—"
            if len(task) > 38:
                task = task[:37] + "…"
            cells = [
                (widths[0], e["day"], "L"),
                (widths[1], (e["user_name"] or "")[:20], "L"),
                (widths[2], task, "L"),
                (widths[3], fmt_hm_long(e["secs"]), "L"),
                (widths[4], money(e["rate"], cur), "R"),
                (widths[5], money(e["amount"], cur), "R"),
            ]
            for w, val, al in cells:
                pdf.cell(w, 6, _txt(pdf, str(val)), align=al)
            pdf.ln()

        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(sum(widths[:3]), 6, "", border="T")
        pdf.cell(widths[3], 6, _txt(pdf, fmt_hm_long(g["secs"])), border="T", align="L")
        pdf.cell(widths[4], 6, "", border="T")
        pdf.cell(widths[5], 6, _txt(pdf, money(g["amount"], cur)), border="T", align="R", ln=1)
        pdf.ln(4)
        grand_secs += g["secs"]
        grand_amount += g["amount"]

    if not groups:
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, _txt(pdf, "Keine offenen Buchungen."), ln=1)
    else:
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(sum(widths[:3]), 8, _txt(pdf, "Gesamt offen"), align="R")
        pdf.cell(widths[3], 8, _txt(pdf, fmt_hm_long(grand_secs)), align="L")
        pdf.cell(widths[4], 8, "")
        pdf.cell(widths[5], 8, _txt(pdf, money(grand_amount, cur)), align="R", ln=1)

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out_path))
    return {"secs": grand_secs, "amount": grand_amount}
