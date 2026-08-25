from fastapi import FastAPI, Request, Depends, HTTPException, status, Form, Body
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import Optional, List
import os
import json

from .database import engine, get_db, Base
from . import models, auth
from .seed import seed_database
from .tasks_config import get_tasks_for_vehicle

# Create tables and seed
Base.metadata.create_all(bind=engine)
seed_database()

app = FastAPI(title="Status Truck Sales - Job Card System")

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

# ---------- AUTH ROUTES ----------

@app.post("/token")
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = auth.authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
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
        "user_id": user.id
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
                "client_name", "salesman_name", "priority", "target_delivery_date"]
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
        customer_order_ref=body.get("customer_order_ref") or None,
        salesman_name=body["salesman_name"],
        created_by=created_by_id,
        priority=body.get("priority", "Normal"),
        target_delivery_date=body.get("target_delivery_date"),
        current_location=body.get("current_location") or None,
        internal_notes=body.get("internal_notes") or None,
        quotation_invoice_number=body.get("quotation_invoice_number") or None,
        estimated_workshop_hours=body.get("estimated_workshop_hours") or None,
        other_instructions=body.get("other_instructions") or None,
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
async def api_list_jobs(status: str = None, db: Session = Depends(get_db)):
    query = db.query(models.JobCard).order_by(models.JobCard.created_at.desc())
    if status:
        query = query.filter(models.JobCard.status == status)
    jobs = query.limit(50).all()
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
            "completed_at": t.completed_at.isoformat() if t.completed_at else None
        })

    return {
        "id": job.id,
        "job_number": job.job_number,
        "stock_number": job.stock_number,
        "vehicle_description": job.vehicle_description,
        "year": job.year,
        "main_type": job.main_type,
        "sub_type": job.sub_type,
        "client_name": job.client_name,
        "customer_order_ref": job.customer_order_ref,
        "salesman_name": job.salesman_name,
        "priority": job.priority,
        "target_delivery_date": job.target_delivery_date,
        "current_location": job.current_location,
        "internal_notes": job.internal_notes,
        "other_instructions": job.other_instructions,
        "status": job.status,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "accepted_at": job.accepted_at.isoformat() if job.accepted_at else None,
        "tasks": tasks
    }

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

    task = db.query(models.JobTask).filter(
        models.JobTask.id == task_id,
        models.JobTask.job_card_id == job_id
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    user_id = body.get("user_id")
    new_status = body.get("status")
    notes = body.get("notes")

    allowed_statuses = ["Not Started", "In Progress", "Completed", "Blocked"]
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
        notes=body.get("notes") or None
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

@app.get("/api/admin/users")
async def api_list_users(db: Session = Depends(get_db)):
    users = db.query(models.User).order_by(models.User.role, models.User.full_name).all()
    return {
        "users": [
            {
                "id": u.id,
                "username": u.username,
                "full_name": u.full_name,
                "role": u.role,
                "is_active": u.is_active,
                "created_at": u.created_at.isoformat() if u.created_at else None
            } for u in users
        ]
    }

@app.post("/api/admin/users")
async def api_create_user(request: Request, db: Session = Depends(get_db)):
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
async def api_toggle_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = not user.is_active
    db.commit()
    return {"success": True, "is_active": user.is_active}

@app.post("/api/admin/users/{user_id}/reset-password")
async def api_reset_password(user_id: int, request: Request, db: Session = Depends(get_db)):
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
            "pdi_signed_sales_at": job.pdi_signed_sales_at.isoformat() if job.pdi_signed_sales_at else None
        },
        "items": items
    }

@app.post("/api/jobs/{job_id}/pdi/items/{item_id}")
async def api_update_pdi_item(job_id: int, item_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        body = await request.json()
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    item = db.query(models.PDIItem).filter(
        models.PDIItem.id == item_id,
        models.PDIItem.job_card_id == job_id
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="PDI item not found")

    if "status" in body:
        if body["status"] not in ("Pass", "Fail", "N/A", None, ""):
            raise HTTPException(status_code=400, detail="Status must be Pass, Fail or N/A")
        item.status = body["status"] if body["status"] else None
    if "notes" in body:
        item.notes = body["notes"]
    if "initials" in body:
        item.initials = body["initials"]

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
