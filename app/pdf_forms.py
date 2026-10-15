"""Filed PDF job card and PDI. Logo keeps its real shape."""
import os
from datetime import datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGO = os.path.join(BASE, "static", "images", "status_logo_white_trim.png")
FONT = "/usr/share/fonts/truetype/liberation2/LiberationSerif-Italic.ttf"
if os.path.exists(FONT) and "SignFont" not in pdfmetrics.getRegisteredFontNames():
    pdfmetrics.registerFont(TTFont("SignFont", FONT))

BLUE = colors.HexColor("#025daa")
NAVY = colors.HexColor("#0c1015")
LINE = colors.HexColor("#d0d7e2")
SOFT = colors.HexColor("#f4f7fb")
WHITE = colors.white


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="H", fontName="Helvetica-Bold", fontSize=16, textColor=WHITE, leading=19))
    styles.add(ParagraphStyle(name="Sub", fontName="Helvetica", fontSize=8, textColor=colors.HexColor("#c5d4e8"), leading=11))
    styles.add(ParagraphStyle(name="Sec", fontName="Helvetica-Bold", fontSize=10, textColor=BLUE, leading=13, spaceBefore=8, spaceAfter=4))
    styles.add(ParagraphStyle(name="Cell", fontName="Helvetica", fontSize=8, leading=11, textColor=NAVY))
    styles.add(ParagraphStyle(name="CellB", fontName="Helvetica-Bold", fontSize=8, leading=11, textColor=NAVY))
    styles.add(ParagraphStyle(name="Small", fontName="Helvetica", fontSize=7.5, leading=10, textColor=colors.HexColor("#4b5563")))
    styles.add(ParagraphStyle(name="Sign", fontName="SignFont" if "SignFont" in pdfmetrics.getRegisteredFontNames() else "Helvetica-Oblique", fontSize=13, leading=16, textColor=colors.HexColor("#1e3a5f")))
    styles.add(ParagraphStyle(name="Foot", fontName="Helvetica", fontSize=7.5, textColor=colors.HexColor("#6b7280"), alignment=TA_CENTER))
    return styles


S = None


def P(text, style="Cell"):
    return Paragraph(str(text if text not in (None, "") else "—"), S[style])


def when(value):
    if not value:
        return ""
    if isinstance(value, str):
        return value.replace("T", " ")[:16]
    try:
        return value.strftime("%d %b %Y %H:%M")
    except Exception:
        return str(value)[:16]


def header(title, sub, right_lines):
    bits = []
    if os.path.exists(LOGO):
        # Trimmed wordmark is 5032 x 1206, ratio 4.17. Do not stretch.
        bits.append(Image(LOGO, width=46 * mm, height=11 * mm))
    else:
        bits.append(P("STATUS", "CellB"))
    left = [Paragraph(title, S["H"]), Paragraph(sub, S["Sub"]), Paragraph("Status Truck Sales &nbsp;·&nbsp; www.statustrucksales.co.za", S["Sub"])]
    right = [Paragraph(x, S["Sub"]) for x in right_lines]
    t = Table([[bits[0], left, right]], colWidths=[52 * mm, 92 * mm, 42 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (2, 0), (2, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (0, 0), 6),
        ("RIGHTPADDING", (2, 0), (2, 0), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    bar = Table([[""]], colWidths=[186 * mm])
    bar.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), BLUE), ("TOPPADDING", (0, 0), (-1, -1), 1.4), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.4)]))
    return [t, bar, Spacer(1, 6)]


def info_block(pairs):
    cells = []
    for i in range(0, len(pairs), 2):
        a, b = pairs[i], pairs[i + 1] if i + 1 < len(pairs) else ("", "")
        cells.append([P(a[0], "Small"), P(a[1], "CellB"), P(b[0], "Small"), P(b[1], "CellB")])
    t = Table(cells, colWidths=[28 * mm, 65 * mm, 28 * mm, 65 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), SOFT),
        ("BACKGROUND", (2, 0), (2, -1), SOFT),
        ("BOX", (0, 0), (-1, -1), 0.4, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def section(title, headers, rows, widths):
    data = [[P(h, "CellB") for h in headers]]
    if not rows:
        data.append([P("None")] + [P("")] * (len(headers) - 1))
    for r in rows:
        data.append([P(c) for c in r])
    t = Table(data, colWidths=widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("BOX", (0, 0), (-1, -1), 0.4, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), SOFT))
    t.setStyle(TableStyle(style))
    return [Paragraph(title, S["Sec"]), t]


def sign_block(rows):
    data = []
    for role, name, stamp in rows:
        data.append([P(role, "CellB"), P(name or "Not signed", "Sign" if name else "Small"), P(stamp, "Small")])
    t = Table(data, colWidths=[40 * mm, 80 * mm, 66 * mm])
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.4, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE),
        ("BACKGROUND", (0, 0), (0, -1), SOFT),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def footer(canvas, doc, label):
    canvas.saveState()
    canvas.setStrokeColor(BLUE)
    canvas.setLineWidth(1.5)
    canvas.line(12 * mm, 10 * mm, A4[0] - 12 * mm, 10 * mm)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#6b7280"))
    canvas.drawString(12 * mm, 6 * mm, label)
    canvas.drawRightString(A4[0] - 12 * mm, 6 * mm, f"Page {doc.page}")
    canvas.restoreState()


def vehicle_pairs(job):
    return [
        ("Stock number", job.stock_number), ("Job number", job.job_number),
        ("Make / model", job.vehicle_description), ("Year", job.year),
        ("Type", f"{job.main_type or ''} / {job.sub_type or ''}".strip(" /")), ("VIN", getattr(job, "vin_number", None)),
        ("Registration", getattr(job, "registration_number", None)), ("Location", job.current_location),
        ("Client", job.client_name), ("Salesman", job.salesman_name),
        ("Quote / invoice", getattr(job, "quotation_invoice_number", None)), ("Target date", job.target_delivery_date),
    ]


def noise(text):
    s = (text or "").lower()
    return "update request" in s or "requested an update" in s or "morning location" in s or "ask louis" in s


def build_work_pdf(job, workshop_name, sales_name):
    global S
    S = _styles()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=14 * mm, title=f"{job.stock_number} completed work")
    story = []
    story += header("COMPLETED WORK", f"Job card &nbsp;·&nbsp; {job.stock_number or ''} &nbsp;·&nbsp; {job.job_number or ''}", ["FILE COPY", datetime.utcnow().strftime("%d %b %Y"), job.status or ""])
    story.append(info_block(vehicle_pairs(job)))
    done, open_rows = [], []
    for t in job.tasks or []:
        if (t.task_name or "").lower().startswith("activity:") or noise(t.task_name):
            continue
        note = t.notes or t.description or ""
        if getattr(t, "third_party_provider", None):
            note = (note + " · " + t.third_party_provider).strip(" ·")
        if t.status == "Completed":
            done.append([t.task_name, note, when(t.completed_at)])
        else:
            open_rows.append([t.task_name, t.status or "", note])
    story += section("COMPLETED TASKS", ["Task", "Notes", "Done"], done, [58 * mm, 96 * mm, 32 * mm])
    story += section("STILL OPEN", ["Task", "Status", "Notes"], open_rows, [58 * mm, 36 * mm, 92 * mm])
    parts = [[p.description, getattr(p, "quantity", None) or "1", getattr(p, "price", None) or "", p.order_number or "", getattr(p, "supplier_invoice", None) or "", getattr(p, "part_progress", None) or ""] for p in (getattr(job, "parts", None) or [])]
    story += section("PARTS", ["Part", "Qty", "Price", "Order no.", "Invoice", "Status"], parts, [52 * mm, 16 * mm, 24 * mm, 32 * mm, 30 * mm, 32 * mm])
    supplies = [[s.category, s.item_type, s.quantity or "1", s.status or "", s.notes or ""] for s in (getattr(job, "supplies", None) or [])]
    story += section("HOSES / COUPLERS / SUZI", ["Category", "Type", "Qty", "Status", "Notes"], supplies, [32 * mm, 40 * mm, 16 * mm, 28 * mm, 70 * mm])
    bookings = [[b.service, b.provider, b.booked_date or "", b.notes or ""] for b in (getattr(job, "third_party_bookings", None) or [])]
    story += section("3RD PARTY BOOKINGS", ["Service", "Company", "Date", "Notes"], bookings, [48 * mm, 52 * mm, 32 * mm, 54 * mm])
    story.append(Paragraph("SIGNED IN APP", S["Sec"]))
    story.append(sign_block([
        ("Workshop", workshop_name, "Signed ready &nbsp;·&nbsp; " + when(job.ready_for_delivery_workshop_at) if workshop_name else "Not signed"),
        ("Sales", sales_name, "Signed ready &nbsp;·&nbsp; " + when(job.ready_for_delivery_sales_at) if sales_name else "Not signed"),
    ]))
    story.append(Spacer(1, 6))
    story.append(Paragraph("Status Truck Sales &nbsp;·&nbsp; Boksburg &nbsp;·&nbsp; Internal use only &nbsp;·&nbsp; www.statustrucksales.co.za", S["Foot"]))
    label = f"{job.stock_number or ''}  ·  {job.vehicle_description or ''}  ·  Completed work"
    doc.build(story, onFirstPage=lambda c, d: footer(c, d, label), onLaterPages=lambda c, d: footer(c, d, label))
    buf.seek(0)
    return buf


def build_pdi_pdf(job, items, workshop_name, sales_name):
    global S
    S = _styles()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=14 * mm, title=f"{job.stock_number} PDI")
    story = []
    story += header("PDI CHECKLIST", f"Pre-delivery inspection &nbsp;·&nbsp; {job.stock_number or ''} &nbsp;·&nbsp; {job.job_number or ''}", ["FILE COPY", datetime.utcnow().strftime("%d %b %Y"), "PDI signed" if (workshop_name and sales_name) else job.status or ""])
    story.append(info_block(vehicle_pairs(job)[:10]))
    rows = []
    for item in items:
        rows.append([item.check_item, item.status or "—", item.notes or ""])
    story += section("INSPECTION", ["Item", "Result", "Note"], rows, [90 * mm, 24 * mm, 72 * mm])
    story.append(Paragraph("SIGNED IN APP", S["Sec"]))
    story.append(sign_block([
        ("Workshop", workshop_name, "Signed PDI &nbsp;·&nbsp; " + when(job.pdi_signed_workshop_at) if workshop_name else "Not signed"),
        ("Sales", sales_name, "Signed PDI &nbsp;·&nbsp; " + when(job.pdi_signed_sales_at) if sales_name else "Not signed"),
    ]))
    story.append(Spacer(1, 6))
    story.append(Paragraph("Status Truck Sales &nbsp;·&nbsp; Boksburg &nbsp;·&nbsp; Internal use only &nbsp;·&nbsp; www.statustrucksales.co.za", S["Foot"]))
    label = f"{job.stock_number or ''}  ·  {job.vehicle_description or ''}  ·  PDI"
    doc.build(story, onFirstPage=lambda c, d: footer(c, d, label), onLaterPages=lambda c, d: footer(c, d, label))
    buf.seek(0)
    return buf
