"""Locked client-facing wording for progress reports. Workshop names never go on the PDF."""

from io import BytesIO
from datetime import datetime
from pathlib import Path

WEBSITE = "www.statustrucksales.co.za"

STATUS_LINE = {
    "Submitted to Workshop": "Preparation has started",
    "Pending Admin Approval": "Preparation has started",
    "Accepted": "The vehicle is currently being prepared",
    "Accepted by Workshop": "The vehicle is currently being prepared",
    "In Progress": "The vehicle is currently being prepared",
    "PDI Failed - Returned to Workshop": "The vehicle is currently being prepared",
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
    "Accepted by Workshop": "We will confirm with you as soon as the next inspection is complete.",
    "In Progress": "We will confirm with you as soon as the next inspection is complete.",
    "PDI Failed - Returned to Workshop": "Preparation is continuing. We will update you after the next inspection.",
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
        "key": "other_prep",
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


def _looks_internal(task_name: str) -> bool:
    raw = (task_name or "").strip()
    n = _norm(raw)
    if len(raw) > 42:
        return True
    return any(x in n for x in (
        "workshop", "double check", "already through", "just check",
        "trailer sto", "please", "make sure", "as discussed",
    ))

def _client_title(task_name, group):
    if (group or {}).get("key") == "other_prep" or _looks_internal(task_name):
        return "Additional preparation"
    return group["title"]


def build_report(job, tasks, parts=None):
    groups = {}
    for t in tasks or []:
        name = getattr(t, "task_name", "") or ""
        if _norm(getattr(t, "status", None)) in ("n/a", "na"):
            continue
        if _norm(name).startswith("activity:"):
            continue
        if any(x in _norm(name) for x in ("update request", "requested an update", "morning location")):
            continue
        g = group_for_task(name)
        if not g:
            continue
        if _looks_internal(name):
            g = {
                "key": "other_prep",
                "title": "Additional preparation",
                "note": "Extra work agreed before handover",
                "match": [],
            }
        key = g["key"]
        line_status = client_status_for_task(t)
        title = _client_title(name, g)
        cur = groups.get(key)
        if not cur or _RANK.get(line_status, 0) > _RANK.get(cur["status"], 0):
            groups[key] = {
                "title": title,
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
    order = [g["key"] for g in GROUPS] + ["parts", "other_prep"]
    items = []
    seen = set()
    for key in order:
        if key in groups and key not in seen:
            items.append(groups[key])
            seen.add(key)
    for key, row in groups.items():
        if key not in seen:
            items.append(row)

    if not items:
        items.append({
            "title": "Vehicle preparation",
            "note": "Work logged on this job",
            "status": "In progress" if (job.status or "") not in ("Ready for Delivery", "Delivered / Closed") else "Completed",
        })

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


def _wrap(text, font, size, max_w):
    from reportlab.pdfbase.pdfmetrics import stringWidth
    text = (text or "").strip()
    if not text:
        return [""]
    words = text.split()
    lines, line = [], ""
    for w in words:
        trial = (line + " " + w).strip()
        if stringWidth(trial, font, size) <= max_w:
            line = trial
        else:
            if line:
                lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines or [""]


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
    left = 16 * mm
    right = W - 16 * mm
    width = right - left

    root = Path(__file__).resolve().parent.parent
    logo = root / "static" / "images" / "status_logo_th.png"
    c.setFillColor(navy)
    c.rect(0, H - 28 * mm, W, 28 * mm, fill=1, stroke=0)
    if logo.exists():
        c.drawImage(ImageReader(str(logo)), 16 * mm, H - 24 * mm, width=52 * mm, height=18 * mm,
                    mask="auto", preserveAspectRatio=True, anchor="w")
    c.setFillColor(white)
    c.setFont("Helvetica", 8)
    c.drawRightString(right, H - 12 * mm, WEBSITE)
    c.setFont("Helvetica-Bold", 9)
    c.drawRightString(right, H - 17.5 * mm, "VEHICLE PREPARATION UPDATE")
    c.setFillColor(blue)
    c.rect(0, H - 30 * mm, W, 2 * mm, fill=1, stroke=0)

    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(left, H - 42 * mm, "Progress report")
    c.setFillColor(grey)
    c.setFont("Helvetica", 9)
    c.drawString(left, H - 47 * mm, "Prepared for the client.")

    c.setFillColor(soft)
    c.roundRect(left, H - 80 * mm, width, 28 * mm, 3 * mm, fill=1, stroke=0)
    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(left + 4 * mm, H - 56 * mm, "TO")
    c.drawString(left + 62 * mm, H - 56 * mm, "VEHICLE")
    c.drawString(left + 128 * mm, H - 56 * mm, "REFERENCE")
    c.setFillColor(black)
    c.setFont("Helvetica", 9)
    to_lines = _wrap(report.get("client_name") or "Client", "Helvetica", 9, 54 * mm)
    veh_lines = _wrap(" ".join(x for x in [report.get("vehicle"), report.get("registration")] if x), "Helvetica", 9, 60 * mm)
    ref_lines = _wrap(("Quote " + report["quote"]) if report.get("quote") else "", "Helvetica", 9, 42 * mm)
    c.drawString(left + 4 * mm, H - 62 * mm, to_lines[0])
    c.drawString(left + 62 * mm, H - 62 * mm, veh_lines[0])
    c.drawString(left + 128 * mm, H - 62 * mm, ref_lines[0] if ref_lines[0] else "")
    c.setFillColor(grey)
    c.setFont("Helvetica", 8)
    c.drawString(left + 4 * mm, H - 68 * mm, "Client")
    c.drawString(left + 62 * mm, H - 68 * mm, (report.get("year") or "") + ((" · " + report.get("make_model")) if report.get("make_model") and report.get("year") else ""))
    c.drawString(left + 128 * mm, H - 68 * mm, report.get("date") or "")
    if report.get("vin"):
        c.drawString(left + 62 * mm, H - 73.5 * mm, "VIN: " + report["vin"])
    if report.get("stock_number"):
        c.drawString(left + 128 * mm, H - 73.5 * mm, "Internal ref " + report["stock_number"])

    status = report.get("status_line") or ""
    status_lines = _wrap(status, "Helvetica-Bold", 9, width - 48 * mm)
    box_h = max(12 * mm, 6 * mm + len(status_lines) * 4.2 * mm)
    c.setFillColor(HexColor("#e8f3ec"))
    c.roundRect(left, H - 82 * mm - box_h, width, box_h, 2.5 * mm, fill=1, stroke=0)
    c.setFillColor(ok)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(left + 4 * mm, H - 88 * mm, "STATUS")
    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 9)
    sy = H - 88 * mm
    for i, ln in enumerate(status_lines):
        c.drawString(left + 28 * mm, sy - i * 4.2 * mm, ln)

    y = H - 82 * mm - box_h - 10 * mm
    c.setFillColor(black)
    c.setFont("Helvetica", 9.5)
    dear = _wrap(f"Dear {report.get('client_name') or 'Client'},", "Helvetica", 9.5, width)
    for ln in dear:
        c.drawString(left, y, ln)
        y -= 5 * mm
    intro = _wrap(
        f"Please find a short update on the preparation of your {report.get('vehicle') or 'vehicle'}. Only the work that affects handover is shown below.",
        "Helvetica", 9.5, width
    )
    for ln in intro:
        c.drawString(left, y, ln)
        y -= 4.6 * mm

    y -= 4 * mm
    c.setFillColor(blue)
    c.rect(left, y, width, 8 * mm, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(left + 4 * mm, y + 2.6 * mm, "PREPARATION ITEM")
    c.drawString(left + width - 42 * mm, y + 2.6 * mm, "STATUS")

    items = report.get("items") or [{"title": "Vehicle preparation", "status": "In progress", "note": ""}]
    for i, it in enumerate(items):
        title = it.get("title") or "Preparation"
        note = it.get("note") or ""
        st = it.get("status") or ""
        if st == "Completed":
            note = ""
        title_lines = _wrap(title, "Helvetica", 9, width - 50 * mm)
        note_lines = _wrap(note, "Helvetica", 8, width - 50 * mm) if note else []
        row_h = 6 * mm + (len(title_lines) + len(note_lines)) * 4.2 * mm
        y -= row_h
        if y < 36 * mm:
            c.showPage()
            y = H - 20 * mm
        if i % 2 == 0:
            c.setFillColor(HexColor("#f7f9fc"))
            c.rect(left, y, width, row_h, fill=1, stroke=0)
        c.setFillColor(navy)
        c.setFont("Helvetica", 9)
        ty = y + row_h - 5 * mm
        for ln in title_lines:
            c.drawString(left + 4 * mm, ty, ln)
            ty -= 4.2 * mm
        c.setFillColor(grey)
        c.setFont("Helvetica", 8)
        for ln in note_lines:
            c.drawString(left + 4 * mm, ty, ln)
            ty -= 4.2 * mm
        if st == "Completed":
            c.setFillColor(ok)
        elif st in ("In progress", "Delayed", "Still in preparation"):
            c.setFillColor(mid)
        else:
            c.setFillColor(grey)
        c.setFont("Helvetica-Bold", 9)
        c.drawRightString(right - 3 * mm, y + row_h - 5 * mm, st)

    y -= 10 * mm
    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(left, y, "NEXT STEP")
    y -= 6 * mm
    c.setFillColor(black)
    c.setFont("Helvetica", 9.5)
    for ln in _wrap(report.get("next_step") or "", "Helvetica", 9.5, width):
        if y < 36 * mm:
            c.showPage()
            y = H - 20 * mm
        c.drawString(left, y, ln)
        y -= 4.6 * mm

    y -= 8 * mm
    c.setStrokeColor(HexColor("#d7dde4"))
    c.setLineWidth(0.6)
    c.line(left, y + 6 * mm, right, y + 6 * mm)
    c.setFillColor(grey)
    c.setFont("Helvetica", 8)
    c.drawString(left, y, "PREPARED BY")
    y -= 6 * mm
    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(left, y, report.get("salesman_name") or "Status Truck Sales")
    y -= 5.5 * mm
    c.setFillColor(black)
    c.setFont("Helvetica", 9)
    c.drawString(left, y, "Sales  ·  Status Truck Sales")
    y -= 5 * mm
    c.setFillColor(blue)
    c.drawString(left, y, WEBSITE)

    c.setFillColor(blue)
    c.rect(0, 0, W, 16 * mm, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Helvetica", 8)
    c.drawString(left, 7 * mm, "Status Truck Sales")
    c.drawCentredString(W / 2, 7 * mm, WEBSITE)
    c.drawRightString(right, 7 * mm, "Not a tax invoice")
    c.showPage()
    c.save()
    return buf.getvalue()
