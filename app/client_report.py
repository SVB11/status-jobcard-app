"""Locked client-facing wording for progress reports. Workshop names never go on the PDF."""

from io import BytesIO
from datetime import datetime
from pathlib import Path

WEBSITE = "www.statustrucksales.co.za"

STATUS_LINE = {
    "Submitted to Workshop": "Preparation has started",
    "Pending Admin Approval": "Preparation has started",
    "Accepted": "The vehicle is currently being prepared",
    "In Progress": "The vehicle is currently being prepared",
    "Work Completed": "Preparation is complete. Final inspection is under way",
    "PDI in Progress": "Preparation is complete. Final inspection is under way",
    "PDI Completed": "Preparation is complete. Final inspection is under way",
    "Ready for Delivery": "The vehicle is ready. We will confirm handover with you",
    "Delivered / Closed": "This vehicle has been handed over",
}

NEXT_STEP = {
    "Submitted to Workshop": "We will update you as preparation continues.",
    "Pending Admin Approval": "We will update you as preparation continues.",
    "Accepted": "We will confirm with you as soon as the next inspection is complete.",
    "In Progress": "We will confirm with you as soon as the next inspection is complete.",
    "Work Completed": "Final inspection is under way. We will contact you when the vehicle is ready.",
    "PDI in Progress": "Final inspection is under way. We will contact you when the vehicle is ready.",
    "PDI Completed": "Final inspection is under way. We will contact you when the vehicle is ready.",
    "Ready for Delivery": "The vehicle is ready. Please contact me to arrange collection or delivery.",
    "Delivered / Closed": "This vehicle has been handed over.",
}

# First matching group wins for a task. Order matters.
GROUPS = [
    {"key": "barrel", "title": "Tank statutory test", "note": "Statutory tank test",
     "match": ["barrel test"]},
    {"key": "pressure", "title": "Tank pressure test", "note": "Statutory tank test",
     "match": ["pressure test", "slp"]},
    {"key": "cal", "title": "Meter calibration", "note": "Delivery meters checked",
     "match": ["calibration"]},
    {"key": "dekra", "title": "Compliance inspection", "note": "Prepared to required spec",
     "match": ["dekra"]},
    {"key": "fuel_spec", "title": "Fuel-spec preparation", "note": "Prepared for fuel work",
     "match": ["fuel spec"]},
    {"key": "roadworthy", "title": "Roadworthy inspection", "note": "Official inspection before handover",
     "match": ["roadworthy"]},
    {"key": "as_is_rw", "title": "Roadworthy inspection only", "note": "Sold as is, with roadworthy",
     "match": ["as is", "with roadworthy"]},
    {"key": "as_is", "title": "Sold as inspected", "note": "No roadworthy included",
     "match": ["as is"]},
    {"key": "brakes", "title": "Brake test", "note": "Safety test before handover",
     "match": ["brake"]},
    {"key": "wash", "title": "Cleaned for handover", "note": "Washed and presented",
     "match": ["wash"]},
    {"key": "appearance", "title": "Appearance preparation", "note": "Paint and body finishing",
     "match": ["touch-up", "touch up", "polish", "spray rim", "spray / paint", "respray"]},
    {"key": "rims", "title": "Wheel finish", "note": "Rims prepared",
     "match": ["spray rims"]},
    {"key": "refurb", "title": "Body and mechanical preparation", "note": "Workshop preparation before handover",
     "match": ["full refurbishment", "already refurbished"]},
    {"key": "service", "title": "Service", "note": "Service before handover",
     "match": ["service before"]},
    {"key": "electrical", "title": "Electrical check", "note": "Electrical work before handover",
     "match": ["man auto", "auto electrical", "electrical"]},
    {"key": "sails", "title": "Curtain and sail work", "note": "Curtains, belts and fittings",
     "match": ["tautliner", "sail"]},
    {"key": "tipper", "title": "Tipper and hydraulics check", "note": "Bin and hydraulics inspected",
     "match": ["tipper bin", "hydraulics"]},
    {"key": "tarps", "title": "Tarp work", "note": "Tarps checked or fitted",
     "match": ["tarp"]},
    {"key": "cracks", "title": "Bodywork", "note": "Structural repairs as required",
     "match": ["crack repair"]},
    {"key": "supply", "title": "Delivery equipment", "note": "Hoses and couplings supplied",
     "match": ["hose", "coupler", "suzi"]},
    {"key": "pdi", "title": "Final inspection", "note": "Last check before handover",
     "match": ["pdi", "final inspection"]},
]


def _norm(s):
    return (s or "").strip().lower()


def group_for_task(task_name: str):
    name = _norm(task_name)
    if not name:
        return None
    # more specific as-is with roadworthy before generic as-is / roadworthy
    if "as is" in name:
        if "without" in name:
            return next(g for g in GROUPS if g["key"] == "as_is")
        return next(g for g in GROUPS if g["key"] == "as_is_rw")
    for g in GROUPS:
        if g["key"] in ("as_is", "as_is_rw"):
            continue
        if any(m in name for m in g["match"]):
            return g
    return {
        "key": "other_" + name[:24],
        "title": "Additional preparation",
        "note": "Extra work agreed before handover",
        "match": [],
    }


def client_status_for_task(task) -> str:
    st = _norm(getattr(task, "status", None) or "")
    result = _norm(getattr(task, "test_result", None) or "")
    booked = getattr(task, "booked_date", None)
    name = _norm(getattr(task, "task_name", None) or "")
    if "already refurbished" in name and st in ("", "not started", "completed"):
        return "Completed"
    if result in ("fail", "failed"):
        return "Still in preparation"
    if st == "completed":
        return "Completed"
    if st in ("in progress", "in-progress"):
        return "In progress"
    if st == "blocked":
        return "Delayed"
    if booked or st in ("booked", "scheduled"):
        return "Scheduled"
    if st in ("not started", "", "n/a", "na"):
        if booked:
            return "Scheduled"
        return "Not yet started"
    return "In progress"


_RANK = {
    "Completed": 4,
    "In progress": 3,
    "Scheduled": 2,
    "Delayed": 3,
    "Still in preparation": 3,
    "Not yet started": 1,
}


def build_report(job, tasks, parts=None):
    groups = {}
    for t in tasks or []:
        name = getattr(t, "task_name", "") or ""
        if _norm(getattr(t, "status", None)) in ("n/a", "na"):
            continue
        g = group_for_task(name)
        if not g:
            continue
        key = g["key"]
        line_status = client_status_for_task(t)
        cur = groups.get(key)
        if not cur or _RANK.get(line_status, 0) > _RANK.get(cur["status"], 0):
            groups[key] = {
                "title": g["title"],
                "note": g["note"],
                "status": line_status,
            }
        if "roadworthy" in _norm(name) and _norm(getattr(t, "test_result", None)) in ("fail", "failed"):
            groups[key]["note"] = "Re-inspection after corrections"
            groups[key]["status"] = "Still in preparation"

    if parts:
        waiting = [p for p in parts if _norm(getattr(p, "part_progress", None) or getattr(p, "progress", None) or getattr(p, "status", None)) not in ("delivered", "closed", "complete", "completed", "")]
        if waiting:
            groups["parts"] = {
                "title": "Waiting on a part",
                "note": "Preparation continues around it",
                "status": "Delayed",
            }

    # stable display order
    order = [g["key"] for g in GROUPS] + ["parts"]
    items = []
    seen = set()
    for key in order:
        if key in groups and key not in seen:
            items.append(groups[key])
            seen.add(key)
    for key, row in groups.items():
        if key not in seen:
            items.append(row)

    job_status = job.status or ""
    return {
        "client_name": job.client_name or "Client",
        "salesman_name": job.salesman_name or "",
        "vehicle": " ".join(x for x in [job.year, job.vehicle_description] if x).strip(),
        "year": job.year or "",
        "make_model": job.vehicle_description or "",
        "registration": job.registration_number or "",
        "vin": job.vin_number or "",
        "quote": job.quotation_invoice_number or "",
        "stock_number": job.stock_number or "",
        "job_status": job_status,
        "status_line": STATUS_LINE.get(job_status, "The vehicle is currently being prepared"),
        "next_step": NEXT_STEP.get(job_status, "We will update you as preparation continues."),
        "items": items,
        "website": WEBSITE,
        "date": datetime.utcnow().strftime("%d %B %Y"),
    }


def whatsapp_text(report: dict) -> str:
    lines = [
        "Status Truck Sales — vehicle preparation update",
        "",
        f"Dear {report['client_name']},",
        "",
        f"{report['vehicle']}" + (f" · {report['registration']}" if report.get("registration") else ""),
    ]
    if report.get("quote"):
        lines.append(f"Reference: {report['quote']}")
    lines += [
        "",
        f"Current status: {report['status_line']}",
        "",
    ]
    for it in report.get("items") or []:
        extra = f" ({it['note']})" if it.get("note") and it["status"] != "Completed" else ""
        lines.append(f"- {it['title']}: {it['status']}{extra}")
    lines += [
        "",
        f"Next step: {report['next_step']}",
        "",
        report.get("salesman_name") or "Status Truck Sales",
        "Sales · Status Truck Sales",
        WEBSITE,
    ]
    return "\n".join(lines)


def render_pdf(report: dict) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.colors import HexColor, white, black
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader

    buf = BytesIO()
    W, H = A4
    c = canvas.Canvas(buf, pagesize=A4)
    blue = HexColor("#025daa")
    navy = HexColor("#0c2b4a")
    grey = HexColor("#5b6570")
    ok = HexColor("#1f7a3f")
    mid = HexColor("#b45309")
    soft = HexColor("#f4f7fb")

    root = Path(__file__).resolve().parent.parent
    logo = root / "static" / "images" / "status_logo_th.png"
    c.setFillColor(navy)
    c.rect(0, H - 28 * mm, W, 28 * mm, fill=1, stroke=0)
    if logo.exists():
        c.drawImage(ImageReader(str(logo)), 16 * mm, H - 24 * mm, width=52 * mm, height=18 * mm,
                    mask="auto", preserveAspectRatio=True, anchor="w")
    c.setFillColor(white)
    c.setFont("Helvetica", 8)
    c.drawRightString(W - 16 * mm, H - 12 * mm, WEBSITE)
    c.setFont("Helvetica-Bold", 9)
    c.drawRightString(W - 16 * mm, H - 17.5 * mm, "VEHICLE PREPARATION UPDATE")
    c.setFillColor(blue)
    c.rect(0, H - 30 * mm, W, 2 * mm, fill=1, stroke=0)

    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(16 * mm, H - 42 * mm, "Progress report")
    c.setFillColor(grey)
    c.setFont("Helvetica", 9)
    c.drawString(16 * mm, H - 47 * mm, "Prepared for the client.")

    c.setFillColor(soft)
    c.roundRect(16 * mm, H - 78 * mm, W - 32 * mm, 26 * mm, 3 * mm, fill=1, stroke=0)
    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(20 * mm, H - 56 * mm, "TO")
    c.drawString(78 * mm, H - 56 * mm, "VEHICLE")
    c.drawString(148 * mm, H - 56 * mm, "REFERENCE")
    c.setFillColor(black)
    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, H - 62 * mm, (report.get("client_name") or "")[:34])
    c.drawString(78 * mm, H - 62 * mm, (report.get("vehicle") or "")[:32])
    c.drawString(148 * mm, H - 62 * mm, (("Quote " + report["quote"]) if report.get("quote") else "")[:28])
    c.setFillColor(grey)
    c.setFont("Helvetica", 8)
    c.drawString(20 * mm, H - 68 * mm, "Client")
    c.drawString(78 * mm, H - 68 * mm, (report.get("registration") or "")[:22])
    c.drawString(148 * mm, H - 68 * mm, report.get("date") or "")
    if report.get("vin"):
        c.drawString(78 * mm, H - 73.5 * mm, "VIN: " + report["vin"][:22])
    if report.get("stock_number"):
        c.drawString(148 * mm, H - 73.5 * mm, "Internal ref " + report["stock_number"])

    c.setFillColor(HexColor("#e8f3ec"))
    c.roundRect(16 * mm, H - 92 * mm, W - 32 * mm, 10 * mm, 2.5 * mm, fill=1, stroke=0)
    c.setFillColor(ok)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, H - 88.2 * mm, "CURRENT STATUS")
    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(58 * mm, H - 88.2 * mm, (report.get("status_line") or "")[:62])

    c.setFillColor(black)
    c.setFont("Helvetica", 9.5)
    y = H - 104 * mm
    c.drawString(16 * mm, y, f"Dear {report.get('client_name') or 'Client'},")
    y -= 6 * mm
    c.drawString(16 * mm, y, f"Please find a short update on the preparation of your {report.get('vehicle') or 'vehicle'}.")
    y -= 5 * mm
    c.drawString(16 * mm, y, "Only the work that affects handover is shown below.")

    y -= 10 * mm
    c.setFillColor(blue)
    c.rect(16 * mm, y, W - 32 * mm, 8 * mm, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(20 * mm, y + 2.6 * mm, "PREPARATION ITEM")
    c.drawString(118 * mm, y + 2.6 * mm, "STATUS")
    c.drawString(152 * mm, y + 2.6 * mm, "NOTE")

    items = report.get("items") or []
    if not items:
        items = [{"title": "Preparation", "status": "In progress", "note": ""}]
    for i, it in enumerate(items):
        y -= 9 * mm
        if y < 40 * mm:
            break
        if i % 2 == 0:
            c.setFillColor(HexColor("#f7f9fc"))
            c.rect(16 * mm, y - 2 * mm, W - 32 * mm, 9 * mm, fill=1, stroke=0)
        c.setFillColor(navy)
        c.setFont("Helvetica", 9)
        c.drawString(20 * mm, y + 1.2 * mm, (it.get("title") or "")[:40])
        st = it.get("status") or ""
        if st == "Completed":
            c.setFillColor(ok)
        elif st in ("In progress", "Delayed", "Still in preparation"):
            c.setFillColor(mid)
        else:
            c.setFillColor(grey)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(118 * mm, y + 1.2 * mm, st[:22])
        c.setFillColor(grey)
        c.setFont("Helvetica", 8)
        note = it.get("note") or ""
        if st == "Completed":
            note = ""
        c.drawString(152 * mm, y + 1.2 * mm, note[:28])

    y -= 16 * mm
    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(16 * mm, y, "NEXT STEP")
    c.setFillColor(black)
    c.setFont("Helvetica", 9.5)
    c.drawString(16 * mm, y - 6 * mm, (report.get("next_step") or "")[:95])

    y -= 22 * mm
    c.setStrokeColor(HexColor("#d7dde4"))
    c.setLineWidth(0.6)
    c.line(16 * mm, y + 8 * mm, W - 16 * mm, y + 8 * mm)
    c.setFillColor(grey)
    c.setFont("Helvetica", 8)
    c.drawString(16 * mm, y + 2 * mm, "PREPARED BY")
    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(16 * mm, y - 5 * mm, (report.get("salesman_name") or "Status Truck Sales")[:40])
    c.setFillColor(black)
    c.setFont("Helvetica", 9)
    c.drawString(16 * mm, y - 10.5 * mm, "Sales  ·  Status Truck Sales")
    c.setFillColor(blue)
    c.drawString(16 * mm, y - 16 * mm, WEBSITE)

    c.setFillColor(blue)
    c.rect(0, 0, W, 16 * mm, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Helvetica", 8)
    c.drawString(16 * mm, 7 * mm, "Status Truck Sales")
    c.drawCentredString(W / 2, 7 * mm, WEBSITE)
    c.drawRightString(W - 16 * mm, 7 * mm, "Not a tax invoice")
    c.showPage()
    c.save()
    return buf.getvalue()
