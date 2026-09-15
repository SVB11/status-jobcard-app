from fastapi import FastAPI, Request, Depends, HTTPException, status, Form, Body
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import Optional, List
import os
import json

from .database import engine, get_db, Base, SQLITE_FILE
from . import models, auth
from .seed import seed_database
from .tasks_config import get_tasks_for_vehicle
from .lists_config import LOCATIONS, WORKSHOP_BAYS, ACTIVITY_TYPES, EXTRA_WORK_PRESETS, THIRD_PARTY_SERVICES, BARREL_INTERVALS, providers_for_task
from .migrate import migrate_schema

# Create tables and seed
Base.metadata.create_all(bind=engine)
migrate_schema()
seed_database()

app = FastAPI(title="Status Truck Sales - Job Card System", docs_url=None, redoc_url=None, openapi_url=None)

FAILED_LOGINS = {}
MAX_FAILED = 6
LOCK_MINUTES = 15

@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Cache-Control"] = "no-store"
    return response

def login_blocked(username: str):
    rec = FAILED_LOGINS.get((username or "").lower())
    if not rec:
        return False
    count, when = rec
    if count >= MAX_FAILED and (datetime.utcnow() - when).total_seconds() < LOCK_MINUTES * 60:
        return True
    if (datetime.utcnow() - when).total_seconds() >= LOCK_MINUTES * 60:
        FAILED_LOGINS.pop((username or "").lower(), None)
    return False

def record_failed_login(username: str):
    key = (username or "").lower()
    count, _ = FAILED_LOGINS.get(key, (0, datetime.utcnow()))
    FAILED_LOGINS[key] = (count + 1, datetime.utcnow())

def clear_failed_login(username: str):
    FAILED_LOGINS.pop((username or "").lower(), None)

def require_admin(user: models.User):
    if user.role not in ("admin", "accounts"):
        raise HTTPException(status_code=403, detail="Admin access only")
    return user

# Absolute paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

from jinja2 import Environment, FileSystemLoader, select_autoescape

jinja_env = Environment(
    loader=FileSystemLoader(os.path.join(BASE_DIR, "templates")),
    autoescape=select_autoescape(["html", "xml"])
)

def render_template(name: str, **context):
    template = jinja_env.get_template(name)
    return HTMLResponse(template.render(**context))

# ---------- HELPERS ----------

def generate_job_number(db: Session) -> str:
    """Generate next job number in format JC-2026-0001"""
    year = datetime.now().year
    prefix = f"JC-{year}-"
    last = db.query(models.JobCard).filter(
        models.JobCard.job_number.like(f"{prefix}%")
    ).order_by(models.JobCard.id.desc()).first()

    if last and last.job_number:
        try:
            num = int(last.job_number.split("-")[-1]) + 1
        except:
            num = 1
    else:
        num = 1
    return f"{prefix}{num:04d}"

def log_audit(db: Session, user_id: int, action: str, job_card_id: int = None, details: str = None):
    entry = models.AuditLog(
        user_id=user_id,
        job_card_id=job_card_id,
        action=action,
        details=details
    )
    db.add(entry)
    db.commit()

def assert_editable(db: Session, job, user_id):
    if not job or job.status != "Delivered / Closed":
        return
    u = db.query(models.User).filter(models.User.id == user_id).first() if user_id else None
    if not u or u.role not in ("admin", "accounts"):
        raise HTTPException(status_code=400, detail="Job is delivered and locked. Only Admin can edit.")

def user_name(db: Session, user_id):
    if not user_id:
        return None
    u = db.query(models.User).filter(models.User.id == user_id).first()
    return u.full_name if u else None

def parts_missing_order_numbers(db: Session, job_id: int):
    parts = db.query(models.PartItem).filter(models.PartItem.job_card_id == job_id).all()
    return [p for p in parts if not (p.order_number or "").strip()]

# ---------- AUTH ROUTES ----------

@app.post("/token")
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    username = form_data.username
    if login_blocked(username):
        raise HTTPException(status_code=429, detail="Too many failed logins. Try again in 15 minutes.")
    user = auth.authenticate_user(db, username, form_data.password)
    if not user:
        record_failed_login(username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    clear_failed_login(username)
    access_token_expires = timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = auth.create_access_token(
        data={"sub": user.username, "role": user.role, "full_name": user.full_name},
        expires_delta=access_token_expires
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": user.role,
        "full_name": user.full_name,
        "user_id": user.id,
        "must_change_password": bool(getattr(user, "must_change_password", False))
    }

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return render_template("login.html", request=request)

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return RedirectResponse(url="/login")

# ---------- DASHBOARD ----------

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    return render_template("dashboard.html", request=request, page_title="Dashboard")

# ---------- CREATE JOB CARD ----------

@app.get("/jobs/create", response_class=HTMLResponse)
async def create_job_page(request: Request):
    return render_template("create_job.html", request=request, page_title="Create Job Card")

@app.get("/api/tasks-for-type")
async def api_tasks_for_type(main_type: str, year: str = None):
    """Return the standard tasks for a vehicle type (used by frontend)."""
    tasks = get_tasks_for_vehicle(main_type, year)
    return {"tasks": tasks}

@app.post("/api/jobs/create")
async def api_create_job(
    request: Request,
    db: Session = Depends(get_db)
):
    """Create a new Job Card with selected tasks."""
    try:
        body = await request.json()
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Required fields
    required = ["stock_number", "vehicle_description", "year", "main_type", "sub_type",
                "client_name", "salesman_name", "priority", "target_delivery_date",
                "vin_number", "registration_number", "quotation_invoice_number"]
    for field in required:
        if not body.get(field):
            raise HTTPException(status_code=400, detail=f"Missing required field: {field}")

    # Get current user from token if possible (simplified for now)
    # In production we would decode the JWT properly here
    created_by_id = body.get("user_id")  # passed from frontend for now

    job_number = generate_job_number(db)

    job = models.JobCard(
        job_number=job_number,
        stock_number=body["stock_number"].strip().upper(),
        vehicle_description=body["vehicle_description"].strip(),
        year=str(body["year"]).strip(),
        main_type=body["main_type"],
        sub_type=body["sub_type"].strip(),
        client_name=body["client_name"].strip(),
        salesman_name=body["salesman_name"],
        created_by=created_by_id,
        priority=body.get("priority", "Normal"),
        target_delivery_date=body.get("target_delivery_date"),
        current_location=body.get("current_location") or "Yard",
        internal_notes=body.get("internal_notes") or None,
        quotation_invoice_number=body.get("quotation_invoice_number") or None,
        other_instructions=body.get("other_instructions") or None,
        vin_number=(body.get("vin_number") or "").strip() or None,
        registration_number=(body.get("registration_number") or "").strip().upper() or None,
        third_party_place=(body.get("third_party_place") or "").strip() or None,
        third_party_date=body.get("third_party_date") or None,
        parts_to_order=(body.get("parts_to_order") or "").strip() or None,
        status="Submitted to Workshop"
    )
    db.add(job)
    db.flush()  # get job.id

    # Add selected tasks
    selected_tasks = body.get("selected_tasks", [])
    for t in selected_tasks:
        task = models.JobTask(
            job_card_id=job.id,
            task_name=t.get("task_name"),
            description=t.get("description"),
            is_custom=t.get("is_custom", False),
            status="Not Started"
        )
        db.add(task)

    other_text = (body.get("other_instructions") or "").strip()
    if other_text:
        db.add(models.JobTask(
            job_card_id=job.id,
            task_name="Other: " + other_text[:80],
            description=other_text,
            is_custom=True,
            needs_approval=True,
            status="Not Started"
        ))

    # Free-text other instructions already stored on job

    db.commit()
    db.refresh(job)

    # Audit
    if created_by_id:
        log_audit(db, created_by_id, "Created Job Card", job.id,
                  f"Job {job_number} for {job.stock_number} – {job.vehicle_description}")

    return {
        "success": True,
        "job_number": job.job_number,
        "job_id": job.id,
        "message": f"Job Card {job.job_number} submitted to Workshop successfully."
    }

# ---------- LIST JOBS (basic) ----------

@app.get("/api/jobs")
async def api_list_jobs(status: str = None, salesman: str = None, created_by: int = None, db: Session = Depends(get_db)):
    query = db.query(models.JobCard).order_by(models.JobCard.created_at.desc())
    if status:
        query = query.filter(models.JobCard.status == status)
    if salesman:
        query = query.filter(models.JobCard.salesman_name == salesman)
    if created_by:
        query = query.filter(models.JobCard.created_by == created_by)
    jobs = query.limit(100).all()
    result = []
    for j in jobs:
        result.append({
            "id": j.id,
            "job_number": j.job_number,
            "stock_number": j.stock_number,
            "vehicle_description": j.vehicle_description,
            "main_type": j.main_type,
            "client_name": j.client_name,
            "salesman_name": j.salesman_name,
            "priority": j.priority,
            "target_delivery_date": j.target_delivery_date,
            "status": j.status,
            "current_location": j.current_location,
            "year": j.year,
            "created_by": j.created_by,
            "created_at": j.created_at.isoformat() if j.created_at else None
        })
    return {"jobs": result}

@app.get("/health")
async def health():
    return {"status": "ok", "app": "Status Truck Sales Job Card System", "version": "0.2"}

# ---------- JOB LIST PAGE ----------

@app.get("/jobs", response_class=HTMLResponse)
async def jobs_page(request: Request):
    return render_template("jobs.html", request=request, page_title="Job Cards")

# ---------- ACCEPT JOB ----------

@app.post("/api/jobs/{job_id}/accept")
async def api_accept_job(job_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        body = await request.json()
    except:
        body = {}

    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != "Submitted to Workshop":
        raise HTTPException(status_code=400, detail=f"Job is already in status: {job.status}")

    user_id = body.get("user_id")
    job.status = "Accepted by Workshop"
    job.accepted_at = datetime.utcnow()
    job.accepted_by = user_id
    acceptor = user_name(db, user_id) or body.get("full_name") or "Workshop"
    db.add(models.JobUpdate(
        job_card_id=job.id,
        category="progress",
        description=f"Job accepted by {acceptor}",
        created_by_name=acceptor,
        created_by=user_id
    ))
    db.commit()

    if user_id:
        log_audit(db, user_id, "Accepted Job Card", job.id, f"Job {job.job_number} accepted by Workshop")

    # TODO: create notification for the salesman

    return {"success": True, "message": f"Job {job.job_number} accepted", "status": job.status}

# ---------- JOB DETAIL ----------

@app.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail_page(request: Request, job_id: int):
    return render_template("job_detail.html", request=request, job_id=job_id, page_title="Job Detail")

@app.get("/api/jobs/{job_id}")
async def api_get_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    tasks = []
    for t in job.tasks:
        tasks.append({
            "id": t.id,
            "task_name": t.task_name,
            "description": t.description,
            "status": t.status,
            "notes": t.notes,
            "is_custom": t.is_custom,
            "needs_approval": bool(getattr(t, "needs_approval", False)),
            "approved_by_name": getattr(t, "approved_by_name", None),
            "last_updated_by_name": getattr(t, "last_updated_by_name", None),
            "task_location": getattr(t, "task_location", None),
            "third_party_provider": getattr(t, "third_party_provider", None),
            "booked_date": getattr(t, "booked_date", None),
            "test_result": getattr(t, "test_result", None),
            "fail_list": getattr(t, "fail_list", None),
            "providers": providers_for_task_db(db, t.task_name),
            "completed_at": t.completed_at.isoformat() if t.completed_at else None
        })

    updates = []
    for u in sorted(job.updates, key=lambda x: x.created_at or datetime.min, reverse=True):
        updates.append({
            "id": u.id,
            "category": u.category,
            "description": u.description,
            "notes": u.notes,
            "created_by_name": u.created_by_name,
            "created_at": u.created_at.isoformat() if u.created_at else None
        })

    part_items = []
    for p in getattr(job, "parts", []) or []:
        part_items.append({
            "id": p.id,
            "description": p.description,
            "order_number": p.order_number,
            "quantity": getattr(p, "quantity", None) or "1",
            "price": getattr(p, "price", None),
            "supplier_invoice": getattr(p, "supplier_invoice", None),
            "part_progress": getattr(p, "part_progress", None) or "To be ordered",
            "ordered_date": getattr(p, "ordered_date", None),
            "follow_up": bool(getattr(p, "follow_up", False)),
            "follow_up_note": getattr(p, "follow_up_note", None),
            "created_by_name": p.created_by_name,
            "order_number_by": getattr(p, "order_number_by", None),
            "created_at": p.created_at.isoformat() if p.created_at else None
        })

    bookings = []
    for b in getattr(job, "third_party_bookings", []) or []:
        bookings.append({
            "id": b.id,
            "service": b.service,
            "provider": b.provider,
            "booked_date": b.booked_date,
            "notes": b.notes,
            "created_by_name": b.created_by_name,
            "created_at": b.created_at.isoformat() if b.created_at else None
        })

    workshop_hours = None
    if job.workshop_entered_at:
        delta = datetime.utcnow() - job.workshop_entered_at.replace(tzinfo=None)
        workshop_hours = round(delta.total_seconds() / 3600, 1)

    return {
        "id": job.id,
        "job_number": job.job_number,
        "stock_number": job.stock_number,
        "vehicle_description": job.vehicle_description,
        "year": job.year,
        "main_type": job.main_type,
        "sub_type": job.sub_type,
        "vin_number": getattr(job, "vin_number", None),
        "chassis_number": getattr(job, "chassis_number", None),
        "registration_number": getattr(job, "registration_number", None),
        "quotation_invoice_number": getattr(job, "quotation_invoice_number", None),
        "client_name": job.client_name,
        "salesman_name": job.salesman_name,
        "priority": job.priority,
        "target_delivery_date": job.target_delivery_date,
        "current_location": job.current_location,
        "internal_notes": job.internal_notes,
        "other_instructions": job.other_instructions,
        "third_party_place": getattr(job, "third_party_place", None),
        "third_party_date": getattr(job, "third_party_date", None),
        "parts_to_order": getattr(job, "parts_to_order", None),
        "workshop_entered_at": job.workshop_entered_at.isoformat() if getattr(job, "workshop_entered_at", None) else None,
        "workshop_hours": workshop_hours,
        "current_activity": getattr(job, "current_activity", None),
        "current_activity_notes": getattr(job, "current_activity_notes", None),
        "current_activity_at": job.current_activity_at.isoformat() if getattr(job, "current_activity_at", None) else None,
        "current_activity_by": getattr(job, "current_activity_by", None),
        "pdi_signed_workshop": job.pdi_signed_workshop,
        "pdi_signed_sales": job.pdi_signed_sales,
        "pdi_signed_workshop_by_name": user_name(db, job.pdi_signed_workshop_by),
        "pdi_signed_sales_by_name": user_name(db, job.pdi_signed_sales_by),
        "pdi_signed_workshop_at": job.pdi_signed_workshop_at.isoformat() if job.pdi_signed_workshop_at else None,
        "pdi_signed_sales_at": job.pdi_signed_sales_at.isoformat() if job.pdi_signed_sales_at else None,
        "status": job.status,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "created_by": job.created_by,
        "created_by_name": user_name(db, job.created_by),
        "accepted_at": job.accepted_at.isoformat() if job.accepted_at else None,
        "accepted_by_name": user_name(db, job.accepted_by),
        "tasks": tasks,
        "updates": updates,
        "third_party_bookings": bookings,
        "parts": part_items,
        "parts_missing_order": any(not (p.get("order_number") or "").strip() for p in part_items)
    }

@app.post("/api/jobs/{job_id}/vehicle")
async def api_update_vehicle(job_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        body = await request.json()
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    user_id = body.get("user_id")
    u = db.query(models.User).filter(models.User.id == user_id).first() if user_id else None
    is_admin = u and u.role in ("admin", "accounts")
    is_creator = u and job.created_by and int(job.created_by) == int(u.id)
    if not (is_admin or is_creator):
        raise HTTPException(status_code=403, detail="Only the person who created this job card or Admin can correct vehicle details")
    if job.status == "Delivered / Closed" and not is_admin:
        raise HTTPException(status_code=400, detail="Job is delivered and locked")
    stock = (body.get("stock_number") or "").strip().upper()
    desc = (body.get("vehicle_description") or "").strip()
    year = (body.get("year") or "").strip()
    if not stock or not desc or not year:
        raise HTTPException(status_code=400, detail="WS number, description and year are required")
    old = f"{job.stock_number} {job.vehicle_description} {job.year}"
    job.stock_number = stock
    job.vehicle_description = desc
    job.year = year
    if "main_type" in body and body.get("main_type"):
        job.main_type = body.get("main_type")
    if "sub_type" in body and body.get("sub_type"):
        job.sub_type = body.get("sub_type")
    if "vin_number" in body:
        job.vin_number = (body.get("vin_number") or "").strip() or None
    if "registration_number" in body:
        job.registration_number = (body.get("registration_number") or "").strip() or None
    changer = body.get("full_name") or (u.full_name if u else "Staff")
    db.add(models.JobUpdate(
        job_card_id=job.id,
        category="progress",
        description=f"Vehicle details corrected: {old} → {job.stock_number} {job.vehicle_description} {job.year}",
        created_by_name=changer,
        created_by=user_id
    ))
    if user_id:
        log_audit(db, user_id, "Corrected vehicle details", job.id, f"{old} → {job.stock_number}")
    db.commit()
    return {"success": True}

# ---------- TASK UPDATES ----------

@app.post("/api/jobs/{job_id}/tasks/{task_id}/update")
async def api_update_task(job_id: int, task_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        body = await request.json()
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    assert_editable(db, job, body.get("user_id"))

    task = db.query(models.JobTask).filter(
        models.JobTask.id == task_id,
        models.JobTask.job_card_id == job_id
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    user_id = body.get("user_id")
    new_status = body.get("status")
    notes = body.get("notes")
    if "task_location" in body:
        task.task_location = body.get("task_location") or None
    if "third_party_provider" in body:
        task.third_party_provider = body.get("third_party_provider") or None
        if task.third_party_provider:
            task.task_location = "3rd Party: " + task.third_party_provider
    if "booked_date" in body:
        task.booked_date = body.get("booked_date") or None
    if "test_result" in body:
        task.test_result = body.get("test_result") or None
        if task.test_result == "Fail":
            new_status = "Failed test - back to workshop"
            if not body.get("task_location"):
                task.task_location = "Yard"
        elif task.test_result == "Pass":
            new_status = "Completed"
    if "fail_list" in body:
        task.fail_list = body.get("fail_list") or None

    allowed_statuses = ["Not Started", "In Progress", "Completed", "Blocked", "Failed test - back to workshop"]
    if new_status and new_status not in allowed_statuses:
        raise HTTPException(status_code=400, detail="Invalid status")

    old_status = task.status

    if new_status:
        task.status = new_status
        if new_status == "Completed":
            task.completed_at = datetime.utcnow()
            task.completed_by = user_id
        elif new_status != "Completed":
            task.completed_at = None
            task.completed_by = None

    if notes is not None:
        task.notes = notes

    changer = body.get("full_name") or user_name(db, user_id) or "Staff"
    task.last_updated_by_name = changer
    change_bits = []
    if new_status:
        change_bits.append(f"status {old_status} → {new_status}")
    if "task_location" in body:
        change_bits.append(f"location {task.task_location or '—'}")
    if "third_party_provider" in body:
        change_bits.append(f"3rd party {task.third_party_provider or '—'}")
    if notes is not None:
        change_bits.append("note updated")
    if change_bits:
        db.add(models.JobUpdate(
            job_card_id=job.id,
            category="progress",
            description=f"{task.task_name}: " + "; ".join(change_bits),
            created_by_name=changer,
            created_by=user_id
        ))

    # If job was only Accepted, move to In Progress when first task is worked on
    if job.status == "Accepted by Workshop" and new_status in ("In Progress", "Completed", "Blocked"):
        job.status = "In Progress"

    db.commit()

    # Audit
    if user_id:
        log_audit(db, user_id, "Updated Task", job.id,
                  f"Task '{task.task_name}' → {new_status or old_status}" + (f" | Notes: {notes}" if notes else ""))

    # Check if all tasks are completed → move job to Work Completed
    all_tasks = db.query(models.JobTask).filter(models.JobTask.job_card_id == job_id).all()
    if all_tasks and all(t.status == "Completed" for t in all_tasks):
        job.status = "Work Completed"
        job.work_completed_at = datetime.utcnow()
        db.commit()
        if user_id:
            log_audit(db, user_id, "Work Completed", job.id, f"All tasks completed on {job.job_number}")

    # Blocked notification placeholder
    if new_status == "Blocked" and user_id:
        log_audit(db, user_id, "Task Blocked", job.id,
                  f"Task '{task.task_name}' marked Blocked – Sales should be notified")

    db.refresh(task)
    return {
        "success": True,
        "task": {
            "id": task.id,
            "task_name": task.task_name,
            "status": task.status,
            "notes": task.notes,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None
        },
        "job_status": job.status
    }

@app.post("/api/jobs/{job_id}/tasks/add")
async def api_add_task(job_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        body = await request.json()
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    assert_editable(db, job, body.get("user_id"))

    task_name = (body.get("task_name") or "").strip()
    if not task_name:
        raise HTTPException(status_code=400, detail="Task name is required")

    user_id = body.get("user_id")
    task = models.JobTask(
        job_card_id=job_id,
        task_name=task_name,
        description=body.get("description") or None,
        is_custom=True,
        status="Not Started",
        notes=body.get("notes") or None,
        task_location=body.get("task_location") or None,
        needs_approval=not body.get("is_admin", False),
        last_updated_by_name=body.get("full_name")
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    if user_id:
        log_audit(db, user_id, "Added Custom Task", job.id, f"Added task: {task_name}")

    return {
        "success": True,
        "task": {
            "id": task.id,
            "task_name": task.task_name,
            "description": task.description,
            "status": task.status,
            "notes": task.notes,
            "is_custom": True
        }
    }

# ---------- ADMIN: USER MANAGEMENT ----------

@app.get("/admin/users", response_class=HTMLResponse)
async def admin_users_page(request: Request):
    return render_template("admin_users.html", request=request, page_title="User Management")

@app.get("/admin/third-parties", response_class=HTMLResponse)
async def admin_third_parties_page(request: Request):
    return render_template("admin_third_parties.html", request=request, page_title="3rd Parties")

@app.get("/api/admin/third-parties")
async def api_admin_list_third_parties(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_admin(current_user)
    rows = db.query(models.ThirdPartyCompany).order_by(models.ThirdPartyCompany.category, models.ThirdPartyCompany.name).all()
    return {"companies": [{"id": r.id, "category": r.category, "name": r.name, "is_active": r.is_active} for r in rows]}

@app.post("/api/admin/third-parties")
async def api_admin_add_third_party(request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_admin(current_user)
    body = await request.json()
    name = (body.get("name") or "").strip()
    category = (body.get("category") or "").strip()
    if not name or not category:
        raise HTTPException(status_code=400, detail="Category and company name are required")
    db.add(models.ThirdPartyCompany(category=category, name=name, is_active=True))
    db.commit()
    return {"success": True}

@app.post("/api/admin/third-parties/{item_id}/toggle")
async def api_admin_toggle_third_party(item_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_admin(current_user)
    row = db.query(models.ThirdPartyCompany).filter(models.ThirdPartyCompany.id == item_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    row.is_active = not row.is_active
    db.commit()
    return {"success": True, "is_active": row.is_active}

@app.get("/api/admin/pending-extras")
async def api_admin_pending_extras(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_admin(current_user)
    tasks = db.query(models.JobTask).filter(models.JobTask.needs_approval == True).order_by(models.JobTask.id.desc()).all()
    out = []
    for t in tasks:
        job = db.query(models.JobCard).filter(models.JobCard.id == t.job_card_id).first()
        if not job:
            continue
        out.append({
            "task_id": t.id,
            "job_id": job.id,
            "job_number": job.job_number,
            "stock_number": job.stock_number,
            "vehicle_description": job.vehicle_description,
            "year": job.year,
            "task_name": t.task_name,
            "description": t.description,
            "last_updated_by_name": t.last_updated_by_name
        })
    return {"tasks": out}

@app.get("/api/admin/users")
async def api_list_users(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_admin(current_user)
    users = db.query(models.User).order_by(models.User.role, models.User.full_name).all()
    return {
        "users": [
            {
                "id": u.id,
                "username": u.username,
                "full_name": u.full_name,
                "role": u.role,
                "is_active": u.is_active,
                "password": getattr(u, "password_plain", None) or "(changed — not stored)",
                "created_at": u.created_at.isoformat() if u.created_at else None
            } for u in users
        ]
    }

@app.post("/api/admin/users")
async def api_create_user(request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_admin(current_user)
    try:
        body = await request.json()
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    username = (body.get("username") or "").strip().lower()
    full_name = (body.get("full_name") or "").strip()
    password = body.get("password") or ""
    role = body.get("role") or "sales"

    if not username or not full_name or not password:
        raise HTTPException(status_code=400, detail="Username, full name and password are required")

    if role not in ("sales", "workshop", "accounts", "admin"):
        raise HTTPException(status_code=400, detail="Invalid role")

    existing = db.query(models.User).filter(models.User.username == username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")

    user = models.User(
        username=username,
        full_name=full_name,
        hashed_password=auth.get_password_hash(password),
        password_plain=password,
        must_change_password=True,
        role=role,
        is_active=True
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return {
        "success": True,
        "user": {
            "id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "role": user.role
        }
    }

@app.post("/api/admin/users/{user_id}/toggle")
async def api_toggle_user(user_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_admin(current_user)
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = not user.is_active
    db.commit()
    return {"success": True, "is_active": user.is_active}

@app.post("/api/admin/users/{user_id}/reset-password")
async def api_reset_password(user_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_admin(current_user)
    try:
        body = await request.json()
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    new_password = body.get("password") or ""
    if len(new_password) < 4:
        raise HTTPException(status_code=400, detail="Password too short")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.hashed_password = auth.get_password_hash(new_password)
    user.password_plain = new_password
    user.must_change_password = True
    db.commit()
    return {"success": True}

@app.post("/api/me/password")
async def api_change_own_password(request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    body = await request.json()
    user_id = current_user.id
    current = body.get("current_password") or ""
    new_password = body.get("new_password") or ""
    if len(new_password) < 4:
        raise HTTPException(status_code=400, detail="New password too short")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not auth.verify_password(current, user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is wrong")
    user.hashed_password = auth.get_password_hash(new_password)
    user.password_plain = new_password
    user.must_change_password = False
    db.commit()
    return {"success": True}

# ---------- READY FOR DELIVERY & CLOSE ----------

@app.post("/api/jobs/{job_id}/ready")
async def api_mark_ready(job_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        body = await request.json()
    except:
        body = {}

    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status not in ("PDI Completed", "Work Completed", "Ready for Delivery"):
        # Allow from Work Completed for now (PDI can be added later)
        if job.status != "Work Completed":
            raise HTTPException(status_code=400, detail=f"Cannot mark ready from status: {job.status}")

    user_id = body.get("user_id")
    party = body.get("party")  # "sales" or "workshop"

    missing = parts_missing_order_numbers(db, job_id)
    if missing and party == "workshop":
        raise HTTPException(
            status_code=400,
            detail="Cannot close / mark ready. Add Chantelle order numbers for: " + ", ".join(p.description for p in missing)
        )

    if party == "sales":
        job.ready_sales = True
        job.ready_for_delivery_sales_at = datetime.utcnow()
    elif party == "workshop":
        job.ready_workshop = True
        job.ready_for_delivery_workshop_at = datetime.utcnow()
    else:
        raise HTTPException(status_code=400, detail="party must be 'sales' or 'workshop'")

    if job.ready_sales and job.ready_workshop:
        job.status = "Ready for Delivery"

    db.commit()

    if user_id:
        log_audit(db, user_id, "Marked Ready for Delivery", job.id, f"Marked by {party}")

    return {
        "success": True,
        "ready_sales": job.ready_sales,
        "ready_workshop": job.ready_workshop,
        "status": job.status
    }

@app.post("/api/jobs/{job_id}/close")
async def api_close_job(job_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        body = await request.json()
    except:
        body = {}

    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != "Ready for Delivery":
        raise HTTPException(status_code=400, detail="Job must be Ready for Delivery before closing")
    missing = parts_missing_order_numbers(db, job_id)
    if missing:
        raise HTTPException(
            status_code=400,
            detail="Cannot close job. Parts without order numbers: " + ", ".join(p.description for p in missing) + ". Order number to be created by Chantelle."
        )

    user_id = body.get("user_id")
    job.status = "Delivered / Closed"
    job.delivered_at = datetime.utcnow()
    job.delivered_by = user_id
    db.commit()

    if user_id:
        log_audit(db, user_id, "Closed Job", job.id, f"Job {job.job_number} delivered and closed")

    return {"success": True, "status": job.status}

# ---------- PDI DIGITAL FORMS ----------

from .pdi_config import get_pdi_for_type

@app.get("/jobs/{job_id}/pdi", response_class=HTMLResponse)
async def pdi_page(request: Request, job_id: int):
    return render_template("pdi.html", request=request, job_id=job_id, page_title="PDI Checklist")

@app.get("/api/jobs/{job_id}/pdi")
async def api_get_pdi(job_id: int, db: Session = Depends(get_db)):
    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Load existing PDI items or generate from template
    existing = db.query(models.PDIItem).filter(models.PDIItem.job_card_id == job_id).all()
    if not existing:
        # Generate from template
        template = get_pdi_for_type(job.main_type)
        for section in template:
            for item in section["items"]:
                pdi = models.PDIItem(
                    job_card_id=job_id,
                    section=section["section"],
                    item_number=item["num"],
                    check_item=item["item"],
                    acceptance_criteria=item.get("criteria"),
                    status=None,
                    notes=None
                )
                db.add(pdi)
        db.commit()
        existing = db.query(models.PDIItem).filter(models.PDIItem.job_card_id == job_id).order_by(models.PDIItem.item_number).all()

    items = []
    for p in existing:
        items.append({
            "id": p.id,
            "section": p.section,
            "item_number": p.item_number,
            "check_item": p.check_item,
            "acceptance_criteria": p.acceptance_criteria,
            "status": p.status,
            "notes": p.notes,
            "initials": p.initials
        })

    return {
        "job": {
            "id": job.id,
            "job_number": job.job_number,
            "stock_number": job.stock_number,
            "vehicle_description": job.vehicle_description,
            "year": job.year,
            "main_type": job.main_type,
            "sub_type": job.sub_type,
            "client_name": job.client_name,
            "salesman_name": job.salesman_name,
            "status": job.status,
            "pdi_signed_workshop": job.pdi_signed_workshop,
            "pdi_signed_sales": job.pdi_signed_sales,
            "pdi_signed_workshop_at": job.pdi_signed_workshop_at.isoformat() if job.pdi_signed_workshop_at else None,
            "pdi_signed_sales_at": job.pdi_signed_sales_at.isoformat() if job.pdi_signed_sales_at else None,
            "pdi_signed_workshop_by_name": user_name(db, job.pdi_signed_workshop_by),
            "pdi_signed_sales_by_name": user_name(db, job.pdi_signed_sales_by)
        },
        "items": items
    }

@app.post("/api/jobs/{job_id}/pdi/items/{item_id}")
async def api_update_pdi_item(job_id: int, item_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        body = await request.json()
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    job_lock = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    assert_editable(db, job_lock, body.get("user_id"))
    if job_lock and job_lock.pdi_signed_workshop and job_lock.pdi_signed_sales:
        raise HTTPException(status_code=400, detail="PDI is locked after dual sign-off")

    item = db.query(models.PDIItem).filter(
        models.PDIItem.id == item_id,
        models.PDIItem.job_card_id == job_id
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="PDI item not found")

    if "notes" in body:
        item.notes = body["notes"]
    if "initials" in body:
        item.initials = body["initials"]

    if "status" in body:
        if body["status"] not in ("Pass", "Fail", "N/A", None, ""):
            raise HTTPException(status_code=400, detail="Status must be Pass, Fail or N/A")
        item.status = body["status"] if body["status"] else None
        if item.status == "Fail":
            note = (item.notes or body.get("notes") or "").strip()
            if not note:
                raise HTTPException(status_code=400, detail="A fail note is required: describe what failed")
            item.notes = note
            inspector = body.get("full_name") or "Inspector"
            item.initials = inspector
            job = job_lock
            job.status = "PDI Failed - Returned to Workshop"
            job.pdi_signed_workshop = False
            job.pdi_signed_sales = False
            job.ready_sales = False
            job.ready_workshop = False
            msg = f"PDI FAIL on {job.stock_number}: {item.check_item} — {note} (by {inspector})"
            db.add(models.JobTask(
                job_card_id=job.id,
                task_name="PDI Fail: " + (item.check_item or "Item")[:80],
                description=note + " (inspection by " + inspector + ")",
                is_custom=True,
                needs_approval=False,
                status="Not Started",
                notes=note,
                last_updated_by_name=inspector
            ))
            db.add(models.JobUpdate(
                job_card_id=job.id,
                category="pdi",
                description=msg,
                notes=note,
                created_by_name=inspector,
                created_by=body.get("user_id")
            ))
            notify_role(db, "workshop", msg, job.id)
            notify_role(db, "admin", msg, job.id)
            notify_role(db, "accounts", msg, job.id)
            if job.created_by:
                db.add(models.Notification(user_id=job.created_by, job_card_id=job.id, message=msg))
            sales_users = db.query(models.User).filter(models.User.role == "sales", models.User.full_name == job.salesman_name).all()
            for su in sales_users:
                db.add(models.Notification(user_id=su.id, job_card_id=job.id, message=msg))

    db.commit()
    return {"success": True}

@app.post("/api/jobs/{job_id}/pdi/sign")
async def api_sign_pdi(job_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        body = await request.json()
    except:
        body = {}

    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    assert_editable(db, job, body.get("user_id"))

    fails = db.query(models.PDIItem).filter(models.PDIItem.job_card_id == job_id, models.PDIItem.status == "Fail").count()
    if fails:
        raise HTTPException(status_code=400, detail="Cannot sign PDI while items are marked Fail. Send back to workshop to fix first.")

    party = body.get("party")  # "workshop" or "sales"
    user_id = body.get("user_id")

    if party == "workshop":
        job.pdi_signed_workshop = True
        job.pdi_signed_workshop_by = user_id
        job.pdi_signed_workshop_at = datetime.utcnow()
        if job.status == "Work Completed":
            job.status = "PDI in Progress"
    elif party == "sales":
        job.pdi_signed_sales = True
        job.pdi_signed_sales_by = user_id
        job.pdi_signed_sales_at = datetime.utcnow()
    else:
        raise HTTPException(status_code=400, detail="party must be workshop or sales")

    if job.pdi_signed_workshop and job.pdi_signed_sales:
        job.status = "PDI Completed"
        job.pdi_completed_at = datetime.utcnow()

    db.commit()

    if user_id:
        log_audit(db, user_id, "Signed PDI", job.id, f"PDI signed by {party}")

    return {
        "success": True,
        "pdi_signed_workshop": job.pdi_signed_workshop,
        "pdi_signed_sales": job.pdi_signed_sales,
        "status": job.status
    }

# ---------- DELETE JOB (Admin only) ----------

@app.post("/api/jobs/{job_id}/delete")
async def api_delete_job(job_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        body = await request.json()
    except:
        body = {}

    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    user_id = body.get("user_id")
    job_number = job.job_number

    # Delete related records first (tasks, pdi items, audit can stay or cascade)
    db.query(models.JobTask).filter(models.JobTask.job_card_id == job_id).delete()
    db.query(models.PDIItem).filter(models.PDIItem.job_card_id == job_id).delete()
    db.delete(job)
    db.commit()

    if user_id:
        log_audit(db, user_id, "Deleted Job Card", None, f"Deleted job {job_number}")

    return {"success": True, "message": f"Job {job_number} deleted"}

# ---------- LISTS & LOCATION DASHBOARD ----------

def providers_for_task_db(db: Session, task_name: str):
    base = providers_for_task(task_name)
    name = (task_name or "").lower()
    rows = db.query(models.ThirdPartyCompany).filter(models.ThirdPartyCompany.is_active == True).all()
    extra = []
    for r in rows:
        cat = (r.category or "").lower()
        if cat in name or any(k in name for k in cat.split()):
            extra.append(r.name)
        elif "roadworthy" in name and "roadworthy" in cat:
            extra.append(r.name)
        elif "barrel" in name and "barrel" in cat:
            extra.append(r.name)
        elif "pressure" in name and "pressure" in cat:
            extra.append(r.name)
        elif "calibrat" in name and "calibrat" in cat:
            extra.append(r.name)
        elif ("auto electrical" in name or "scotty" in name) and "electrical" in cat:
            extra.append(r.name)
    out = []
    for n in base + extra:
        if n not in out:
            out.append(n)
    return out

def grouped_third_parties(db: Session):
    rows = db.query(models.ThirdPartyCompany).filter(models.ThirdPartyCompany.is_active == True).order_by(models.ThirdPartyCompany.category, models.ThirdPartyCompany.name).all()
    grouped = {}
    for r in rows:
        grouped.setdefault(r.category, []).append(r.name)
    if grouped:
        return [{"service": k, "providers": v} for k, v in grouped.items()]
    return THIRD_PARTY_SERVICES

@app.get("/api/lists")
async def api_lists(db: Session = Depends(get_db)):
    return {
        "locations": LOCATIONS,
        "activity_types": ACTIVITY_TYPES,
        "extra_work_presets": EXTRA_WORK_PRESETS,
        "third_party_services": grouped_third_parties(db),
        "barrel_intervals": BARREL_INTERVALS,
        "third_party_categories": ["Barrel Test", "Pressure Test", "Calibration Test", "Roadworthy", "Auto Electrical", "Other"]
    }

@app.get("/api/locations-board")
async def api_locations_board(db: Session = Depends(get_db)):
    jobs = db.query(models.JobCard).filter(
        models.JobCard.status != "Delivered / Closed"
    ).all()
    board = {loc: [] for loc in LOCATIONS}
    board["Unspecified"] = []
    for j in jobs:
        loc = j.current_location if j.current_location in board else "Unspecified"
        board[loc].append({
            "id": j.id,
            "job_number": j.job_number,
            "stock_number": j.stock_number,
            "vehicle_description": j.vehicle_description,
            "year": j.year,
            "label": f"{j.stock_number} {j.vehicle_description} {j.year or ''}".strip(),
            "status": j.status,
            "priority": j.priority
        })
    return {"board": board}

@app.post("/api/jobs/{job_id}/location")
async def api_update_location(job_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        body = await request.json()
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    location = body.get("location")
    if location not in LOCATIONS:
        raise HTTPException(status_code=400, detail="Invalid location")
    old = job.current_location
    job.current_location = location
    if location in WORKSHOP_BAYS and not job.workshop_entered_at:
        job.workshop_entered_at = datetime.utcnow()
    user_id = body.get("user_id")
    name = body.get("full_name") or "Staff"
    update = models.JobUpdate(
        job_card_id=job.id,
        category="location",
        description=f"Location changed: {old or '—'} → {location}",
        notes=body.get("notes"),
        created_by_name=name,
        created_by=user_id
    )
    db.add(update)
    db.commit()
    if user_id:
        log_audit(db, user_id, "Changed Location", job.id, update.description)
    return {"success": True, "current_location": job.current_location}

@app.post("/api/jobs/{job_id}/updates")
async def api_add_update(job_id: int, request: Request, db: Session = Depends(get_db)):
    """Permanent update. Cannot be deleted."""
    try:
        body = await request.json()
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    category = body.get("category") or "progress"
    description = (body.get("description") or "").strip()
    if not description:
        raise HTTPException(status_code=400, detail="Description is required")
    user_id = body.get("user_id")
    name = body.get("full_name") or "Staff"
    update = models.JobUpdate(
        job_card_id=job.id,
        category=category,
        description=description,
        notes=(body.get("notes") or "").strip() or None,
        created_by_name=name,
        created_by=user_id
    )
    db.add(update)
    # Also add to Work / Prep Tasks so workshop can mark completed + notes
    if category in ("extra_work", "activity", "parts", "third_party"):
        prefix = {
            "extra_work": "Extra",
            "activity": "Activity",
            "parts": "Parts",
            "third_party": "3rd party",
        }.get(category, "Extra")
        db.add(models.JobTask(
            job_card_id=job.id,
            task_name=f"{prefix}: {description}",
            description=body.get("notes") or None,
            is_custom=True,
            status="Not Started",
            notes=body.get("notes") or None
        ))
    # Also persist latest 3rd party / parts onto the job card when provided
    if category == "third_party":
        if body.get("third_party_place"):
            job.third_party_place = body.get("third_party_place")
        if body.get("third_party_date"):
            job.third_party_date = body.get("third_party_date")
    if category == "parts" and body.get("parts_to_order"):
        existing = job.parts_to_order or ""
        addition = body.get("parts_to_order")
        job.parts_to_order = (existing + "\n" + addition).strip() if existing else addition
    db.commit()
    if user_id:
        log_audit(db, user_id, "Added Update", job.id, f"{category}: {description}")
    return {"success": True, "id": update.id}

@app.get("/jobs/{job_id}/print", response_class=HTMLResponse)
async def print_job_page(request: Request, job_id: int):
    return render_template("print_job.html", request=request, job_id=job_id)


@app.post("/api/jobs/{job_id}/third-party")
async def api_add_third_party(job_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        body = await request.json()
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    assert_editable(db, job, body.get("user_id"))
    service = (body.get("service") or "").strip()
    provider = (body.get("provider") or "").strip()
    booked_date = body.get("booked_date") or None
    interval = (body.get("interval") or "").strip()
    if not service or not provider:
        raise HTTPException(status_code=400, detail="Service and provider are required")
    allowed = {s["service"]: s["providers"] for s in THIRD_PARTY_SERVICES}
    if service not in allowed or provider not in allowed[service]:
        raise HTTPException(status_code=400, detail="Invalid service or provider")
    if service == "Barrel Test":
        if interval not in BARREL_INTERVALS:
            raise HTTPException(status_code=400, detail="Select barrel test interval: 3 year, 6 year, 3 and 6 year, or 15 year")
        service = f"Barrel Test ({interval})"
    user_id = body.get("user_id")
    name = body.get("full_name") or "Staff"
    booking = models.ThirdPartyBooking(
        job_card_id=job.id,
        service=service,
        provider=provider,
        booked_date=booked_date,
        notes=(body.get("notes") or "").strip() or None,
        created_by_name=name,
        created_by=user_id
    )
    db.add(booking)
    desc = f"{service} — {provider}" + (f" on {booked_date}" if booked_date else "")
    db.add(models.JobUpdate(
        job_card_id=job.id,
        category="third_party",
        description=desc,
        notes=body.get("notes"),
        created_by_name=name,
        created_by=user_id
    ))
    # Fill the matching Work / Prep task with provider + date
    match_key = service.lower()
    matched = False
    for t in job.tasks:
        name = (t.task_name or "").lower()
        hit = False
        if "barrel" in match_key and "barrel" in name:
            hit = True
        elif "pressure" in match_key and "pressure" in name:
            hit = True
        elif "calibration" in match_key and "calibration" in name:
            hit = True
        elif "roadworthy" in match_key and "roadworthy" in name and "as is" not in name:
            hit = True
        elif "auto electrical" in match_key and ("auto electrical" in name or "man auto" in name):
            hit = True
        if hit:
            t.third_party_provider = provider
            t.booked_date = booked_date
            t.task_location = f"3rd Party: {provider}"
            t.notes = ((t.notes + " | ") if t.notes else "") + desc
            matched = True
    if not matched:
        db.add(models.JobTask(
            job_card_id=job.id,
            task_name=f"3rd party: {desc}",
            description=body.get("notes"),
            is_custom=True,
            status="Not Started",
            notes=body.get("notes"),
            task_location=f"3rd Party: {provider}",
            third_party_provider=provider,
            booked_date=booked_date
        ))
    job.third_party_place = f"{service} - {provider}"
    job.third_party_date = booked_date
    db.commit()
    if user_id:
        log_audit(db, user_id, "3rd Party Booked", job.id, desc)
    return {"success": True, "id": booking.id}

@app.get("/jobs/{job_id}/print-pdi", response_class=HTMLResponse)
async def print_pdi_page(request: Request, job_id: int):
    return render_template("print_pdi.html", request=request, job_id=job_id)

@app.get("/jobs/{job_id}/print-work", response_class=HTMLResponse)
async def print_work_page(request: Request, job_id: int):
    return render_template("print_work.html", request=request, job_id=job_id)

@app.post("/api/jobs/{job_id}/parts")
async def api_add_part(job_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        body = await request.json()
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    assert_editable(db, job, body.get("user_id"))
    desc = (body.get("description") or "").strip()
    if not desc:
        raise HTTPException(status_code=400, detail="Part description is required")
    user_id = body.get("user_id")
    name = body.get("full_name") or "Staff"
    part = models.PartItem(
        job_card_id=job.id,
        description=desc,
        order_number=(body.get("order_number") or "").strip() or None,
        quantity=(body.get("quantity") or "").strip() or "1",
        price=(body.get("price") or "").strip() or None,
        supplier_invoice=(body.get("supplier_invoice") or "").strip() or None,
        part_progress=body.get("part_progress") or "To be ordered",
        ordered_date=body.get("ordered_date") or None,
        created_by_name=name,
        created_by=user_id
    )
    db.add(part)
    db.add(models.JobUpdate(
        job_card_id=job.id,
        category="parts",
        description="Part added: " + desc,
        notes=part.order_number,
        created_by_name=name,
        created_by=user_id
    ))
    db.add(models.JobTask(
        job_card_id=job.id,
        task_name="Parts: " + desc,
        is_custom=True,
        status="Not Started"
    ))
    notify_role(db, "workshop", f"Part to be ordered: {desc} on {job.stock_number}", job.id)
    db.commit()
    return {"success": True, "id": part.id}

@app.post("/api/jobs/{job_id}/parts/{part_id}/order-number")
async def api_set_part_order(job_id: int, part_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        body = await request.json()
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    part = db.query(models.PartItem).filter(models.PartItem.id == part_id, models.PartItem.job_card_id == job_id).first()
    if not part:
        raise HTTPException(status_code=404, detail="Part not found")
    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    assert_editable(db, job, body.get("user_id"))
    order_number = (body.get("order_number") or "").strip()
    if not order_number:
        raise HTTPException(status_code=400, detail="Order number is required")
    part.order_number = order_number
    part.order_number_by = body.get("full_name") or "Staff"
    db.add(models.JobUpdate(
        job_card_id=job_id,
        category="parts",
        description=f"Order number added for {part.description}: {order_number} by {part.order_number_by}",
        created_by_name=body.get("full_name") or "Staff",
        created_by=body.get("user_id")
    ))
    db.commit()
    return {"success": True}

@app.get("/api/admin/backup.db")
async def api_admin_backup_db(current_user: models.User = Depends(auth.get_current_active_user)):
    require_admin(current_user)
    path = SQLITE_FILE or "status_jobcard.db"
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Database file not found")
    stamp = datetime.utcnow().strftime("%Y%m%d")
    return FileResponse(path, filename=f"status_jobcard_backup_{stamp}.db", media_type="application/octet-stream")

@app.get("/api/admin/backup-pack.zip")
async def api_admin_backup_pack(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_admin(current_user)
    import csv, io, zipfile, tempfile
    stamp = datetime.utcnow().strftime("%Y%m%d")
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    tmp.close()
    with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as zf:
        path = SQLITE_FILE or "status_jobcard.db"
        if path and os.path.exists(path):
            zf.write(path, f"status_jobcard_backup_{stamp}.db")
        jobs = db.query(models.JobCard).order_by(models.JobCard.id.desc()).all()
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["job_number", "stock_number", "vehicle", "year", "type", "client", "salesman", "status", "location", "created"])
        for j in jobs:
            w.writerow([j.job_number, j.stock_number, j.vehicle_description, j.year, f"{j.main_type}/{j.sub_type}", j.client_name, j.salesman_name, j.status, j.current_location or "", j.created_at])
        zf.writestr("jobcards.csv", buf.getvalue())
        parts = db.query(models.PartItem).all()
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["job_id", "description", "qty", "order_number", "progress", "price", "invoice"])
        for p in parts:
            w.writerow([p.job_card_id, p.description, getattr(p, "quantity", ""), p.order_number, getattr(p, "part_progress", ""), getattr(p, "price", ""), getattr(p, "supplier_invoice", "")])
        zf.writestr("parts.csv", buf.getvalue())
    return FileResponse(tmp.name, filename=f"sts_jobcards_backup_{stamp}.zip", media_type="application/zip")

@app.get("/api/admin/export/jobs.csv")
async def api_admin_export_jobs(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_admin(current_user)
    import csv, io
    jobs = db.query(models.JobCard).order_by(models.JobCard.id.desc()).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["job_number", "stock_number", "vehicle", "year", "type", "client", "salesman", "status", "location", "created"])
    for j in jobs:
        w.writerow([j.job_number, j.stock_number, j.vehicle_description, j.year, f"{j.main_type} / {j.sub_type}", j.client_name, j.salesman_name, j.status, j.current_location or "", j.created_at])
    return Response(content=buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=jobcards_backup.csv"})

@app.get("/api/admin/export/extras.csv")
async def export_extras_csv(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_admin(current_user)
    import csv
    from io import StringIO
    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Date", "Job Number", "Stock Number", "Year", "Vehicle", "Category", "Description", "Notes", "Added By"])
    rows = db.query(models.JobUpdate).order_by(models.JobUpdate.created_at.desc()).all()
    for u in rows:
        job = db.query(models.JobCard).filter(models.JobCard.id == u.job_card_id).first()
        writer.writerow([
            u.created_at.isoformat() if u.created_at else "",
            job.job_number if job else "",
            job.stock_number if job else "",
            job.year if job else "",
            job.vehicle_description if job else "",
            u.category,
            u.description,
            u.notes or "",
            u.created_by_name or "",
        ])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=workshop_extras.csv"}
    )

@app.get("/api/admin/export/parts.csv")
async def export_parts_csv(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_admin(current_user)
    import csv
    from io import StringIO
    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Date", "Job Number", "Stock Number", "Year", "Vehicle", "Part Description", "Order Number", "Added By"])
    parts = db.query(models.PartItem).order_by(models.PartItem.created_at.desc()).all()
    for p in parts:
        job = db.query(models.JobCard).filter(models.JobCard.id == p.job_card_id).first()
        writer.writerow([
            p.created_at.isoformat() if p.created_at else "",
            job.job_number if job else "",
            job.stock_number if job else "",
            job.year if job else "",
            job.vehicle_description if job else "",
            p.description,
            p.order_number or "",
            p.created_by_name or "",
        ])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=parts.csv"}
    )

@app.get("/api/admin/export/custom-tasks.csv")
async def export_custom_tasks_csv(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_admin(current_user)
    import csv
    from io import StringIO
    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Date", "Job Number", "Stock Number", "Year", "Vehicle", "Task", "Status", "Notes"])
    tasks = db.query(models.JobTask).filter(models.JobTask.is_custom == True).order_by(models.JobTask.created_at.desc()).all()
    for t in tasks:
        job = db.query(models.JobCard).filter(models.JobCard.id == t.job_card_id).first()
        writer.writerow([
            t.created_at.isoformat() if t.created_at else "",
            job.job_number if job else "",
            job.stock_number if job else "",
            job.year if job else "",
            job.vehicle_description if job else "",
            t.task_name,
            t.status,
            t.notes or "",
        ])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=manual_tasks.csv"}
    )

def diary_service_label(task_name: str):
    n = (task_name or "").lower()
    if "as is" in n and "without" in n:
        return None
    if "as is" in n and "roadworthy" in n:
        return "As Is - with Roadworthy only"
    if "roadworthy" in n:
        return "Roadworthy"
    if "calibrat" in n:
        return "Calibration (if fitted with meters)"
    if "pressure" in n or "slp" in n:
        return "Pressure Test (SLP)"
    if "barrel" in n:
        if "3 and 6" in n or "3 & 6" in n:
            return "Barrel test - 3 and 6 year"
        if "15" in n:
            return "Barrel test - 15 year"
        if "6 year" in n or "6-year" in n:
            return "Barrel test - 6 year"
        if "3 year" in n or "3-year" in n:
            return "Barrel test - 3 year"
        return "Barrel test"
    return None

@app.get("/api/workshop/bookings")
async def api_workshop_bookings(db: Session = Depends(get_db)):
    out = []
    seen = set()
    tasks = db.query(models.JobTask).all()
    for t in tasks:
        label = diary_service_label(t.task_name)
        if not label:
            continue
        if not (t.third_party_provider or t.booked_date or (t.task_location or "").lower().startswith("3rd")):
            if t.status in ("Not Started", None, ""):
                continue
        job = db.query(models.JobCard).filter(models.JobCard.id == t.job_card_id).first()
        if not job or job.status == "Delivered / Closed":
            continue
        key = (job.id, label)
        seen.add(key)
        out.append({
            "id": f"task-{t.id}",
            "service": label,
            "provider": t.third_party_provider or t.task_location or "—",
            "booked_date": t.booked_date,
            "status": t.status,
            "test_result": getattr(t, "test_result", None),
            "job_id": job.id,
            "job_number": job.job_number,
            "stock_number": job.stock_number,
            "vehicle_description": job.vehicle_description,
            "year": job.year,
            "label": f"{job.stock_number} {job.vehicle_description or ''} {job.year or ''}".strip(),
        })
    rows = db.query(models.ThirdPartyBooking).order_by(models.ThirdPartyBooking.booked_date).all()
    for b in rows:
        job = db.query(models.JobCard).filter(models.JobCard.id == b.job_card_id).first()
        if not job or job.status == "Delivered / Closed":
            continue
        svc = diary_service_label(b.service) or b.service
        if (job.id, svc) in seen:
            continue
        out.append({
            "id": f"bk-{b.id}",
            "service": svc,
            "provider": b.provider,
            "booked_date": b.booked_date,
            "status": "",
            "test_result": None,
            "job_id": job.id,
            "job_number": job.job_number,
            "stock_number": job.stock_number,
            "vehicle_description": job.vehicle_description,
            "year": job.year,
            "label": f"{job.stock_number} {job.vehicle_description or ''} {job.year or ''}".strip(),
        })
    out.sort(key=lambda x: (x.get("booked_date") or "9999", x.get("stock_number") or ""))
    return {"bookings": out}

def notify_role(db, role, message, job_id=None):
    users = db.query(models.User).filter(models.User.role == role, models.User.is_active == True).all()
    for u in users:
        db.add(models.Notification(user_id=u.id, job_card_id=job_id, message=message))

@app.post("/api/jobs/{job_id}/parts/{part_id}/progress")
async def api_part_progress(job_id: int, part_id: int, request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    part = db.query(models.PartItem).filter(models.PartItem.id == part_id, models.PartItem.job_card_id == job_id).first()
    if not part:
        raise HTTPException(status_code=404, detail="Part not found")
    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    assert_editable(db, job, body.get("user_id"))
    progress = body.get("part_progress") or "To be ordered"
    if progress not in ("To be ordered", "Ordered", "Waiting for delivery", "Delivered"):
        raise HTTPException(status_code=400, detail="Invalid progress")
    if "supplier_invoice" in body:
        part.supplier_invoice = (body.get("supplier_invoice") or "").strip() or None
    if "price" in body:
        part.price = (body.get("price") or "").strip() or None
    if "quantity" in body:
        part.quantity = (body.get("quantity") or "").strip() or part.quantity
    if progress == "Delivered" and not (part.supplier_invoice or "").strip():
        raise HTTPException(status_code=400, detail="Supplier invoice number is required when the part is received / delivered")
    part.part_progress = progress
    if body.get("ordered_date"):
        part.ordered_date = body.get("ordered_date")
    db.add(models.JobUpdate(
        job_card_id=job_id,
        category="parts",
        description=f"{part.description}: {progress}",
        notes=part.ordered_date,
        created_by_name=body.get("full_name") or "Staff",
        created_by=body.get("user_id")
    ))
    db.commit()
    return {"success": True}

@app.post("/api/jobs/{job_id}/parts/{part_id}/follow-up")
async def api_part_followup(job_id: int, part_id: int, request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    part = db.query(models.PartItem).filter(models.PartItem.id == part_id, models.PartItem.job_card_id == job_id).first()
    if not part:
        raise HTTPException(status_code=404, detail="Part not found")
    part.follow_up = True
    part.follow_up_note = (body.get("note") or "").strip() or "Please follow up"
    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    msg = f"Follow-up requested: {part.description} on {job.stock_number if job else job_id}"
    if part.follow_up_note:
        msg += f" — {part.follow_up_note}"
    notify_role(db, "workshop", msg, job_id)
    db.add(models.JobUpdate(
        job_card_id=job_id,
        category="parts",
        description=msg,
        created_by_name=body.get("full_name") or "Admin",
        created_by=body.get("user_id")
    ))
    db.commit()
    return {"success": True}

@app.post("/api/jobs/{job_id}/activity")
async def api_set_activity(job_id: int, request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    assert_editable(db, job, body.get("user_id"))

    assert_editable(db, job, body.get("user_id"))

    assert_editable(db, job, body.get("user_id"))
    location = body.get("location")
    if location:
        job.current_location = location
        if location in WORKSHOP_BAYS and not job.workshop_entered_at:
            job.workshop_entered_at = datetime.utcnow()
    job.current_activity = (body.get("activity") or "").strip() or None
    job.current_activity_notes = (body.get("notes") or "").strip() or None
    job.current_activity_at = datetime.utcnow()
    job.current_activity_by = body.get("full_name") or "Workshop"
    db.add(models.JobUpdate(
        job_card_id=job.id,
        category="activity",
        description=f"{job.current_location or ''} — {job.current_activity or ''}".strip(" —"),
        notes=job.current_activity_notes,
        created_by_name=job.current_activity_by,
        created_by=body.get("user_id")
    ))
    if job.current_activity:
        db.add(models.JobTask(
            job_card_id=job.id,
            task_name="Activity: " + job.current_activity[:80],
            description=job.current_activity_notes,
            is_custom=True,
            needs_approval=False,
            status="In Progress",
            task_location=job.current_location,
            notes=job.current_activity_notes,
            last_updated_by_name=job.current_activity_by
        ))
    db.commit()
    return {"success": True}

@app.get("/admin/print-bookings", response_class=HTMLResponse)
async def admin_print_bookings_page(request: Request):
    return render_template("print_admin_bookings.html", request=request)

@app.get("/api/admin/job-bookings")
async def api_admin_job_bookings(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_admin(current_user)
    jobs = db.query(models.JobCard).filter(models.JobCard.status != "Delivered / Closed").order_by(models.JobCard.created_at.desc()).all()
    out = []
    for job in jobs:
        parts = db.query(models.PartItem).filter(models.PartItem.job_card_id == job.id).all()
        extras = db.query(models.JobTask).filter(models.JobTask.job_card_id == job.id, models.JobTask.is_custom == True).all()
        if not parts and not extras:
            continue
        out.append({
            "id": job.id,
            "job_number": job.job_number,
            "stock_number": job.stock_number,
            "vehicle_description": job.vehicle_description,
            "year": job.year,
            "status": job.status,
            "salesman_name": job.salesman_name,
            "parts": [{
                "description": p.description,
                "quantity": getattr(p, "quantity", None) or "1",
                "price": getattr(p, "price", None),
                "order_number": p.order_number,
                "part_progress": getattr(p, "part_progress", None) or "To be ordered",
                "supplier_invoice": getattr(p, "supplier_invoice", None)
            } for p in parts],
            "extras": [{
                "task_name": e.task_name,
                "description": e.description,
                "status": e.status,
                "needs_approval": bool(getattr(e, "needs_approval", False))
            } for e in extras]
        })
    return {"jobs": out}

@app.get("/api/workshop/parts")
async def api_workshop_parts(db: Session = Depends(get_db)):
    parts = db.query(models.PartItem).order_by(models.PartItem.created_at.desc()).all()
    out = []
    for p in parts:
        job = db.query(models.JobCard).filter(models.JobCard.id == p.job_card_id).first()
        if job and job.status == "Delivered / Closed":
            continue
        out.append({
            "id": p.id,
            "job_id": p.job_card_id,
            "description": p.description,
            "order_number": p.order_number,
            "quantity": getattr(p, "quantity", None) or "1",
            "price": getattr(p, "price", None),
            "supplier_invoice": getattr(p, "supplier_invoice", None),
            "part_progress": getattr(p, "part_progress", None) or "To be ordered",
            "ordered_date": getattr(p, "ordered_date", None),
            "follow_up": bool(getattr(p, "follow_up", False)),
            "follow_up_note": getattr(p, "follow_up_note", None),
            "stock_number": job.stock_number if job else "",
            "vehicle_description": job.vehicle_description if job else "",
            "year": job.year if job else "",
        })
    return {"parts": out}

@app.get("/api/notifications")
async def api_notifications(user_id: int, db: Session = Depends(get_db)):
    rows = db.query(models.Notification).filter(models.Notification.user_id == user_id).order_by(models.Notification.created_at.desc()).limit(30).all()
    return {"notifications": [{
        "id": n.id,
        "message": n.message,
        "job_card_id": n.job_card_id,
        "is_read": n.is_read,
        "created_at": n.created_at.isoformat() if n.created_at else None
    } for n in rows]}

@app.post("/api/jobs/{job_id}/tasks/{task_id}/approve")
async def api_approve_task(job_id: int, task_id: int, request: Request, db: Session = Depends(get_db)):
    body = {}
    try:
        body = await request.json()
    except:
        pass
    task = db.query(models.JobTask).filter(models.JobTask.id == task_id, models.JobTask.job_card_id == job_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task.needs_approval = False
    task.approved_by_name = body.get("full_name") or "Admin"
    db.add(models.JobUpdate(
        job_card_id=job_id,
        category="progress",
        description=f"Admin approved extra task: {task.task_name}",
        created_by_name=task.approved_by_name,
        created_by=body.get("user_id")
    ))
    db.commit()
    return {"success": True}

@app.get("/api/pdi-fails")
async def api_pdi_fails(db: Session = Depends(get_db)):
    jobs = db.query(models.JobCard).filter(models.JobCard.status == "PDI Failed - Returned to Workshop").order_by(models.JobCard.created_at.desc()).all()
    out = []
    for j in jobs:
        fails = db.query(models.PDIItem).filter(models.PDIItem.job_card_id == j.id, models.PDIItem.status == "Fail").all()
        out.append({
            "id": j.id,
            "job_number": j.job_number,
            "stock_number": j.stock_number,
            "vehicle_description": j.vehicle_description,
            "year": j.year,
            "salesman_name": j.salesman_name,
            "fails": [{"item": f.check_item, "notes": f.notes, "by": f.initials} for f in fails]
        })
    return {"jobs": out}
