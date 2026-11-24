from fastapi import FastAPI, Request, Depends, HTTPException, status, Form, Body, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timedelta
from typing import Optional, List
import os
import json
import re
import uuid

from .database import engine, get_db, Base, SQLITE_FILE, SessionLocal
from . import models, auth
from .seed import seed_database
from .pdf_forms import build_pdi_pdf, build_work_pdf
from .lists_config import LOCATIONS, WORKSHOP_BAYS, ACTIVITY_TYPES, EXTRA_WORK_PRESETS, THIRD_PARTY_SERVICES, BARREL_INTERVALS, providers_for_task, SUPPLY_CATEGORIES, type_family
from .migrate import migrate_schema
from .stock_photos import match_stock_photo
from .client_report import build_report, render_pdf, whatsapp_text
from .display import job_display_id, job_display_label, stock_repeat_counts, with_display

# Create tables and seed
Base.metadata.create_all(bind=engine)
migrate_schema()
seed_database()

app = FastAPI(title="Status Truck Sales - Job Card System", docs_url=None, redoc_url=None, openapi_url=None)

FAILED_LOGINS = {}
MAX_FAILED = 6
LOCK_MINUTES = 15

# Paths a 'yard' role user may reach (public paths are handled before this check).
YARD_ROLE_PATHS = ("/yard", "/yard/print", "/logout", "/set-password", "/api/me/set-password", "/api/push/subscribe")

def yard_role_path_allowed(path: str) -> bool:
    return path in YARD_ROLE_PATHS or path.startswith("/api/yard/")

@app.middleware("http")
async def security_headers(request: Request, call_next):
    path = request.url.path
    public_unauthenticated = path in (
        "/",
        "/set-password",
        "/login",
        "/token",
        "/health",
        "/sw.js",
        "/manifest.json",
        "/api/push/public-key",
    ) or path.startswith("/static/")
    raw = auth.token_from_request(request)
    user = None
    if raw:
        db = SessionLocal()
        try:
            user = auth._user_from_token_string(raw, db)
        finally:
            db.close()
        if user and not getattr(user, "is_active", True):
            user = None
    if not public_unauthenticated:
        if user is None:
            if path.startswith("/api/") or path.startswith("/uploads/"):
                return JSONResponse(
                    {"detail": "Could not validate credentials"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return RedirectResponse(url="/login")
        if getattr(user, "must_change_password", False) and path not in ("/set-password", "/api/me/set-password"):
            if path.startswith("/api/"):
                return JSONResponse({"detail": "Set a new password before using the app."}, status_code=403)
            return RedirectResponse(url="/set-password")
        if (getattr(user, "role", "") or "") == "yard" and not yard_role_path_allowed(path):
            # Yard users may only use the Yard check. Deny everything else server-side.
            if path.startswith("/api/") or path.startswith("/uploads/"):
                return JSONResponse({"detail": "Yard users can only use the Yard check."}, status_code=403)
            return RedirectResponse(url="/yard")
    if path.startswith("/uploads/tasks/") or path.startswith("/uploads/yard/"):
        # Direct task and yard photo files stay unavailable, even to signed-in staff.
        return JSONResponse({"detail": "Not found"}, status_code=404)
    request.state.yard_only = bool(user and user.role == "yard")
    request.state.has_yard_access = bool(user and user_has_yard_access(user))
    request.state.is_stock_manager = bool(user and is_stock_manager(user))
    request.state.can_view_yard_stock = bool(user and can_view_yard_stock(user))
    request.state.can_start_job = bool(user and can_create_job(user))
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    if not (path.startswith("/api/yard/stock/units/") and path.endswith("/photo") and response.status_code == 200):
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

def is_admin_user(user: models.User) -> bool:
    if not user:
        return False
    if user.role in ("admin", "accounts"):
        return True
    return (user.full_name or "").strip().lower() == "sebastian van biljon"

def require_admin(user: models.User):
    if not is_admin_user(user):
        raise HTTPException(status_code=403, detail="Admin access only")
    return user

def user_has_yard_access(user) -> bool:
    """Admin, accounts and yard always have Yard check. Others only with yard_access=1."""
    if not user:
        return False
    if (getattr(user, "role", "") or "") in ("admin", "accounts", "yard"):
        return True
    return bool(getattr(user, "yard_access", False))

# Absolute paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
DATA_ROOT = "/data" if os.path.isdir("/data") else BASE_DIR
UPLOAD_DIR = os.path.join(DATA_ROOT, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(os.path.join(UPLOAD_DIR, "supplier"), exist_ok=True)
os.makedirs(os.path.join(UPLOAD_DIR, "tasks"), exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

@app.get("/sw.js")
async def service_worker():
    path = os.path.join(BASE_DIR, "static", "js", "sw.js")
    return FileResponse(path, media_type="application/javascript", headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})

@app.get("/manifest.json")
async def manifest():
    path = os.path.join(BASE_DIR, "static", "manifest.json")
    return FileResponse(path, media_type="application/manifest+json")

from jinja2 import Environment, FileSystemLoader, select_autoescape

jinja_env = Environment(
    loader=FileSystemLoader(os.path.join(BASE_DIR, "templates")),
    autoescape=select_autoescape(["html", "xml"])
)

def render_template(name: str, **context):
    if "yard_only" not in context:
        context["yard_only"] = bool(getattr(getattr(context.get("request"), "state", None), "yard_only", False))
    if "has_yard_access" not in context:
        context["has_yard_access"] = bool(getattr(getattr(context.get("request"), "state", None), "has_yard_access", False))
    if "is_stock_manager" not in context:
        context["is_stock_manager"] = bool(getattr(getattr(context.get("request"), "state", None), "is_stock_manager", False))
    if "can_view_yard_stock" not in context:
        context["can_view_yard_stock"] = bool(getattr(getattr(context.get("request"), "state", None), "can_view_yard_stock", False))
    if "can_start_job" not in context:
        context["can_start_job"] = bool(getattr(getattr(context.get("request"), "state", None), "can_start_job", False))
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

def stock_counts_exact(db, stock_value) -> dict:
    stock = (stock_value or "").strip()
    if not stock:
        return {}
    n = db.query(models.JobCard).filter(models.JobCard.stock_number == stock_value).count()
    return {stock: n}

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
    if is_archived(job):
        raise HTTPException(status_code=400, detail="This job is archived and read-only.")

def is_job_salesman(job, user) -> bool:
    if not job or not user:
        return False
    return (job.salesman_name or "").strip().casefold() == (user.full_name or "").strip().casefold()

def has_sales_rights(user) -> bool:
    """Sales role, or an admin user with the sales_rights flag (Sebastian on one login)."""
    if not user:
        return False
    return (user.role or "") == "sales" or bool(getattr(user, "sales_rights", False))

def job_salesman_users(db, job, skip_roles=()):
    """Active users who get the salesman's notices for this job: sales role or sales_rights flag, name match."""
    from sqlalchemy import or_
    q = db.query(models.User).filter(models.User.is_active == True, or_(models.User.role == "sales", models.User.sales_rights == True))
    if job.salesman_name:
        q = q.filter(models.User.full_name == job.salesman_name)
    return [u for u in q.all() if (u.role or "") not in skip_roles]

def assert_sales_owner(db, job, user, body, action):
    if is_job_salesman(job, user):
        return
    if user and user.role == "admin" and body.get("override"):
        named = db.query(models.User).filter(models.User.id == body.get("on_behalf_of")).first()
        if named and is_job_salesman(job, named):
            return
    who = job.salesman_name or "the salesman who opened this job"
    raise HTTPException(status_code=400, detail=f"Only {who} can {action}. Another salesman cannot sign this job.")

def is_test_task(name: str) -> bool:
    n = (name or "").lower()
    keys = ("roadworthy", "brake test", "pressure test", "barrel test", "calibration", "dekra", "slp")
    if any(k in n for k in keys):
        return True
    return "3rd party" in n or "third party" in n or "third-party" in n

def require_other_side(db, job, user_id, other_by, side_label, body):
    if not user_id or not other_by or int(other_by) != int(user_id):
        return None
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user or user.role != "admin":
        raise HTTPException(status_code=400, detail=f"You already signed the other side of {side_label}. One person cannot sign both sides.")
    reason = (body.get("reason") or "").strip()
    on_behalf = body.get("on_behalf_of")
    if not body.get("override") or len(reason) < 15 or not on_behalf:
        raise HTTPException(status_code=400, detail="Admin override needs 'Signing on behalf of' a named sales or workshop user, and a reason of at least 15 characters.")
    named = db.query(models.User).filter(models.User.id == on_behalf, models.User.role.in_(("sales", "workshop"))).first()
    if not named:
        raise HTTPException(status_code=400, detail="Signing on behalf of must be a named sales or workshop user.")
    return named

def record_override(db, job, user_id, named, reason, side):
    job.admin_override = True
    db.add(models.IntegrityEvent(
        job_card_id=job.id,
        event_type="override",
        side=side,
        user_id=user_id,
        on_behalf_of=named.id,
        reason=reason,
        override=True,
    ))
    log_audit(db, user_id, "Admin override", job.id, f"{side} on behalf of {named.full_name}. {reason}")

def user_name(db: Session, user_id):
    if not user_id:
        return None
    u = db.query(models.User).filter(models.User.id == user_id).first()
    return u.full_name if u else None

def parts_missing_order_numbers(db: Session, job_id: int):
    parts = db.query(models.PartItem).filter(models.PartItem.job_card_id == job_id).all()
    return [p for p in parts if not (p.order_number or "").strip()]

# ---------- AUTH ROUTES ----------

@app.get("/api/push/public-key")
async def api_push_public_key():
    from .vapid import VAPID_PUBLIC_KEY, PUSH_ENABLED
    if not PUSH_ENABLED or not VAPID_PUBLIC_KEY:
        return {"key": None, "enabled": False}
    return {"key": VAPID_PUBLIC_KEY, "enabled": True}

@app.post("/api/push/subscribe")
async def api_push_subscribe(request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    body = await request.json()
    user_id = body.get("user_id")
    sub = body.get("subscription") or {}
    endpoint = (sub.get("endpoint") or "").strip()
    keys = sub.get("keys") or {}
    if not user_id or not endpoint or not keys.get("p256dh") or not keys.get("auth"):
        raise HTTPException(status_code=400, detail="Invalid subscription")
    existing = db.query(models.PushSubscription).filter(models.PushSubscription.endpoint == endpoint).first()
    if existing:
        existing.user_id = user_id
        existing.p256dh = keys["p256dh"]
        existing.auth = keys["auth"]
    else:
        db.add(models.PushSubscription(
            user_id=user_id,
            endpoint=endpoint,
            p256dh=keys["p256dh"],
            auth=keys["auth"]
        ))
    db.commit()
    return {"success": True}

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
    if (user.username or "").lower() == "damian" and (user.role or "") != "marketing":
        user.role = "marketing"
        db.commit()
    access_token_expires = timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = auth.create_access_token(
        data={"sub": user.username, "role": user.role, "full_name": user.full_name},
        expires_delta=access_token_expires
    )
    payload = {
        "access_token": access_token,
        "token_type": "bearer",
        "role": user.role,
        "full_name": user.full_name,
        "user_id": user.id,
        "must_change_password": bool(getattr(user, "must_change_password", False)),
        "supplier_company": getattr(user, "supplier_company", None),
        "yard_access": user_has_yard_access(user),
        "sales_rights": has_sales_rights(user)
    }
    resp = JSONResponse(payload)
    resp.set_cookie(
        key="sts_token",
        value=access_token,
        max_age=auth.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        samesite="lax",
        secure=True,
        path="/",
    )
    return resp

@app.get("/set-password", response_class=HTMLResponse)
async def set_password_page(request: Request):
    return render_template("set_password.html", request=request, page_title="Set new password")

@app.get("/logout")
async def logout_page():
    response = HTMLResponse('<script>localStorage.clear();location.replace("/login");</script>')
    response.delete_cookie("sts_token", path="/")
    return response

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return render_template("login.html", request=request)

@app.post("/api/me/set-password")
async def api_set_password(request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    body = await request.json()
    current = body.get("current_password") or ""
    new_password = body.get("new_password") or ""
    if len(new_password) < 10:
        raise HTTPException(status_code=400, detail="New password must be at least 10 characters")
    user = db.query(models.User).filter(models.User.id == current_user.id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not auth.verify_password(current, user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is wrong")
    if auth.verify_password(new_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="New password cannot be the same as the old one")
    user.hashed_password = auth.get_password_hash(new_password)
    user.must_change_password = False
    user.password_changed_at = datetime.utcnow()
    db.commit()
    return {"success": True}

@app.post("/api/admin/users/force-reset")
async def api_force_reset_all(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_admin(current_user)
    users = db.query(models.User).all()
    for u in users:
        u.must_change_password = True
    log_audit(db, current_user.id, "Force password reset", None, f"must_change_password set for {len(users)} users")
    db.commit()
    return {"success": True, "count": len(users)}

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return RedirectResponse(url="/login")

# ---------- DASHBOARD ----------

@app.get("/locations", response_class=HTMLResponse)
async def locations_page(request: Request, current_user: models.User = Depends(auth.get_current_active_user)):
    return render_template("locations.html", request=request, page_title="Locations")

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, current_user: models.User = Depends(auth.get_current_active_user)):
    return render_template("dashboard.html", request=request, page_title="Dashboard")

@app.get("/stock", response_class=HTMLResponse)
async def stock_page(request: Request, current_user: models.User = Depends(auth.get_current_active_user)):
    return render_template("stock.html", request=request, page_title="Workshop stock")

@app.get("/supplier", response_class=HTMLResponse)
async def supplier_page(request: Request, current_user: models.User = Depends(auth.get_current_active_user)):
    return render_template("supplier.html", request=request, page_title="Supplier jobs")

# ---------- CREATE JOB CARD ----------

@app.get("/jobs/create", response_class=HTMLResponse)
async def create_job_page(request: Request, current_user: models.User = Depends(auth.get_current_active_user)):
    return render_template("create_job.html", request=request, page_title="Create Job Card")

@app.get("/api/tasks-for-type")
async def api_tasks_for_type(main_type: str, year: str = None, purpose: str = "sold", current_user: models.User = Depends(auth.get_current_active_user)):
    """Return the standard tasks for a vehicle type (used by frontend)."""
    try:
        if (purpose or "").strip().lower() == "showroom":
            return {"tasks": get_showroom_tasks(main_type)}
        return {"tasks": get_tasks_for_vehicle(main_type, year)}
    except Exception as exc:
        # Never leave sales with an empty task list.
        return {"tasks": [
            {"task_name": "Roadworthy", "description": "Prepare and take the vehicle for roadworthy"},
            {"task_name": "Brake tests", "description": "Brake test to be done before delivery"},
            {"task_name": "Wash / clean for delivery", "description": "Wash and present the vehicle for handover"},
            {"task_name": "Touch-ups", "description": "Paint / body touch-ups as needed"},
            {"task_name": "Polish", "description": "Polish cab / body for delivery"},
            {"task_name": "Spray rims", "description": "Spray or refurbish rims"},
            {"task_name": "As Is – with Roadworthy only", "description": "Sell as is. Only roadworthy to be done"},
        ], "warning": str(exc)}

@app.get("/api/jobs/open-ws")
async def api_open_ws(stock: str, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    key = "".join((stock or "").split()).upper()
    if not key:
        return {"open": []}
    jobs = active_jobs(db).all()
    matched = [j for j in jobs if "".join((j.stock_number or "").split()).upper() == key]
    counts = stock_repeat_counts(matched)
    open_jobs = []
    for j in matched:
        open_jobs.append(with_display({
            "id": j.id,
            "job_number": j.job_number,
            "stock_number": j.stock_number,
            "status": j.status,
            "job_purpose": getattr(j, "job_purpose", None) or "sold",
        }, j, counts))
    return {"open": open_jobs}

@app.post("/api/jobs/create")
async def api_create_job(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_active_user),
):
    """Create a new Job Card with selected tasks."""
    try:
        body = await request.json()
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    purpose = (body.get("job_purpose") or "sold").strip().lower()
    if purpose not in ("sold", "showroom"):
        purpose = "sold"
    if purpose == "showroom":
        body["client_name"] = body.get("client_name") or "Showroom"
        body["salesman_name"] = body.get("salesman_name") or "Workshop"
        body["quotation_invoice_number"] = body.get("quotation_invoice_number") or "SHOWROOM"
        if not body.get("target_delivery_date"):
            body["target_delivery_date"] = str(sast_today()) if "sast_today" in dir() else datetime.utcnow().date().isoformat()
        if not body.get("priority"):
            body["priority"] = "Normal"

    # Required fields
    required = ["stock_number", "vehicle_description", "year", "main_type",
                "client_name", "salesman_name", "priority", "target_delivery_date",
                "vin_number", "registration_number", "quotation_invoice_number"]
    for field in required:
        if not body.get(field):
            raise HTTPException(status_code=400, detail=f"Missing required field: {field}")

    # Get current user from token if possible (simplified for now)
    # In production we would decode the JWT properly here
    created_by_id = body.get("user_id")  # passed from frontend for now

    convert_id = body.get("convert_job_id")
    if purpose == "sold" and convert_id:
        job = db.query(models.JobCard).filter(models.JobCard.id == int(convert_id)).first()
        if not job:
            raise HTTPException(status_code=404, detail="Showroom job not found")
        if (getattr(job, "job_purpose", None) or "sold") != "showroom":
            raise HTTPException(status_code=400, detail="Only a showroom job can be converted to sales")
        if job.status in CLOSED_STATUSES:
            raise HTTPException(status_code=400, detail="That showroom job is already closed")
        job.job_purpose = "sold"
        job.client_name = body["client_name"].strip()
        job.salesman_name = body["salesman_name"]
        job.priority = body.get("priority") or job.priority
        job.target_delivery_date = body.get("target_delivery_date") or job.target_delivery_date
        job.quotation_invoice_number = body.get("quotation_invoice_number") or job.quotation_invoice_number
        if (body.get("vin_number") or "").strip():
            job.vin_number = body["vin_number"].strip()
        if (body.get("registration_number") or "").strip():
            job.registration_number = body["registration_number"].strip().upper()
        if (body.get("vehicle_description") or "").strip():
            job.vehicle_description = body["vehicle_description"].strip()
        if body.get("year"):
            job.year = str(body["year"]).strip()
        if body.get("main_type"):
            job.main_type = body["main_type"]
        if body.get("sub_type"):
            job.sub_type = body["sub_type"]
        if body.get("internal_notes"):
            job.internal_notes = body.get("internal_notes")
        if job.status == "Pending Admin Approval":
            job.status = "Submitted to Workshop"
        existing_names = {(t.task_name or "").strip().lower() for t in (job.tasks or [])}
        for t in body.get("selected_tasks") or []:
            name = (t.get("task_name") or "").strip()
            if not name or name.lower() in existing_names:
                continue
            db.add(models.JobTask(
                job_card_id=job.id,
                task_name=name,
                description=t.get("description"),
                is_custom=False,
                needs_approval=False,
                status="Not Started",
            ))
            existing_names.add(name.lower())
        other_text = (body.get("other_instructions") or "").strip()
        if other_text:
            db.add(models.JobTask(
                job_card_id=job.id,
                task_name="Other: " + other_text[:80],
                description=other_text,
                is_custom=True,
                needs_approval=True,
                status="Not Started",
            ))
        add_update(db, job.id, "progress", "Showroom job converted to sales. Showroom tasks kept.", created_by_name=body.get("salesman_name"), created_by=created_by_id)
        db.commit()
        if created_by_id:
            log_audit(db, created_by_id, "Converted showroom to sales", job.id, job.stock_number)
        msg = f"{job_display_id(job)} showroom job is now a sales job for {job.client_name}"
        notify_role(db, "workshop", msg, job.id)
        notify_role(db, "admin", msg, job.id)
        notify_role(db, "accounts", msg, job.id)
        return {
            "success": True,
            "converted": True,
            "job_number": job.job_number,
            "job_id": job.id,
            "message": f"{job_display_id(job)} converted from showroom to sales. Showroom tasks kept.",
        }

    job_number = generate_job_number(db)
    start_status = "Pending Admin Approval" if purpose == "showroom" else "Submitted to Workshop"

    job = models.JobCard(
        job_number=job_number,
        stock_number=body["stock_number"].strip().upper(),
        vehicle_description=body["vehicle_description"].strip(),
        year=str(body["year"]).strip(),
        main_type=body["main_type"],
        sub_type=(body.get("sub_type") or body.get("main_type") or "").strip(),
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
        job_purpose=purpose,
        status=start_status
    )
    db.add(job)
    db.flush()  # get job.id

    # Add selected tasks
    selected_tasks = body.get("selected_tasks", [])
    if purpose == "showroom" and not selected_tasks:
        selected_tasks = get_showroom_tasks(body.get("main_type"))
    for t in selected_tasks:
        custom = bool(t.get("is_custom", False))
        task = models.JobTask(
            job_card_id=job.id,
            task_name=t.get("task_name"),
            description=t.get("description"),
            is_custom=custom,
            needs_approval=custom,
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
                  f"Job {job_display_id(job)} – {job.vehicle_description}")
    if purpose == "showroom":
        msg = f"SHOWROOM job {job_display_id(job)} — {job.vehicle_description} needs admin approval"
        notify_role(db, "admin", msg, job.id)
        notify_role(db, "accounts", msg, job.id)
        notify_role(db, "workshop", msg, job.id)
        done_msg = f"Showroom job {job_display_id(job)} created. Waiting for admin approval before work starts."
    else:
        msg = f"New job card {job_display_id(job)} — {job.vehicle_description}"
        notify_role(db, "workshop", msg, job.id)
        notify_role(db, "admin", msg, job.id)
        notify_role(db, "accounts", msg, job.id)
        done_msg = f"Job Card {job_display_id(job)} submitted to Workshop successfully."

    return {
        "success": True,
        "job_number": job.job_number,
        "job_id": job.id,
        "message": done_msg
    }

# ---------- LIST JOBS (basic) ----------

DELIVERED_STATUS = "Delivered / Closed"
DELIVERED_LOCATION = "Out / Delivered"
CLOSED_STATUSES = (DELIVERED_STATUS,)

def active_jobs(db):
    """Every active list must start here so archived jobs stay out of the floor."""
    return db.query(models.JobCard).filter(models.JobCard.archived_at == None)

def is_archived(job) -> bool:
    return bool(job and getattr(job, "archived_at", None))

def is_delivery_wash_task(name: str) -> bool:
    n = (name or "").lower()
    return "wash" in n and "clean" in n and "delivery" in n

def open_blocking_tasks(job):
    open_names = []
    for t in (job.tasks or []):
        if (t.status or "") == "Completed":
            continue
        if is_delivery_wash_task(t.task_name):
            continue
        open_names.append(t.task_name or "Task")
    return open_names

def delivery_wash_open(job):
    wash = [t for t in (job.tasks or []) if is_delivery_wash_task(getattr(t, "task_name", "") or "")]
    return bool(wash) and not all((t.status or "") == "Completed" for t in wash)

# ---------- "Waiting on" sign-off display (admin/accounts view only; display, no rule changes) ----------

def can_see_waiting_on(user) -> bool:
    return bool(user) and (user.role or "") in ("admin", "accounts")

def waiting_on_task_rows(db, job_ids):
    """One query: job_id -> list of (task_name, status, needs_approval)."""
    out = {}
    if not job_ids:
        return out
    rows = db.query(models.JobTask.job_card_id, models.JobTask.task_name, models.JobTask.status, models.JobTask.needs_approval).filter(models.JobTask.job_card_id.in_(list(job_ids))).all()
    for jid, name, st, appr in rows:
        out.setdefault(jid, []).append((name, st, appr))
    return out

def signoff_waiting_on(job, viewer, task_rows=None):
    """Short lines saying who the job is waiting on. Uses the same fields the sign-off rules use; changes nothing."""
    if not job or is_archived(job) or (job.status or "") in CLOSED_STATUSES:
        return []
    if task_rows is None:
        task_rows = [(t.task_name, t.status, getattr(t, "needs_approval", False)) for t in (job.tasks or [])]
    status = job.status or ""
    showroom = is_showroom(job)
    salesman = (job.salesman_name or "").strip() or "salesman"
    sales = "You (sales)" if viewer is not None and is_job_salesman(job, viewer) else f"Sales ({salesman})"
    lines = []
    approvals = sum(1 for n, st, appr in task_rows if appr and (st or "") != "Completed")
    open_tasks = sum(1 for n, st, appr in task_rows if (st or "") != "Completed" and not is_delivery_wash_task(n or ""))
    wash_open = any(is_delivery_wash_task(n or "") for n, st, a in task_rows) and not all((st or "") == "Completed" for n, st, a in task_rows if is_delivery_wash_task(n or ""))
    if approvals:
        lines.append("Admin — approve extra task" if approvals == 1 else f"Admin — approve {approvals} extra tasks")
    if status == "Pending Admin Approval":
        lines.append("Admin — approve showroom job")
        return lines
    if status == "Submitted to Workshop":
        lines.append("Workshop — accept job")
        return lines
    if status == "PDI Failed - Returned to Workshop":
        lines.append("Workshop — fix PDI fails")
    if open_tasks:
        lines.append("Workshop — 1 task open" if open_tasks == 1 else f"Workshop — {open_tasks} tasks open")
    if status not in ("Work Completed", "PDI in Progress", "PDI Completed", "Ready for Delivery"):
        return lines
    if showroom:
        if not job.ready_workshop:
            lines.append("Workshop — showroom sign-off")
        elif status == "Ready for Delivery":
            if wash_open:
                lines.append("Workshop — wash for delivery")
            lines.append("Workshop or sales — deliver / close")
        return lines
    if type_family(job.main_type) == "tanker":
        if not job.empty_signed_workshop:
            lines.append("Workshop — tanker empty check")
        if not job.empty_signed_sales:
            lines.append(f"{sales} — tanker empty check")
    if not job.pdi_signed_workshop:
        lines.append("Workshop — PDI sign-off")
    if not job.pdi_signed_sales:
        lines.append(f"{sales} — PDI sign-off")
    if job.pdi_signed_workshop and job.pdi_signed_sales:
        if not job.ready_workshop:
            lines.append("Workshop — mark ready")
        if not job.ready_sales:
            lines.append(f"{sales} — mark ready")
    if status == "Ready for Delivery":
        if wash_open:
            lines.append("Workshop — wash for delivery")
        lines.append(f"{sales} — deliver / close")
    return lines

def archive_blockers(job):
    missing = []
    if is_showroom(job):
        if not job.ready_workshop:
            missing.append("Workshop ready for showroom sign-off")
    else:
        if not (job.pdi_signed_workshop and job.pdi_signed_sales):
            missing.append("Both PDI sign-offs (workshop and sales)")
    if delivery_wash_open(job):
        missing.append("Wash / clean for delivery must be completed before the client collects")
    return missing

def archive_job(db, job, user_id=None, by_name="System", reason="Job delivered and archived"):
    if not job or is_archived(job):
        return job
    now = datetime.utcnow()
    job.status = DELIVERED_STATUS
    job.current_location = DELIVERED_LOCATION
    if not job.delivered_at:
        job.delivered_at = now
    if user_id and not getattr(job, "delivered_by", None):
        job.delivered_by = user_id
    job.archived_at = now
    job.archived_by = user_id
    job.archive_reason = reason
    db.add(models.JobUpdate(
        job_card_id=job.id,
        category="progress",
        description=f"Job delivered and archived {job_display_id(job)}",
        notes=reason,
        created_by_name=by_name or "System",
        created_by=user_id,
    ))
    if user_id:
        log_audit(db, user_id, "Job delivered and archived", job.id, f"{job_display_id(job)} {reason}")
    db.commit()
    return job

def require_admin_only(user):
    if not user or user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

def hide_archived(job, user):
    if is_archived(job) and (not user or user.role != "admin"):
        raise HTTPException(status_code=404, detail="Job not found")

def job_allocated_to_company(job, company: str) -> bool:
    if not job or not company:
        return False
    if any(company_match(getattr(t, "third_party_provider", None), company) for t in (job.tasks or [])):
        return True
    if any(company_match(getattr(b, "provider", None), company) for b in (getattr(job, "third_party_bookings", None) or [])):
        return True
    return False

@app.get("/api/jobs")
async def api_list_jobs(request: Request, status: str = None, salesman: str = None, created_by: int = None, archived: int = 0, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    raw = auth.token_from_request(request)
    user = auth._user_from_token_string(raw, db) if raw else None
    if user and user.role == "supplier":
        return {"jobs": []}
    query = active_jobs(db).order_by(models.JobCard.created_at.desc())
    if status:
        query = query.filter(models.JobCard.status == status)
    if salesman:
        query = query.filter(models.JobCard.salesman_name == salesman)
    if created_by:
        query = query.filter(models.JobCard.created_by == created_by)
    jobs = query.limit(400).all()
    counts = stock_repeat_counts(jobs)
    show_waiting = can_see_waiting_on(current_user)
    task_map = waiting_on_task_rows(db, [j.id for j in jobs]) if show_waiting else {}
    result = []
    for j in jobs:
        row = with_display({
            "id": j.id,
            "job_number": j.job_number,
            "stock_number": j.stock_number,
            "vehicle_description": j.vehicle_description,
            "main_type": j.main_type,
            "job_purpose": getattr(j, "job_purpose", None) or "sold",
            "client_name": j.client_name,
            "salesman_name": j.salesman_name,
            "priority": j.priority,
            "target_delivery_date": j.target_delivery_date,
            "status": j.status,
            "current_location": j.current_location,
            "year": j.year,
            "created_by": j.created_by,
            "accepted_by": j.accepted_by,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "pdi_signed_sales": bool(j.pdi_signed_sales),
            "pdi_signed_workshop": bool(j.pdi_signed_workshop),
            "ready_sales": bool(j.ready_sales),
            "ready_workshop": bool(j.ready_workshop),
            "photo_url": job_photo_url(j, yard_photo_map_cached(db))
        }, j, counts)
        if show_waiting:
            row["waiting_on"] = signoff_waiting_on(j, current_user, task_map.get(j.id, []))
        result.append(row)
    return {"jobs": result}

@app.get("/health")
async def health():
    return {"status": "ok", "app": "Status Truck Sales Job Card System", "version": "0.3-glass"}

# ---------- JOB LIST PAGE ----------

@app.get("/jobs", response_class=HTMLResponse)
async def jobs_page(request: Request, current_user: models.User = Depends(auth.get_current_active_user)):
    return render_template("jobs.html", request=request, page_title="Job Cards")

@app.get("/jobs/archive", response_class=HTMLResponse)
async def jobs_archive_page(request: Request, current_user: models.User = Depends(auth.get_current_active_user)):
    return RedirectResponse(url="/archive")

@app.get("/archive", response_class=HTMLResponse)
async def archive_page(request: Request, current_user: models.User = Depends(auth.get_current_active_user)):
    return render_template("archive.html", request=request, page_title="Archive")

@app.get("/api/archive")
async def api_archive(q: str = "", db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_admin_only(current_user)
    rows = db.query(models.JobCard).filter(models.JobCard.archived_at != None).order_by(models.JobCard.archived_at.desc()).all()
    needle = (q or "").strip().lower()
    # Count repeats across the full archive, not just the filtered page.
    counts = stock_repeat_counts(rows)
    out = []
    for j in rows:
        hay = " ".join([j.stock_number or "", j.job_number or "", j.vin_number or "", j.registration_number or "", j.client_name or "", j.vehicle_description or ""]).lower()
        if needle and needle not in hay:
            continue
        who = user_name(db, j.archived_by) or ""
        out.append(with_display({
            "id": j.id,
            "job_number": j.job_number,
            "stock_number": j.stock_number,
            "vehicle_description": j.vehicle_description,
            "year": j.year,
            "client_name": j.client_name,
            "vin_number": j.vin_number,
            "registration_number": j.registration_number,
            "delivered_at": j.delivered_at.isoformat() if j.delivered_at else None,
            "archived_at": j.archived_at.isoformat() if j.archived_at else None,
            "archived_by": who,
            "status": j.status,
        }, j, counts))
    return {"jobs": out}

@app.post("/api/archive/{job_id}/restore")
async def api_restore_archive(job_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_admin_only(current_user)
    try:
        body = await request.json()
    except Exception:
        body = {}
    reason = (body.get("reason") or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="A reason is required to restore")
    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    if not job or not is_archived(job):
        raise HTTPException(status_code=404, detail="Archived job not found")
    job.archived_at = None
    job.archived_by = None
    job.archive_reason = reason
    job.status = "Ready for Delivery"
    job.current_location = "Yard"
    db.add(models.JobUpdate(
        job_card_id=job.id,
        category="progress",
        description=f"Restored to active {job_display_id(job)}",
        notes=reason,
        created_by_name=current_user.full_name,
        created_by=current_user.id,
    ))
    log_audit(db, current_user.id, "Restored to active", job.id, f"{job_display_id(job)} {reason}")
    db.commit()
    return {"success": True}

@app.get("/api/archive/{job_id}")
async def api_archive_detail(job_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_admin_only(current_user)
    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    if not job or not is_archived(job):
        raise HTTPException(status_code=404, detail="Archived job not found")
    return with_display({
        "id": job.id,
        "job_number": job.job_number,
        "stock_number": job.stock_number,
        "vehicle_description": job.vehicle_description,
        "year": job.year,
        "client_name": job.client_name,
        "vin_number": job.vin_number,
        "registration_number": job.registration_number,
        "status": job.status,
        "delivered_at": job.delivered_at.isoformat() if job.delivered_at else None,
        "archived_at": job.archived_at.isoformat() if job.archived_at else None,
        "archived_by": user_name(db, job.archived_by),
        "archive_reason": job.archive_reason,
        "pdi_signed_workshop": bool(job.pdi_signed_workshop),
        "pdi_signed_sales": bool(job.pdi_signed_sales),
        "ready_workshop": bool(job.ready_workshop),
        "ready_sales": bool(job.ready_sales),
        "tasks": [{"task_name": t.task_name, "status": t.status, "notes": t.notes} for t in (job.tasks or [])],
        "parts": [{"description": p.description, "quantity": p.quantity, "order_number": p.order_number, "part_progress": p.part_progress} for p in (job.parts or [])],
        "bookings": [{"service": b.service, "provider": b.provider, "booked_date": b.booked_date} for b in (job.third_party_bookings or [])],
        "pdi": [{"check_item": p.check_item, "status": p.status, "notes": p.notes} for p in (job.pdi_items or [])],
        "updates": [{"description": u.description, "notes": u.notes, "created_by_name": u.created_by_name, "created_at": u.created_at.isoformat() if u.created_at else None} for u in (job.updates or [])],
        "audit": [{"action": a.action, "details": a.details, "timestamp": a.timestamp.isoformat() if a.timestamp else None} for a in (job.audit_logs or [])],
    }, job, stock_counts_exact(db, job.stock_number))

# ---------- ACCEPT JOB ----------

@app.post("/api/jobs/{job_id}/approve-showroom")
async def api_approve_showroom(job_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    if current_user.role not in ("admin", "accounts"):
        raise HTTPException(status_code=403, detail="Admin must approve showroom jobs")
    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "Pending Admin Approval":
        raise HTTPException(status_code=400, detail="This job is not waiting for approval")
    job.status = "Submitted to Workshop"
    db.add(models.JobUpdate(
        job_card_id=job.id,
        category="progress",
        description=f"Showroom job approved by {current_user.full_name}",
        created_by_name=current_user.full_name,
        created_by=current_user.id,
    ))
    log_audit(db, current_user.id, "Approved showroom job", job.id, job.stock_number)
    notify_role(db, "workshop", f"Showroom job approved: {job_display_id(job)} — {job.vehicle_description}", job.id)
    db.commit()
    return {"success": True, "status": job.status}

@app.get("/api/jobs/showroom-approval-queue")
async def api_showroom_approval_queue(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    if current_user.role not in ("admin", "accounts", "workshop"):
        return {"jobs": []}
    jobs = active_jobs(db).filter(models.JobCard.status == "Pending Admin Approval").order_by(models.JobCard.created_at.desc()).all()
    return {"jobs": [{
        "id": j.id,
        "stock_number": j.stock_number,
        "vehicle_description": j.vehicle_description,
        "year": j.year,
        "main_type": j.main_type,
        "created_by_name": user_name(db, j.created_by),
    } for j in jobs]}

@app.post("/api/jobs/{job_id}/accept")
async def api_accept_job(job_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    try:
        body = await request.json()
    except:
        body = {}

    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status == "Pending Admin Approval":
        raise HTTPException(status_code=400, detail="Admin must approve this showroom job before workshop can accept it")
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
        log_audit(db, user_id, "Accepted Job Card", job.id, f"Job {job_display_id(job)} accepted by Workshop")

    # Photo reminder ping. Information only: any error here is ignored so accept always succeeds.
    try:
        names = [t.task_name for t in (job.tasks or []) if needs_photo_reminder(job, t)]
        if names:
            notify_role(db, "workshop", f"Photo reminder: take BEFORE and AFTER photos on {job_display_id(job)} — " + ", ".join(names[:4]) + (" …" if len(names) > 4 else ""), job.id)
            db.commit()
    except Exception:
        db.rollback()

    # TODO: create notification for the salesman

    return {"success": True, "message": f"Job {job_display_id(job)} accepted", "status": job.status}

# ---------- JOB DETAIL ----------

@app.get("/jobs/client-reports", response_class=HTMLResponse)
async def client_reports_page(request: Request, current_user: models.User = Depends(auth.get_current_active_user)):
    return render_template("client_reports.html", request=request, page_title="Client reports")

@app.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail_page(request: Request, job_id: int, current_user: models.User = Depends(auth.get_current_active_user)):
    return render_template("job_detail.html", request=request, job_id=job_id, page_title="Job Detail")

@app.get("/api/jobs/empty-check-queue")
async def api_empty_check_queue(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    jobs = active_jobs(db).all()
    out = []
    for j in jobs:
        if is_showroom(j) or type_family(j.main_type) != "tanker":
            continue
        if j.status not in ("Work Completed", "PDI in Progress", "PDI Completed", "Ready for Delivery"):
            continue
        need = False
        if current_user.role == "sales":
            if (j.salesman_name or "") != current_user.full_name:
                continue
            need = not bool(j.empty_signed_sales)
        elif current_user.role == "workshop":
            need = not bool(j.empty_signed_workshop)
        elif current_user.role in ("admin", "accounts"):
            need = not (j.empty_signed_workshop and j.empty_signed_sales)
        else:
            continue
        if not need:
            continue
        out.append({
            "id": j.id,
            "stock_number": j.stock_number,
            "vehicle_description": j.vehicle_description,
            "year": j.year,
            "status": j.status,
            "empty_signed_workshop": bool(j.empty_signed_workshop),
            "empty_signed_sales": bool(j.empty_signed_sales),
        })
    return {"jobs": out}

@app.get("/api/jobs/signoff-queue")
async def api_signoff_queue(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    open_jobs = active_jobs(db).all()
    changed = False
    for j in open_jobs:
        if j.status in ("Work Completed", "PDI in Progress", "PDI Completed", "Ready for Delivery", "Pending Admin Approval"):
            continue
        tasks = db.query(models.JobTask).filter(models.JobTask.job_card_id == j.id).all()
        if work_is_done(tasks) and mark_work_complete(db, j):
            changed = True
    if changed:
        db.commit()
    statuses = ("Work Completed", "PDI in Progress", "PDI Completed", "Ready for Delivery")
    jobs = active_jobs(db).filter(models.JobCard.status.in_(statuses)).order_by(models.JobCard.stock_number).all()
    out = []
    for j in jobs:
        need_pdi = False
        need_ready = False
        showroom = is_showroom(j)
        if showroom and current_user.role == "sales":
            continue
        if current_user.role == "sales":
            if (j.salesman_name or "") != current_user.full_name:
                continue
            need_pdi = not bool(j.pdi_signed_sales)
            need_ready = not bool(j.ready_sales)
        elif current_user.role == "workshop":
            need_pdi = (not showroom) and (not bool(j.pdi_signed_workshop))
            need_ready = not bool(j.ready_workshop)
        elif current_user.role in ("admin", "accounts"):
            need_pdi = (not showroom) and (not (j.pdi_signed_sales and j.pdi_signed_workshop))
            need_ready = not (j.ready_workshop if showroom else (j.ready_sales and j.ready_workshop))
        else:
            continue
        if not (need_pdi or need_ready or open_blocking_tasks(j)):
            continue
        action = "Sign PDI" if need_pdi else "Mark ready"
        open_tasks = open_blocking_tasks(j)
        if open_tasks:
            action = "Ready - tasks outstanding"
        out.append({
            "id": j.id,
            "stock_number": j.stock_number,
            "vehicle_description": j.vehicle_description,
            "year": j.year,
            "status": j.status,
            "salesman_name": j.salesman_name,
            "need_pdi": need_pdi,
            "need_ready": need_ready,
            "open_tasks": open_tasks,
            "action": action,
        })
        if can_see_waiting_on(current_user):
            out[-1]["waiting_on"] = signoff_waiting_on(j, current_user)
    return {"jobs": out}

@app.get("/api/jobs/{job_id}")
async def api_get_job(job_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    raw = auth.token_from_request(request)
    user = auth._user_from_token_string(raw, db) if raw else None
    if user and user.role == "supplier":
        if not job_allocated_to_company(job, user.supplier_company):
            raise HTTPException(status_code=403, detail="This job is not booked to your company")
    hide_archived(job, user)

    job_photos = db.query(models.TaskPhoto).filter(models.TaskPhoto.job_card_id == job.id).order_by(models.TaskPhoto.uploaded_at, models.TaskPhoto.id).all()
    photo_archive_rows = db.query(models.PhotoArchive).filter(models.PhotoArchive.job_card_id == job.id).order_by(models.PhotoArchive.id).all()
    photos_archived = any(a.deleted_at for a in photo_archive_rows)

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
            "responsible_user_id": getattr(t, "responsible_user_id", None),
            "responsible_name": getattr(t, "responsible_name", None),
            "assisting_names": getattr(t, "assisting_names", None),
            "paint_team": getattr(t, "paint_team", None),
            "is_paint_task": is_paint_task(t.task_name),
            "providers": providers_for_task_db(db, t.task_name),
            "completed_at": t.completed_at.isoformat() if t.completed_at else None,
            "completed_by": t.completed_by,
            **task_photo_info(job, t, job_photos, photos_archived)
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

    return with_display({
        "id": job.id,
        "job_number": job.job_number,
        "stock_number": job.stock_number,
        "vehicle_description": job.vehicle_description,
        "year": job.year,
        "main_type": job.main_type,
        "job_purpose": getattr(job, "job_purpose", None) or "sold",
        "sub_type": job.sub_type,
        "photo_url": job_photo_url(job, yard_photo_map_cached(db)),
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
        "update_requested_at": job.update_requested_at.isoformat() if getattr(job, "update_requested_at", None) else None,
        "update_requested_by": getattr(job, "update_requested_by", None),
        "update_request_note": getattr(job, "update_request_note", None),
        "pdi_signed_workshop": job.pdi_signed_workshop,
        "pdi_signed_sales": job.pdi_signed_sales,
        "pdi_signed_workshop_by_name": user_name(db, job.pdi_signed_workshop_by),
        "pdi_signed_sales_by_name": user_name(db, job.pdi_signed_sales_by),
        "admin_override": bool(getattr(job, "admin_override", False)),
        "pdi_signed_workshop_at": job.pdi_signed_workshop_at.isoformat() if job.pdi_signed_workshop_at else None,
        "pdi_signed_sales_at": job.pdi_signed_sales_at.isoformat() if job.pdi_signed_sales_at else None,
        "is_tanker": type_family(job.main_type) == "tanker",
        "empty_signed_workshop": bool(getattr(job, "empty_signed_workshop", False)),
        "empty_signed_sales": bool(getattr(job, "empty_signed_sales", False)),
        "empty_signed_workshop_by_name": user_name(db, getattr(job, "empty_signed_workshop_by", None)),
        "empty_signed_sales_by_name": user_name(db, getattr(job, "empty_signed_sales_by", None)),
        "empty_signed_workshop_at": job.empty_signed_workshop_at.isoformat() if getattr(job, "empty_signed_workshop_at", None) else None,
        "empty_signed_sales_at": job.empty_signed_sales_at.isoformat() if getattr(job, "empty_signed_sales_at", None) else None,
        "status": job.status,
        "archived": is_archived(job),
        "waiting_on": signoff_waiting_on(job, current_user) if can_see_waiting_on(current_user) else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "created_by": job.created_by,
        "created_by_name": user_name(db, job.created_by),
        "accepted_at": job.accepted_at.isoformat() if job.accepted_at else None,
        "accepted_by_name": user_name(db, job.accepted_by),
        "tasks": tasks,
        "updates": updates,
        "third_party_bookings": bookings,
        "supplier_updates": [{
            "id": s.id,
            "company": s.company,
            "status": s.status,
            "work_doing": s.work_doing,
            "parts_needed": s.parts_needed,
            "note": s.note,
            "photo_path": s.photo_path,
            "workshop_parts_decision": s.workshop_parts_decision,
            "workshop_parts_note": s.workshop_parts_note,
            "created_by_name": s.created_by_name,
            "created_at": s.created_at.isoformat() if s.created_at else None
        } for s in db.query(models.SupplierUpdate).filter(models.SupplierUpdate.job_card_id == job.id).order_by(models.SupplierUpdate.created_at.desc()).all()],
        "parts": part_items,
        "parts_missing_order": any(not (p.get("order_number") or "").strip() for p in part_items),
        "supplies": [{
            "id": s.id,
            "category": s.category,
            "item_type": s.item_type,
            "quantity": s.quantity,
            "notes": s.notes,
            "status": s.status,
            "created_by_name": s.created_by_name,
            "completed_by_name": s.completed_by_name,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "completed_at": s.completed_at.isoformat() if s.completed_at else None
        } for s in (db.query(models.SupplyItem).filter(models.SupplyItem.job_card_id == job.id).all() if hasattr(models, "SupplyItem") else [])],
        "photo_count": len(job_photo_items(db, job)),
        "photos_archived": photos_archived,
        "photo_archives": [{
            "id": a.id,
            "photo_count": a.photo_count,
            "downloaded_by_name": a.downloaded_by_name,
            "downloaded_at_sast": sast_text(a.downloaded_at),
            "deleted_by_name": a.deleted_by_name,
            "deleted_at_sast": sast_text(a.deleted_at),
            "deleted_count": a.deleted_count,
        } for a in photo_archive_rows if a.deleted_at],
    }, job, stock_counts_exact(db, job.stock_number))

@app.post("/api/jobs/{job_id}/vehicle")
async def api_update_vehicle(job_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
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

PAINT_TEAMS = ("Reuben", "Jonas", "Ricardo", "Shoes (Bay 4)")
PAINT_TASK_WORDS = ("paint", "spray", "touch-up", "touch up", "touchup")

def is_paint_task(name: str) -> bool:
    n = (name or "").lower()
    return any(w in n for w in PAINT_TASK_WORDS)

def workshop_people(db: Session):
    return db.query(models.User).filter(
        models.User.role == "workshop", models.User.is_active == True
    ).order_by(models.User.full_name).all()

def apply_task_assignment(db, task, body, new_status, old_status, changer):
    """Who is doing the task. Required when a task moves into In Progress."""
    moving_in = new_status == "In Progress" and old_status != "In Progress"
    has_pick = "responsible_user_id" in body
    if not moving_in and not has_pick:
        return []
    paint = is_paint_task(task.task_name)
    rid = body.get("responsible_user_id")
    try:
        rid = int(rid) if rid not in (None, "") else None
    except (TypeError, ValueError):
        rid = None
    person = None
    if rid:
        person = db.query(models.User).filter(
            models.User.id == rid, models.User.role == "workshop", models.User.is_active == True
        ).first()
    if not person:
        raise HTTPException(status_code=400, detail="Choose who is responsible for this task (a workshop user) before it goes In Progress.")
    team = (body.get("paint_team") or "").strip()
    if paint and team not in PAINT_TEAMS:
        raise HTTPException(status_code=400, detail="Paint task: choose the paint team (" + ", ".join(PAINT_TEAMS) + ").")
    # Free text is shown in several older views that build HTML strings, so drop markup characters.
    assisting = "".join(ch for ch in str(body.get("assisting_names") or "") if ch not in "<>&\"'`").strip()[:200] or None
    task.responsible_user_id = person.id
    task.responsible_name = person.full_name
    task.assisting_names = assisting
    if paint:
        task.paint_team = team
    task.assigned_at = datetime.utcnow()
    task.assigned_by_name = changer
    bits = [f"responsible {person.full_name}"]
    if assisting:
        bits.append(f"assisting {assisting}")
    if paint:
        bits.append(f"paint team {team}")
    return bits

@app.get("/api/task-people")
async def api_task_people(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    """Names for the In Progress picker. Names only, no contact details."""
    return {
        "workshop": [{"id": u.id, "full_name": u.full_name} for u in workshop_people(db)],
        "paint_teams": list(PAINT_TEAMS),
    }

@app.post("/api/jobs/{job_id}/tasks/{task_id}/update")
async def api_update_task(job_id: int, task_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    try:
        body = await request.json()
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    assert_editable(db, job, body.get("user_id"))
    if job.status == "Pending Admin Approval":
        raise HTTPException(status_code=400, detail="Admin must approve this showroom job before work can start")

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

    if new_status == "Completed" and is_test_task(task.task_name):
        result = (task.test_result or body.get("test_result") or "").strip()
        note = (body.get("notes") if notes is not None else task.notes) or ""
        reference = (body.get("reference") or "").strip() or note.strip()
        if result not in ("Pass", "Fail", "Repaired"):
            raise HTTPException(status_code=400, detail=f"{task.task_name} needs a result: Pass, Fail or Repaired.")
        if not reference:
            raise HTTPException(status_code=400, detail=f"{task.task_name} needs a reference or note before it can be completed.")
        if result == "Fail" and not ((body.get("fail_list") or task.fail_list or "").strip()):
            raise HTTPException(status_code=400, detail=f"{task.task_name} failed. Add the fail list before completing.")
        task.test_result = result
        if reference and not task.notes:
            task.notes = reference

    if new_status == "Completed" and user_id:
        window = datetime.utcnow() - timedelta(seconds=60)
        recent = db.query(models.JobTask).filter(
            models.JobTask.job_card_id == job_id,
            models.JobTask.completed_by == user_id,
            models.JobTask.completed_at != None,
            models.JobTask.completed_at >= window,
        ).count()
        if recent >= 3:
            note = (body.get("bulk_note") or "").strip()
            if not note:
                raise HTTPException(status_code=400, detail="Bulk completion: more than 3 tasks in 60 seconds. Add a confirmation note.")
            db.add(models.IntegrityEvent(
                job_card_id=job.id,
                event_type="bulk",
                side=task.task_name,
                user_id=user_id,
                reason=note,
            ))
            log_audit(db, user_id, "Bulk completion", job.id, f"{task.task_name}. {note}")

    old_status = task.status

    assign_bits = apply_task_assignment(db, task, body, new_status, old_status, body.get("full_name") or user_name(db, user_id) or "Staff")

    if new_status:
        task.status = new_status
        if new_status == "Completed":
            task.completed_at = datetime.utcnow()
            task.completed_by = user_id
        elif new_status != "Completed":
            task.completed_at = None
            task.completed_by = None

    if notes is not None:
        if body.get("append_note") and str(notes).strip():
            stamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
            who = body.get("full_name") or user_name(db, user_id) or "Staff"
            line = f"{stamp} {who}: {str(notes).strip()}"
            task.notes = (task.notes + "\n" + line) if task.notes else line
        else:
            task.notes = notes

    changer = body.get("full_name") or user_name(db, user_id) or "Staff"
    task.last_updated_by_name = changer
    change_bits = []
    if new_status:
        change_bits.append(f"status {old_status} → {new_status}")
    if "task_location" in body:
        change_bits.append(f"location {task.task_location or '—'}")
        apply_job_location(db, job, task.task_location, changer, user_id)
    if "third_party_provider" in body:
        change_bits.append(f"3rd party {task.third_party_provider or '—'}")
        apply_job_location(db, job, task.task_location or ("3rd Party: " + (task.third_party_provider or "")), changer, user_id)
    if notes is not None:
        change_bits.append("note updated")
    change_bits.extend(assign_bits)
    if change_bits:
        add_update(
            db, job.id, "progress",
            f"{task.task_name}: " + "; ".join(change_bits),
            created_by_name=changer,
            created_by=user_id,
        )

    # If job was only Accepted, move to In Progress when first task is worked on
    if job.status == "Accepted by Workshop" and new_status in ("In Progress", "Completed", "Blocked"):
        job.status = "In Progress"

    db.commit()

    # Audit
    if user_id:
        log_audit(db, user_id, "Updated Task", job.id,
                  f"Task '{task.task_name}' → {new_status or old_status}" + (f" | Notes: {notes}" if notes else ""))

    # Work is done when every task except wash / clean is completed. Wash is after sign-off.
    all_tasks = db.query(models.JobTask).filter(models.JobTask.job_card_id == job_id).all()
    if work_is_done(all_tasks):
        if mark_work_complete(db, job, user_id):
            db.commit()

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
async def api_add_task(job_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
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
        needs_approval=True,
        last_updated_by_name=body.get("full_name")
    )
    db.add(task)
    if task.task_location:
        apply_job_location(db, job, task.task_location, body.get("full_name"), user_id)
    db.commit()
    db.refresh(task)
    if task.needs_approval:
        notify_role(db, "admin", f"EXTRA needs approval on {job_display_id(job)}: {task_name}", job.id)
        db.commit()

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
async def admin_users_page(request: Request, current_user: models.User = Depends(auth.get_current_active_user)):
    return render_template("admin_users.html", request=request, page_title="User Management")

@app.get("/admin/overrides", response_class=HTMLResponse)
async def overrides_page(request: Request, current_user: models.User = Depends(auth.get_current_active_user)):
    return render_template("overrides.html", request=request, page_title="Overrides")

@app.get("/api/admin/overrides")
async def api_overrides(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_admin(current_user)
    rows = db.query(models.IntegrityEvent).order_by(models.IntegrityEvent.timestamp.desc()).limit(400).all()
    out = []
    for e in rows:
        job = db.query(models.JobCard).filter(models.JobCard.id == e.job_card_id).first()
        out.append(with_display({
            "job_id": e.job_card_id,
            "job_number": job.job_number if job else "",
            "stock_number": job.stock_number if job else "",
            "event_type": e.event_type,
            "side": e.side,
            "who": user_name(db, e.user_id),
            "on_behalf_of": user_name(db, e.on_behalf_of),
            "reason": e.reason,
            "override": bool(e.override),
            "when": e.timestamp.isoformat() if e.timestamp else None,
        }, job, stock_counts_exact(db, job.stock_number) if job else {}))
    return {"events": out}

@app.get("/admin/third-parties", response_class=HTMLResponse)
async def admin_third_parties_page(request: Request, current_user: models.User = Depends(auth.get_current_active_user)):
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

@app.post("/api/admin/third-parties/{item_id}/delete")
async def api_admin_delete_third_party(item_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    if (current_user.role or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Only admin can delete 3rd parties")
    row = db.query(models.ThirdPartyCompany).filter(models.ThirdPartyCompany.id == item_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    name = row.name
    db.delete(row)
    db.commit()
    return {"success": True, "deleted": name}

@app.get("/api/admin/pending-extras")
async def api_admin_pending_extras(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_admin(current_user)
    from sqlalchemy import or_, and_
    tasks = db.query(models.JobTask).filter(
        or_(
            models.JobTask.needs_approval == True,
            and_(
                models.JobTask.is_custom == True,
                or_(models.JobTask.approved_by_name.is_(None), models.JobTask.approved_by_name == ""),
                or_(
                    models.JobTask.task_name.ilike("Extra:%"),
                    models.JobTask.task_name.ilike("Other:%"),
                    models.JobTask.task_name.ilike("Activity:%"),
                    models.JobTask.task_name.ilike("Parts:%"),
                    models.JobTask.task_name.ilike("3rd party:%"),
                ),
            ),
        )
    ).order_by(models.JobTask.id.desc()).all()
    out = []
    seen = set()
    for t in tasks:
        if getattr(t, "approved_by_name", None):
            continue
        job = db.query(models.JobCard).filter(models.JobCard.id == t.job_card_id).first()
        if not job:
            continue
        if job.status == "Delivered / Closed":
            continue
        key = (job.id, t.id)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "task_id": t.id,
            "job_id": job.id,
            "job_number": job.job_number,
            "stock_number": job.stock_number,
            "vehicle_description": job.vehicle_description,
            "year": job.year,
            "task_name": t.task_name,
            "description": t.description,
            "last_updated_by_name": t.last_updated_by_name or job.salesman_name
        })
    job_ids = list({row["job_id"] for row in out})
    job_map = {j.id: j for j in db.query(models.JobCard).filter(models.JobCard.id.in_(job_ids)).all()} if job_ids else {}
    counts = stock_repeat_counts(job_map.values())
    out = [with_display(row, job_map.get(row["job_id"]), counts) for row in out]
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
                "supplier_company": getattr(u, "supplier_company", None),
                "is_active": u.is_active,
                "yard_access": bool(getattr(u, "yard_access", False)),
                "has_yard_access": user_has_yard_access(u),
                "stock_manager": bool(getattr(u, "stock_manager", False)),
                "is_stock_manager": is_stock_manager(u),
                "created_at": u.created_at.isoformat() if u.created_at else None,
                "password_changed_at": u.password_changed_at.date().isoformat() if getattr(u, "password_changed_at", None) else None
            } for u in users
        ],
        "supplier_companies": list_supplier_companies(db),
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

    if role not in ("sales", "workshop", "accounts", "admin", "stock", "supplier", "marketing", "yard"):
        raise HTTPException(status_code=400, detail="Invalid role")
    company = (body.get("supplier_company") or "").strip() or None
    if role == "supplier" and not company:
        raise HTTPException(status_code=400, detail="Supplier must be allocated to a company")

    existing = db.query(models.User).filter(models.User.username == username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")

    yard_access = bool(body.get("yard_access"))
    user = models.User(
        username=username,
        full_name=full_name,
        hashed_password=auth.get_password_hash(password),
        must_change_password=True,
        role=role,
        supplier_company=company if role == "supplier" else None,
        yard_access=yard_access,
        is_active=True
    )
    db.add(user)
    if role == "supplier":
        ensure_supplier_company_listed(db, company)
    db.commit()
    db.refresh(user)
    if yard_access:
        log_audit(
            db,
            current_user.id,
            "Yard check access",
            None,
            f"Enabled yard check for user {user.id} on create",
        )

    return {
        "success": True,
        "user": {
            "id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "role": user.role,
            "supplier_company": user.supplier_company,
            "yard_access": bool(user.yard_access),
            "has_yard_access": user_has_yard_access(user),
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

@app.post("/api/admin/users/{user_id}/yard-access")
async def api_set_yard_access(user_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_admin(current_user)
    try:
        body = await request.json()
    except Exception:
        body = {}
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if "yard_access" in body:
        if type(body.get("yard_access")) is not bool:
            raise HTTPException(status_code=400, detail="yard_access must be true or false")
        new_val = body["yard_access"]
    else:
        new_val = not bool(user.yard_access)
    previous = bool(getattr(user, "yard_access", False))
    user.yard_access = new_val
    db.commit()
    if previous != bool(new_val):
        log_audit(
            db,
            current_user.id,
            "Yard check access",
            None,
            ("Enabled" if new_val else "Disabled") + f" yard check for user {user.id}",
        )
    return {
        "success": True,
        "yard_access": bool(user.yard_access),
        "has_yard_access": user_has_yard_access(user),
    }

@app.post("/api/admin/users/{user_id}/stock-manager")
async def api_set_stock_manager(user_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    """Admin grants or removes the stock-list permission (upload list, add/remove vehicles, photos, approve yard finds)."""
    require_admin(current_user)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if type(body.get("stock_manager")) is not bool:
        raise HTTPException(status_code=400, detail="stock_manager must be true or false")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if body["stock_manager"] and user.role in ("supplier", "yard"):
        raise HTTPException(status_code=400, detail="Suppliers and yard logins cannot manage the stock list")
    previous = bool(getattr(user, "stock_manager", False))
    user.stock_manager = body["stock_manager"]
    db.commit()
    if previous != body["stock_manager"]:
        log_audit(db, current_user.id, "Stock list access", None,
                  ("Enabled" if body["stock_manager"] else "Disabled") + f" stock list management for user {user.id}")
    return {"success": True, "stock_manager": bool(user.stock_manager), "is_stock_manager": is_stock_manager(user)}

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
    user.must_change_password = False
    db.commit()
    return {"success": True}

# ---------- READY FOR DELIVERY & CLOSE ----------

def is_showroom(job) -> bool:
    return (getattr(job, "job_purpose", None) or "sold").strip().lower() == "showroom"

@app.post("/api/jobs/{job_id}/ready")
async def api_mark_ready(job_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    try:
        body = await request.json()
    except:
        body = {}

    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if not is_showroom(job) and type_family(job.main_type) == "tanker" and not (job.empty_signed_workshop and job.empty_signed_sales):
        raise HTTPException(status_code=400, detail="Tanker empty check must be signed by workshop and sales before marking ready")
    if job.status not in ("PDI Completed", "Work Completed", "Ready for Delivery"):
        # Allow from Work Completed for now (PDI can be added later)
        if job.status != "Work Completed":
            raise HTTPException(status_code=400, detail=f"Cannot mark ready from status: {job.status}")

    user_id = body.get("user_id")
    party = body.get("party")  # "sales" or "workshop"
    override_user = None

    missing = parts_missing_order_numbers(db, job_id)
    if missing and party == "workshop":
        raise HTTPException(
            status_code=400,
            detail="Cannot close / mark ready. Add Chantelle order numbers for: " + ", ".join(p.description for p in missing)
        )
    open_tasks = open_blocking_tasks(job)
    if open_tasks:
        raise HTTPException(status_code=400, detail="Cannot mark ready. Open tasks: " + "; ".join(open_tasks))

    if is_showroom(job) and party == "sales":
        raise HTTPException(status_code=400, detail="Showroom jobs are signed off by workshop only")
    if party == "sales":
        assert_sales_owner(db, job, current_user, body, "sign this job off")
        override_user = require_other_side(db, job, user_id, job.ready_workshop_by, "ready for delivery", body)
        job.ready_sales = True
        job.ready_for_delivery_sales_at = datetime.utcnow()
        job.ready_sales_by = override_user.id if override_user else user_id
    elif party == "workshop":
        override_user = require_other_side(db, job, user_id, job.ready_sales_by, "ready for delivery", body)
        job.ready_workshop = True
        job.ready_for_delivery_workshop_at = datetime.utcnow()
        job.ready_workshop_by = override_user.id if override_user else user_id
        if is_showroom(job):
            job.ready_sales = True
            job.ready_for_delivery_sales_at = datetime.utcnow()
    else:
        raise HTTPException(status_code=400, detail="party must be 'sales' or 'workshop'")
    if override_user:
        record_override(db, job, user_id, override_user, (body.get("reason") or "").strip(), f"Ready {party}")

    if job.ready_sales and job.ready_workshop:
        job.status = "Ready for Delivery"

    db.commit()

    if user_id:
        log_audit(db, user_id, "Marked Ready for Delivery", job.id, f"Marked by {party}")
    if is_showroom(job) and party == "workshop":
        notify_role(db, "workshop", f"Showroom job {job_display_id(job)} signed off by workshop", job.id)
        notify_role(db, "admin", f"Showroom job {job_display_id(job)} signed off by workshop", job.id)
    elif job.ready_sales and job.ready_workshop:
        notify_signoff(db, job, f"{job_display_id(job)} is ready for delivery")
    elif party == "workshop" and not job.ready_sales:
        notify_salesman(db, job, f"Workshop marked {job_display_id(job)} ready — sales must mark ready")
    elif party == "sales" and not job.ready_workshop:
        notify_role(db, "workshop", f"Sales marked {job_display_id(job)} ready — workshop must mark ready", job.id)
    db.commit()

    return {
        "success": True,
        "ready_sales": job.ready_sales,
        "ready_workshop": job.ready_workshop,
        "status": job.status
    }

@app.post("/api/jobs/{job_id}/empty-sign")
async def api_empty_sign(job_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    try:
        body = await request.json()
    except Exception:
        body = {}
    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if is_showroom(job):
        raise HTTPException(status_code=400, detail="Showroom jobs do not need a tanker empty check")
    if type_family(job.main_type) != "tanker":
        raise HTTPException(status_code=400, detail="Empty check is only for tankers")
    if job.status in ("Delivered / Closed",):
        raise HTTPException(status_code=400, detail="Job already delivered")
    party = body.get("party") or ("workshop" if current_user.role == "workshop" else "sales" if current_user.role == "sales" else None)
    if current_user.role in ("admin", "accounts") and body.get("party"):
        party = body.get("party")
    if party not in ("workshop", "sales"):
        raise HTTPException(status_code=400, detail="Workshop or sales must sign the empty check")
    if party == "workshop":
        override_user = require_other_side(db, job, current_user.id, job.empty_signed_sales_by, "the tanker empty check", body)
        job.empty_signed_workshop = True
        job.empty_signed_workshop_by = override_user.id if override_user else current_user.id
        job.empty_signed_workshop_at = datetime.utcnow()
    else:
        assert_sales_owner(db, job, current_user, body, "sign the tanker empty check")
        override_user = require_other_side(db, job, current_user.id, job.empty_signed_workshop_by, "the tanker empty check", body)
        job.empty_signed_sales = True
        job.empty_signed_sales_by = override_user.id if override_user else current_user.id
        job.empty_signed_sales_at = datetime.utcnow()
    if override_user:
        record_override(db, job, current_user.id, override_user, (body.get("reason") or "").strip(), f"Empty check {party}")
    db.add(models.JobUpdate(
        job_card_id=job.id,
        category="empty_check",
        description=f"Tanker empty check signed by {party} — compartments and pipelines to APIs empty",
        created_by_name=current_user.full_name,
        created_by=current_user.id,
    ))
    log_audit(db, current_user.id, "Tanker empty check", job.id, party)
    if job.empty_signed_workshop and job.empty_signed_sales:
        notify_signoff(db, job, f"Tanker empty check complete on {job_display_id(job)} — can mark ready / deliver")
    elif party == "workshop":
        notify_salesman(db, job, f"Workshop signed tanker empty check on {job_display_id(job)} — sales must sign")
    else:
        notify_role(db, "workshop", f"Sales signed tanker empty check on {job_display_id(job)} — workshop must sign", job.id)
    db.commit()
    return {
        "success": True,
        "empty_signed_workshop": bool(job.empty_signed_workshop),
        "empty_signed_sales": bool(job.empty_signed_sales),
    }

@app.post("/api/jobs/{job_id}/close")
async def api_close_job(job_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    try:
        body = await request.json()
    except:
        body = {}

    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != "Ready for Delivery":
        raise HTTPException(status_code=400, detail="Job must be Ready for Delivery before closing")
    if not is_showroom(job) and type_family(job.main_type) == "tanker" and not (job.empty_signed_workshop and job.empty_signed_sales):
        raise HTTPException(status_code=400, detail="Tanker empty check must be signed by workshop and sales before delivery")
    missing = parts_missing_order_numbers(db, job_id)
    if missing:
        raise HTTPException(
            status_code=400,
            detail="Cannot close job. Parts without order numbers: " + ", ".join(p.description for p in missing) + ". Order number to be created by Chantelle."
        )

    user_id = body.get("user_id")
    blockers = archive_blockers(job)
    if blockers:
        raise HTTPException(status_code=400, detail="Cannot deliver. Outstanding: " + "; ".join(blockers))
    who = user_name(db, user_id) or body.get("full_name") or "Sales"
    archive_job(db, job, user_id, who, "Job delivered and archived")
    return {"success": True, "status": job.status, "archived": True}

@app.post("/api/jobs/{job_id}/reopen")
async def api_reopen_job(job_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_admin_only(current_user)
    try:
        body = await request.json()
    except Exception:
        body = {}
    reason = (body.get("reason") or "").strip()
    if len(reason) < 15:
        raise HTTPException(status_code=400, detail="Reopen needs a reason of at least 15 characters.")
    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    if not job or is_archived(job):
        raise HTTPException(status_code=404, detail="Open job not found")
    job.ready_sales = False
    job.ready_workshop = False
    job.ready_for_delivery_sales_at = None
    job.ready_for_delivery_workshop_at = None
    job.ready_sales_by = None
    job.ready_workshop_by = None
    if job.status == "Ready for Delivery":
        job.status = "Work Completed"
    db.add(models.JobUpdate(
        job_card_id=job.id,
        category="progress",
        description=f"Reopened {job_display_id(job)}",
        notes=reason,
        created_by_name=current_user.full_name,
        created_by=current_user.id,
    ))
    log_audit(db, current_user.id, "Reopened job", job.id, f"{job_display_id(job)} {reason}")
    db.add(models.IntegrityEvent(
        job_card_id=job.id,
        event_type="reopen",
        user_id=current_user.id,
        reason=reason,
    ))
    notify_role(db, "admin", f"{current_user.full_name} reopened {job_display_id(job)}: {reason}", job.id)
    db.query(models.Notification).filter(
        models.Notification.user_id == current_user.id,
        models.Notification.job_card_id == job.id,
        models.Notification.message.like(f"{current_user.full_name} reopened%")
    ).delete(synchronize_session=False)
    notify_salesman(db, job, f"{job_display_id(job)} was reopened: {reason}")
    db.commit()
    return {"success": True, "status": job.status}

# ---------- PDI DIGITAL FORMS ----------

from .pdi_config import get_pdi_for_type

@app.get("/jobs/{job_id}/pdi", response_class=HTMLResponse)
async def pdi_page(request: Request, job_id: int, current_user: models.User = Depends(auth.get_current_active_user)):
    return render_template("pdi.html", request=request, job_id=job_id, page_title="PDI Checklist")

@app.get("/api/jobs/{job_id}/pdi")
async def api_get_pdi(job_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Load existing PDI items or generate from template
    existing = db.query(models.PDIItem).filter(models.PDIItem.job_card_id == job_id).all()
    have = {(p.check_item or "").strip().lower() for p in existing}
    template = get_pdi_for_type(job.main_type)
    added_missing = False
    for section in template:
        for item in section["items"]:
            if (item["item"] or "").strip().lower() in have:
                continue
            if existing:
                db.add(models.PDIItem(
                    job_card_id=job_id,
                    section=section["section"],
                    item_number=item["num"],
                    check_item=item["item"],
                    acceptance_criteria=item.get("criteria"),
                    status=None,
                    notes=None
                ))
                added_missing = True
    if added_missing:
        db.commit()
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
        "job": with_display({
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
        }, job, stock_counts_exact(db, job.stock_number)),
        "items": items
    }

@app.post("/api/jobs/{job_id}/pdi/items/{item_id}")
async def api_update_pdi_item(job_id: int, item_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
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
            msg = f"PDI FAIL on {job_display_id(job)}: {item.check_item} — {note} (by {inspector})"
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
            for su in job_salesman_users(db, job, skip_roles=("admin", "accounts")):
                if job.created_by and su.id == job.created_by:
                    continue
                db.add(models.Notification(user_id=su.id, job_card_id=job.id, message=msg))

    db.commit()
    return {"success": True}

@app.post("/api/jobs/{job_id}/pdi/sign")
async def api_sign_pdi(job_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
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
    override_user = None
    if party == "workshop":
        override_user = require_other_side(db, job, user_id, job.pdi_signed_sales_by, "the PDI", body)
        job.pdi_signed_workshop = True
        job.pdi_signed_workshop_by = override_user.id if override_user else user_id
        job.pdi_signed_workshop_at = datetime.utcnow()
        if job.status == "Work Completed":
            job.status = "PDI in Progress"
    elif party == "sales":
        assert_sales_owner(db, job, current_user, body, "sign this PDI")
        override_user = require_other_side(db, job, user_id, job.pdi_signed_workshop_by, "the PDI", body)
        job.pdi_signed_sales = True
        job.pdi_signed_sales_by = override_user.id if override_user else user_id
        job.pdi_signed_sales_at = datetime.utcnow()
    else:
        raise HTTPException(status_code=400, detail="party must be workshop or sales")
    if override_user:
        record_override(db, job, user_id, override_user, (body.get("reason") or "").strip(), f"PDI {party}")

    if job.pdi_signed_workshop and job.pdi_signed_sales:
        job.status = "PDI Completed"
        job.pdi_completed_at = datetime.utcnow()

    db.commit()

    if user_id:
        log_audit(db, user_id, "Signed PDI", job.id, f"PDI signed by {party}")
    if job.pdi_signed_workshop and job.pdi_signed_sales:
        notify_signoff(db, job, f"PDI signed off on {job_display_id(job)} — mark ready for delivery")
    elif party == "workshop" and not job.pdi_signed_sales:
        notify_salesman(db, job, f"Workshop signed PDI on {job_display_id(job)} — sales must sign and mark ready")
        notify_role(db, "admin", f"Workshop signed PDI on {job_display_id(job)} — waiting for sales", job.id)
    elif party == "sales" and not job.pdi_signed_workshop:
        notify_role(db, "workshop", f"Sales signed PDI on {job_display_id(job)} — workshop must sign and mark ready", job.id)
    db.commit()

    return {
        "success": True,
        "pdi_signed_workshop": job.pdi_signed_workshop,
        "pdi_signed_sales": job.pdi_signed_sales,
        "status": job.status
    }

# ---------- DELETE JOB (Admin only) ----------

@app.post("/api/jobs/{job_id}/delete")
async def api_delete_job(job_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    raise HTTPException(status_code=400, detail="Delivered jobs are archived. They are not deleted.")

@app.get("/api/admin/closed-jobs.csv")
async def api_closed_jobs_csv(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_admin(current_user)
    import csv, io
    jobs = db.query(models.JobCard).filter(models.JobCard.archived_at != None).order_by(models.JobCard.archived_at.desc()).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["job_number", "stock_number", "vehicle", "year", "type", "client", "salesman", "status", "location", "created"])
    for j in jobs:
        w.writerow([j.job_number, j.stock_number, j.vehicle_description, j.year, f"{j.main_type}/{j.sub_type}", j.client_name, j.salesman_name, j.status, j.current_location or "", j.created_at.isoformat() if j.created_at else ""])
    stamp = datetime.now().strftime("%Y-%m-%d")
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=closed_jobs_{stamp}.csv"})

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

def list_supplier_companies(db):
    """Names offered on the Users form and anywhere PFT / FK are listed."""
    names = []
    seen = set()
    def add(n):
        n = (n or "").strip()
        if not n:
            return
        key = n.lower()
        if key in seen:
            return
        seen.add(key)
        names.append(n)
    for (company,) in db.query(models.User.supplier_company).filter(models.User.supplier_company.isnot(None)).all():
        add(company)
    add("PFT")
    add("FK Tanker Solutions")
    rows = db.query(models.ThirdPartyCompany).filter(models.ThirdPartyCompany.is_active == True).order_by(models.ThirdPartyCompany.name).all()
    for r in rows:
        add(r.name)
    return names

def ensure_supplier_company_listed(db, name: str):
    """Add a new supplier name to Pressure Test (same list as PFT / FK) if it is not already on the 3rd party list."""
    name = (name or "").strip()
    if not name:
        return
    rows = db.query(models.ThirdPartyCompany).all()
    for r in rows:
        existing = (r.name or "").strip()
        if existing.lower() == name.lower() or company_match(existing, name):
            if not r.is_active:
                r.is_active = True
            return
    db.add(models.ThirdPartyCompany(category="Pressure Test", name=name, is_active=True))

def allowed_third_party_map(db):
    allowed = {}
    for source in (THIRD_PARTY_SERVICES, grouped_third_parties(db)):
        for s in source:
            allowed.setdefault(s["service"], [])
            for p in s["providers"]:
                if p not in allowed[s["service"]]:
                    allowed[s["service"]].append(p)
    # Login company names (PFT, FK Tanker Solutions, and any new supplier) are valid Pressure Test providers.
    allowed.setdefault("Pressure Test", [])
    for n in list_supplier_companies(db):
        if n not in allowed["Pressure Test"]:
            allowed["Pressure Test"].append(n)
    return allowed

@app.get("/api/lists")
async def api_lists(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    return {
        "locations": LOCATIONS,
        "activity_types": ACTIVITY_TYPES,
        "extra_work_presets": EXTRA_WORK_PRESETS,
        "third_party_services": grouped_third_parties(db),
        "barrel_intervals": BARREL_INTERVALS,
        "third_party_categories": ["Barrel Test", "Pressure Test", "Calibration Test", "Roadworthy", "Auto Electrical", "Other"],
        "supply_categories": SUPPLY_CATEGORIES
    }

def normalize_board_location(raw: str):
    if not raw:
        return None
    s = " ".join(str(raw).strip().split())
    low = s.lower()
    if low.startswith("3rd") or low.startswith("third") or low.startswith("pft") or low.startswith("fk") or "testing station" in low:
        return "3rd Party"
    for loc in LOCATIONS:
        if loc.lower() == low:
            return loc
    for loc in LOCATIONS:
        if low in loc.lower() or loc.lower() in low:
            return loc
    return None

def add_update(db, job_id, category, description, notes=None, created_by_name=None, created_by=None):
    """One save is one line. Skip the same line if it was written in the last 20 seconds."""
    text = (description or "").strip()
    if not text:
        return None
    cutoff = datetime.utcnow() - timedelta(seconds=20)
    recent = db.query(models.JobUpdate).filter(
        models.JobUpdate.job_card_id == job_id,
        models.JobUpdate.category == category,
        models.JobUpdate.description == text,
        models.JobUpdate.created_at >= cutoff,
    ).first()
    if recent:
        return recent
    row = models.JobUpdate(
        job_card_id=job_id,
        category=category,
        description=text,
        notes=notes,
        created_by_name=created_by_name,
        created_by=created_by,
    )
    db.add(row)
    return row

def apply_job_location(db, job, raw_location, name=None, user_id=None):
    """Last recorded task/activity location becomes the dashboard location."""
    if not job or not raw_location:
        return
    display = " ".join(str(raw_location).strip().split())
    bucket = normalize_board_location(display)
    if bucket and bucket != "3rd Party":
        display = bucket
    elif bucket == "3rd Party" and not display.lower().startswith("3rd"):
        display = "3rd Party: " + display
    old = job.current_location
    if (old or "") == display:
        return
    job.current_location = display
    if bucket in WORKSHOP_BAYS and not job.workshop_entered_at:
        job.workshop_entered_at = datetime.utcnow()
    add_update(db, job.id, "location", f"Location changed: {old or '—'} → {display}", created_by_name=name or "Workshop", created_by=user_id)

def _board_bucket(board, raw):
    if raw in board:
        return raw
    mapped = normalize_board_location(raw)
    if mapped in board:
        return mapped
    return "Unspecified"

def _board_push(board, loc, item):
    bucket = _board_bucket(board, loc)
    key = (item.get("id"), item.get("label"), bucket)
    if any((x.get("id"), x.get("label"), bucket) == key for x in board[bucket]):
        return
    board[bucket].append(item)

@app.get("/api/locations-board")
async def api_locations_board(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    jobs = active_jobs(db).order_by(models.JobCard.created_at.desc()).all()
    board = {loc: [] for loc in LOCATIONS}
    board["Unspecified"] = []
    board["Delivered / Out"] = []
    loc_counts = stock_repeat_counts(jobs)
    for j in jobs:
        base = with_display({
            "id": j.id,
            "job_number": j.job_number,
            "stock_number": j.stock_number,
            "vehicle_description": j.vehicle_description,
            "year": j.year,
            "status": j.status,
            "priority": j.priority,
            "photo_url": job_photo_url(j, yard_photo_map_cached(db)),
            "job_purpose": getattr(j, "job_purpose", None) or "sold",
        }, j, loc_counts)
        vehicle = f"{job_display_label(j, loc_counts)} {j.vehicle_description} {j.year or ''}".strip()
        if (j.status or "") in CLOSED_STATUSES or (j.status or "").lower().startswith("delivered"):
            item = dict(base)
            item["label"] = vehicle
            _board_push(board, "Delivered / Out", item)
            continue
        # Current vehicle location
        item = dict(base)
        item["label"] = vehicle
        _board_push(board, j.current_location or "Unspecified", item)
        # Every work / prep task that has a location or 3rd party
        for t in (j.tasks or []):
            if (t.status or "") == "Completed":
                continue
            raw = t.task_location or (f"3rd Party: {t.third_party_provider}" if t.third_party_provider else None)
            if not raw:
                continue
            extra = t.task_name or "Task"
            if t.third_party_provider:
                extra += f" @ {t.third_party_provider}"
            if t.booked_date:
                extra += f" ({t.booked_date})"
            row = dict(base)
            row["label"] = f"{vehicle} — {extra}"
            row["task"] = extra
            _board_push(board, raw, row)
        # Outside / listed 3rd party bookings
        for b in (getattr(j, "third_party_bookings", None) or []):
            extra = f"{b.service} @ {b.provider}"
            if b.booked_date:
                extra += f" ({b.booked_date})"
            row = dict(base)
            row["label"] = f"{vehicle} — {extra}"
            row["task"] = extra
            _board_push(board, f"3rd Party: {b.provider}", row)
    return {"board": board}

@app.post("/api/jobs/{job_id}/location")
async def api_update_location(job_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
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
    if location == DELIVERED_LOCATION:
        blockers = archive_blockers(job)
        if blockers:
            raise HTTPException(status_code=400, detail="Cannot move to Out / Delivered. Outstanding: " + "; ".join(blockers))
        who = body.get("full_name") or user_name(db, body.get("user_id")) or "Staff"
        archive_job(db, job, body.get("user_id"), who, "Job delivered and archived")
        return {"success": True, "current_location": job.current_location, "archived": True}
    old = job.current_location
    job.current_location = location
    if location in WORKSHOP_BAYS and not job.workshop_entered_at:
        job.workshop_entered_at = datetime.utcnow()
    user_id = body.get("user_id")
    name = body.get("full_name") or "Staff"
    add_update(db, job.id, "location", f"Location changed: {old or '—'} → {location}", notes=body.get("notes"), created_by_name=name, created_by=user_id)
    db.commit()
    if user_id:
        log_audit(db, user_id, "Changed Location", job.id, f"Location changed: {old or '—'} → {location}")
    return {"success": True, "current_location": job.current_location}

def sast_today():
    return (datetime.utcnow() + timedelta(hours=2)).date()

def location_touched_today(db, job_id):
    start = datetime.combine(sast_today(), datetime.min.time()) - timedelta(hours=2)
    return db.query(models.JobUpdate).filter(
        models.JobUpdate.job_card_id == job_id,
        models.JobUpdate.category == "location",
        models.JobUpdate.created_at >= start
    ).first() is not None

@app.get("/api/workshop/morning-locations")
async def api_morning_locations(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    if current_user.role != "workshop":
        return {"date": str(sast_today()), "pending": [], "confirmed": 0, "total": 0, "locations": LOCATIONS}
    jobs = active_jobs(db).order_by(models.JobCard.stock_number).all()
    pending = []
    done = 0
    for j in jobs:
        item = {
            "id": j.id,
            "stock_number": j.stock_number,
            "vehicle_description": j.vehicle_description,
            "year": j.year,
            "current_location": j.current_location or "Unspecified",
            "confirmed_today": location_touched_today(db, j.id),
        }
        if item["confirmed_today"]:
            done += 1
        else:
            pending.append(item)
    if pending:
        already = db.query(models.Notification).filter(
            models.Notification.user_id == current_user.id,
            models.Notification.message.like("Morning location check%"),
            models.Notification.created_at >= datetime.combine(sast_today(), datetime.min.time()) - timedelta(hours=2)
        ).first()
        if not already:
            db.add(models.Notification(
                user_id=current_user.id,
                message=f"Morning location check — confirm where each WS is today ({len(pending)} still open)",
            ))
            db.commit()
    else:
        db.query(models.Notification).filter(
            models.Notification.user_id == current_user.id,
            models.Notification.message.like("Morning location check%")
        ).delete(synchronize_session=False)
        db.commit()
    return {"date": str(sast_today()), "pending": pending, "confirmed": done, "total": done + len(pending), "locations": LOCATIONS}

@app.post("/api/jobs/{job_id}/location-confirm")
async def api_confirm_location(job_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    if current_user.role != "workshop":
        raise HTTPException(status_code=403, detail="Workshop only")
    try:
        body = await request.json()
    except Exception:
        body = {}
    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    location = body.get("location") or job.current_location
    if location and location in LOCATIONS:
        job.current_location = location
    loc = job.current_location or "Unspecified"
    db.add(models.JobUpdate(
        job_card_id=job.id,
        category="location",
        description=f"Morning location confirmed: {loc}",
        notes="Daily morning check",
        created_by_name=current_user.full_name,
        created_by=current_user.id
    ))
    db.commit()
    log_audit(db, current_user.id, "Morning location confirmed", job.id, loc)
    return {"success": True, "current_location": loc}

@app.post("/api/jobs/{job_id}/updates")
async def api_add_update(job_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
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
        extra_task = models.JobTask(
            job_card_id=job.id,
            task_name=f"{prefix}: {description}",
            description=body.get("notes") or None,
            is_custom=True,
            needs_approval=True,
            status="Not Started",
            notes=body.get("notes") or None,
            last_updated_by_name=name
        )
        db.add(extra_task)
        notify_role(db, "admin", f"EXTRA needs approval on {job_display_id(job)}: {description}", job.id)
        notify_role(db, "accounts", f"EXTRA needs approval on {job_display_id(job)}: {description}", job.id)
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
async def print_job_page(request: Request, job_id: int, current_user: models.User = Depends(auth.get_current_active_user)):
    return render_template("print_job.html", request=request, job_id=job_id)


@app.post("/api/jobs/{job_id}/third-party")
async def api_add_third_party(job_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
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
    outside = bool(body.get("outside"))
    if not service or not provider:
        raise HTTPException(status_code=400, detail="Service and provider are required")
    if not outside:
        allowed = allowed_third_party_map(db)
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
    # System list bookings fill the matching Work / Prep task.
    # Outside companies get their own extra task so they stay separate.
    match_key = service.lower()
    matched = False
    if outside:
        db.add(models.JobTask(
            job_card_id=job.id,
            task_name=f"Outside 3rd party: {service} — {provider}",
            description=body.get("notes"),
            is_custom=True,
            needs_approval=False,
            status="Not Started",
            notes=body.get("notes"),
            task_location=f"3rd Party: {provider}",
            third_party_provider=provider,
            booked_date=booked_date,
            last_updated_by_name=name
        ))
        apply_job_location(db, job, f"3rd Party: {provider}", name, user_id)
        matched = True
    for t in job.tasks:
        if outside:
            break
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
async def print_pdi_page(request: Request, job_id: int, current_user: models.User = Depends(auth.get_current_active_user)):
    return render_template("print_pdi.html", request=request, job_id=job_id)

@app.get("/jobs/{job_id}/client-report", response_class=HTMLResponse)
async def client_report_page(request: Request, job_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    try:
        report = _client_report_payload(job_id, db)
    except HTTPException:
        report = None
    return render_template(
        "client_report.html",
        request=request,
        job_id=job_id,
        report_json=json.dumps(report) if report else "null",
    )

def _client_report_payload(job_id: int, db: Session, current_user=None):
    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    tasks = db.query(models.JobTask).filter(models.JobTask.job_card_id == job_id).all()
    parts = db.query(models.PartItem).filter(models.PartItem.job_card_id == job_id).all()
    report = build_report(job, tasks, parts)
    if not report.get("salesman_name") and current_user is not None:
        report["salesman_name"] = current_user.full_name
    report["whatsapp"] = whatsapp_text(report)
    report["job_id"] = job.id
    return report

@app.get("/api/jobs/{job_id}/client-report")
async def api_client_report(job_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    return _client_report_payload(job_id, db)

@app.get("/api/jobs/{job_id}/client-report.pdf")
async def api_client_report_pdf(job_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    report = _client_report_payload(job_id, db)
    pdf = render_pdf(report)
    filename = f"{report.get('stock_number') or 'job'}_progress_report.pdf".replace(" ", "_")
    return Response(content=pdf, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{filename}"'
    })

@app.post("/api/jobs/{job_id}/client-report.pdf")
async def api_client_report_pdf_selected(job_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    report = _client_report_payload(job_id, db)
    try:
        body = await request.json()
    except Exception:
        body = {}
    chosen = body.get("items")
    if isinstance(chosen, list) and chosen:
        cleaned = []
        for it in chosen:
            if not isinstance(it, dict):
                continue
            title = (it.get("title") or "").strip()
            if not title:
                continue
            cleaned.append({
                "title": title[:80],
                "status": (it.get("status") or "").strip() or "In progress",
                "note": (it.get("note") or "").strip(),
            })
        if cleaned:
            report["items"] = cleaned
            report["whatsapp"] = whatsapp_text(report)
    pdf = render_pdf(report)
    filename = f"{report.get('stock_number') or 'job'}_progress_report.pdf".replace(" ", "_")
    return Response(content=pdf, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{filename}"'
    })

@app.get("/jobs/{job_id}/print-work", response_class=HTMLResponse)
async def print_work_page(request: Request, job_id: int, current_user: models.User = Depends(auth.get_current_active_user)):
    return render_template("print_work.html", request=request, job_id=job_id)

def _signer(db, job, field, party):
    user_id = getattr(job, field, None)
    if user_id:
        return user_name(db, user_id)
    logs = db.query(models.AuditLog).filter(models.AuditLog.job_card_id == job.id, models.AuditLog.action == "Marked Ready for Delivery").order_by(models.AuditLog.timestamp.desc()).all()
    for log in logs:
        if party in (log.details or "").lower():
            return user_name(db, log.user_id)
    return None

@app.get("/api/jobs/{job_id}/pdf-work")
async def api_pdf_work(job_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    workshop = _signer(db, job, "ready_workshop_by", "workshop") if job.ready_workshop else None
    sales = _signer(db, job, "ready_sales_by", "sales") if job.ready_sales else None
    pdf = build_work_pdf(job, workshop, sales, display_label=job_display_label(job, stock_counts_exact(db, job.stock_number)))
    name = f"{job_display_id(job)} {job.vehicle_description or ''} completed work.pdf".replace("/", "-")
    return Response(content=pdf.read(), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})

@app.get("/api/jobs/{job_id}/pdf-pdi")
async def api_pdf_pdi(job_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    items = list(job.pdi_items or [])
    workshop = user_name(db, job.pdi_signed_workshop_by) if job.pdi_signed_workshop else None
    sales = user_name(db, job.pdi_signed_sales_by) if job.pdi_signed_sales else None
    pdf = build_pdi_pdf(job, items, workshop, sales, display_label=job_display_label(job, stock_counts_exact(db, job.stock_number)))
    name = f"{job_display_id(job)} {job.vehicle_description or ''} PDI.pdf".replace("/", "-")
    return Response(content=pdf.read(), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})

@app.post("/api/jobs/{job_id}/parts")
async def api_add_part(job_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
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
    notify_role(db, "workshop", f"Part to be ordered: {desc} on {job_display_id(job)}", job.id)
    db.commit()
    return {"success": True, "id": part.id}

@app.post("/api/jobs/{job_id}/supplies")
async def api_add_supply(job_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    body = await request.json()
    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    assert_editable(db, job, body.get("user_id"))
    cat = (body.get("category") or "").strip()
    typ = (body.get("item_type") or "").strip()
    if not cat or not typ:
        raise HTTPException(status_code=400, detail="Category and type are required")
    row = models.SupplyItem(
        job_card_id=job.id,
        category=cat,
        item_type=typ,
        quantity=(body.get("quantity") or "1").strip() or "1",
        notes=(body.get("notes") or "").strip() or None,
        status="Booked",
        created_by_name=body.get("full_name") or user_name(db, body.get("user_id"))
    )
    db.add(row)
    db.add(models.JobUpdate(
        job_card_id=job.id,
        category="parts",
        description=f"Supply booked: {cat} — {typ} x{row.quantity}",
        notes=row.notes,
        created_by_name=row.created_by_name,
        created_by=body.get("user_id")
    ))
    db.commit()
    return {"success": True}

@app.post("/api/jobs/{job_id}/supplies/{item_id}/status")
async def api_supply_status(job_id: int, item_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    body = await request.json()
    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    assert_editable(db, job, body.get("user_id"))
    row = db.query(models.SupplyItem).filter(models.SupplyItem.id == item_id, models.SupplyItem.job_card_id == job_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Supply not found")
    status = body.get("status") or "Booked"
    if status not in ("Booked", "Supplied", "Completed"):
        raise HTTPException(status_code=400, detail="Invalid status")
    row.status = status
    changer = body.get("full_name") or user_name(db, body.get("user_id"))
    if status == "Completed":
        row.completed_at = datetime.utcnow()
        row.completed_by_name = changer
    db.add(models.JobUpdate(
        job_card_id=job.id,
        category="parts",
        description=f"Supply {status}: {row.category} — {row.item_type}",
        created_by_name=changer,
        created_by=body.get("user_id")
    ))
    db.commit()
    return {"success": True}

@app.get("/api/supplies")
async def api_all_supplies(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    rows = db.query(models.SupplyItem).order_by(models.SupplyItem.id.desc()).all()
    out = []
    for s in rows:
        job = db.query(models.JobCard).filter(models.JobCard.id == s.job_card_id).first()
        if job and job.status == "Delivered / Closed":
            continue
        out.append({
            "id": s.id,
            "job_id": s.job_card_id,
            "stock_number": job.stock_number if job else "",
            "vehicle_description": job.vehicle_description if job else "",
            "category": s.category,
            "item_type": s.item_type,
            "quantity": s.quantity,
            "status": s.status,
            "created_by_name": s.created_by_name
        })
    return {"supplies": out}

@app.post("/api/jobs/{job_id}/parts/{part_id}/order-number")
async def api_set_part_order(job_id: int, part_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
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

def iso(v):
    return v.isoformat() if v else None

def build_snapshot(db):
    jobs_out = []
    for j in db.query(models.JobCard).order_by(models.JobCard.id.asc()).all():
        jobs_out.append({
            "job_number": j.job_number,
            "stock_number": j.stock_number,
            "vehicle_description": j.vehicle_description,
            "year": j.year,
            "main_type": j.main_type,
            "sub_type": j.sub_type,
            "vin_number": j.vin_number,
            "registration_number": j.registration_number,
            "client_name": j.client_name,
            "salesman_name": j.salesman_name,
            "quotation_invoice_number": getattr(j, "quotation_invoice_number", None),
            "priority": j.priority,
            "target_delivery_date": j.target_delivery_date,
            "current_location": j.current_location,
            "internal_notes": j.internal_notes,
            "other_instructions": j.other_instructions,
            "status": j.status,
            "current_activity": getattr(j, "current_activity", None),
            "current_activity_notes": getattr(j, "current_activity_notes", None),
            "current_activity_by": getattr(j, "current_activity_by", None),
            "pdi_signed_workshop": j.pdi_signed_workshop,
            "pdi_signed_sales": j.pdi_signed_sales,
            "ready_sales": j.ready_sales,
            "ready_workshop": j.ready_workshop,
            "delivered_at": iso(j.delivered_at),
            "archived_at": iso(getattr(j, "archived_at", None)),
            "archived_by": getattr(j, "archived_by", None),
            "archive_reason": getattr(j, "archive_reason", None),
            "created_at": iso(j.created_at),
            "accepted_at": iso(j.accepted_at),
            "tasks": [{
                "task_name": t.task_name, "description": t.description, "is_custom": t.is_custom,
                "status": t.status, "notes": t.notes, "task_location": getattr(t, "task_location", None),
                "third_party_provider": getattr(t, "third_party_provider", None),
                "booked_date": getattr(t, "booked_date", None),
                "test_result": getattr(t, "test_result", None),
                "fail_list": getattr(t, "fail_list", None),
            } for t in (j.tasks or [])],
            "pdi": [{
                "section": p.section, "item_number": p.item_number, "check_item": p.check_item,
                "acceptance_criteria": p.acceptance_criteria, "status": p.status, "notes": p.notes, "initials": p.initials
            } for p in (j.pdi_items or [])],
            "parts": [{
                "description": p.description, "order_number": p.order_number, "quantity": getattr(p, "quantity", None),
                "price": getattr(p, "price", None), "supplier_invoice": getattr(p, "supplier_invoice", None),
                "part_progress": getattr(p, "part_progress", None), "ordered_date": getattr(p, "ordered_date", None),
                "created_by_name": p.created_by_name
            } for p in (getattr(j, "parts", None) or [])],
            "supplies": [{
                "category": s.category, "item_type": s.item_type, "quantity": s.quantity, "notes": s.notes,
                "status": s.status, "created_by_name": s.created_by_name
            } for s in (getattr(j, "supplies", None) or [])],
            "updates": [{
                "category": u.category, "description": u.description, "notes": u.notes, "created_by_name": u.created_by_name, "created_at": iso(u.created_at)
            } for u in (j.updates or [])],
            "bookings": [{
                "service": b.service, "provider": b.provider, "booked_date": b.booked_date, "notes": b.notes, "created_by_name": b.created_by_name
            } for b in (getattr(j, "third_party_bookings", None) or [])],
            "supplier_updates": [{
                "company": s.company, "status": s.status, "work_doing": s.work_doing, "parts_needed": s.parts_needed,
                "note": s.note, "photo_path": getattr(s, "photo_path", None), "created_by_name": s.created_by_name
            } for s in db.query(models.SupplierUpdate).filter(models.SupplierUpdate.job_card_id == j.id).all()],
        })
    return {
        "saved_at": datetime.utcnow().isoformat(),
        "jobs": jobs_out,
        "stock_orders": [{
            "description": s.description, "quantity": s.quantity, "notes": s.notes, "status": s.status,
            "created_by_name": s.created_by_name
        } for s in db.query(models.WorkshopStockOrder).all()] if hasattr(models, "WorkshopStockOrder") else [],
        "third_party_companies": [{"category": c.category, "name": c.name} for c in db.query(models.ThirdPartyCompany).all()],
    }

@app.get("/api/admin/backup.db")
async def api_admin_backup_db(current_user: models.User = Depends(auth.get_current_active_user)):
    require_admin(current_user)
    path = SQLITE_FILE or "status_jobcard.db"
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Database file not found")
    stamp = datetime.now().strftime("%Y-%m-%d")
    return FileResponse(path, filename=f"status_jobcard_backup_{stamp}.db", media_type="application/octet-stream")

@app.get("/api/admin/backup-pack.zip")
async def api_admin_backup_pack(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_admin(current_user)
    import csv, io, zipfile, tempfile
    stamp = datetime.now().strftime("%Y-%m-%d")
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    tmp.close()
    snap = build_snapshot(db)
    with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as zf:
        path = SQLITE_FILE or "status_jobcard.db"
        if path and os.path.exists(path):
            zf.write(path, f"status_jobcard_backup_{stamp}.db")
        zf.writestr(f"full_restore_{stamp}.json", json.dumps(snap, ensure_ascii=False, indent=2))
        jobs = db.query(models.JobCard).order_by(models.JobCard.id.desc()).all()
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["job_number", "stock_number", "vehicle", "year", "type", "client", "salesman", "status", "location", "pdi_workshop", "pdi_sales"])
        for j in jobs:
            w.writerow([j.job_number, j.stock_number, j.vehicle_description, j.year, f"{j.main_type}/{j.sub_type}", j.client_name, j.salesman_name, j.status, j.current_location or "", j.pdi_signed_workshop, j.pdi_signed_sales])
        zf.writestr(f"jobcards_{stamp}.csv", buf.getvalue())
        buf = io.StringIO(); w = csv.writer(buf)
        w.writerow(["Job", "Stock", "Vehicle", "Section", "Item", "Status", "Notes"])
        for j in jobs:
            for p in (j.pdi_items or []):
                w.writerow([j.job_number, j.stock_number, j.vehicle_description, p.section, p.check_item, p.status, p.notes])
        zf.writestr(f"pdi_{stamp}.csv", buf.getvalue())
        buf = io.StringIO(); w = csv.writer(buf)
        w.writerow(["Job", "Stock", "Vehicle", "Task", "Custom", "Status", "Notes", "Location"])
        for j in jobs:
            for t in (j.tasks or []):
                w.writerow([j.job_number, j.stock_number, j.vehicle_description, t.task_name, t.is_custom, t.status, t.notes, getattr(t, "task_location", "")])
        zf.writestr(f"manual_tasks_{stamp}.csv", buf.getvalue())
        buf = io.StringIO(); w = csv.writer(buf)
        w.writerow(["Date", "Job", "Stock", "Vehicle", "Category", "Description", "Notes", "By"])
        for u in db.query(models.JobUpdate).all():
            job = db.query(models.JobCard).filter(models.JobCard.id == u.job_card_id).first()
            w.writerow([iso(u.created_at), job.job_number if job else "", job.stock_number if job else "", job.vehicle_description if job else "", u.category, u.description, u.notes, u.created_by_name])
        zf.writestr(f"workshop_extras_{stamp}.csv", buf.getvalue())
        up_root = globals().get("UPLOAD_DIR")
        if up_root and os.path.isdir(up_root):
            for root, _, files in os.walk(up_root):
                for fn in files:
                    full = os.path.join(root, fn)
                    rel = os.path.relpath(full, up_root)
                    zf.write(full, f"uploads/{rel}")
    return FileResponse(tmp.name, filename=f"STS_full_backup_{stamp}.zip", media_type="application/zip")

@app.post("/api/admin/restore")
async def api_admin_restore(file: UploadFile = File(...), db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_admin(current_user)
    raw = await file.read()
    data = None
    name = (file.filename or "").lower()
    if name.endswith(".json"):
        data = json.loads(raw.decode("utf-8"))
    elif name.endswith(".zip"):
        import zipfile, io
        zf = zipfile.ZipFile(io.BytesIO(raw))
        json_name = next((n for n in zf.namelist() if n.endswith(".json")), None)
        if not json_name:
            raise HTTPException(status_code=400, detail="Zip has no restore JSON")
        data = json.loads(zf.read(json_name).decode("utf-8"))
    else:
        raise HTTPException(status_code=400, detail="Upload the dated backup zip or full_restore JSON")
    added = 0
    skipped = 0
    for j in data.get("jobs") or []:
        exists = db.query(models.JobCard).filter(models.JobCard.job_number == j.get("job_number")).first()
        if exists:
            skipped += 1
            continue
        job = models.JobCard(
            job_number=j.get("job_number"),
            stock_number=j.get("stock_number") or "WS0000",
            vehicle_description=j.get("vehicle_description") or "",
            year=str(j.get("year") or ""),
            main_type=j.get("main_type") or "Other",
            sub_type=j.get("sub_type") or "Other",
            vin_number=j.get("vin_number"),
            registration_number=j.get("registration_number"),
            client_name=j.get("client_name") or "",
            salesman_name=j.get("salesman_name") or "",
            quotation_invoice_number=j.get("quotation_invoice_number"),
            priority=j.get("priority") or "Normal",
            target_delivery_date=j.get("target_delivery_date"),
            current_location=j.get("current_location"),
            internal_notes=j.get("internal_notes"),
            other_instructions=j.get("other_instructions"),
            status=j.get("status") or "Submitted to Workshop",
            current_activity=j.get("current_activity"),
            current_activity_notes=j.get("current_activity_notes"),
            current_activity_by=j.get("current_activity_by"),
            pdi_signed_workshop=bool(j.get("pdi_signed_workshop")),
            pdi_signed_sales=bool(j.get("pdi_signed_sales")),
            ready_sales=bool(j.get("ready_sales")),
            ready_workshop=bool(j.get("ready_workshop")),
        )
        db.add(job)
        db.flush()
        for t in j.get("tasks") or []:
            db.add(models.JobTask(job_card_id=job.id, task_name=t.get("task_name") or "Task", description=t.get("description"), is_custom=bool(t.get("is_custom")), status=t.get("status") or "Not Started", notes=t.get("notes"), task_location=t.get("task_location"), third_party_provider=t.get("third_party_provider"), booked_date=t.get("booked_date"), test_result=t.get("test_result"), fail_list=t.get("fail_list")))
        for p in j.get("pdi") or []:
            db.add(models.PDIItem(job_card_id=job.id, section=p.get("section"), item_number=p.get("item_number"), check_item=p.get("check_item") or "Item", acceptance_criteria=p.get("acceptance_criteria"), status=p.get("status"), notes=p.get("notes"), initials=p.get("initials")))
        for p in j.get("parts") or []:
            db.add(models.PartItem(job_card_id=job.id, description=p.get("description") or "Part", order_number=p.get("order_number"), quantity=p.get("quantity"), price=p.get("price"), supplier_invoice=p.get("supplier_invoice"), part_progress=p.get("part_progress"), ordered_date=p.get("ordered_date"), created_by_name=p.get("created_by_name")))
        for s in j.get("supplies") or []:
            db.add(models.SupplyItem(job_card_id=job.id, category=s.get("category") or "Other", item_type=s.get("item_type") or "Item", quantity=s.get("quantity") or "1", notes=s.get("notes"), status=s.get("status") or "Booked", created_by_name=s.get("created_by_name")))
        for u in j.get("updates") or []:
            db.add(models.JobUpdate(job_card_id=job.id, category=u.get("category") or "progress", description=u.get("description") or "Update", notes=u.get("notes"), created_by_name=u.get("created_by_name")))
        for b in j.get("bookings") or []:
            db.add(models.ThirdPartyBooking(job_card_id=job.id, service=b.get("service") or "Service", provider=b.get("provider") or "Provider", booked_date=b.get("booked_date"), notes=b.get("notes"), created_by_name=b.get("created_by_name")))
        for s in j.get("supplier_updates") or []:
            db.add(models.SupplierUpdate(job_card_id=job.id, company=s.get("company") or "Supplier", status=s.get("status") or "Booked", work_doing=s.get("work_doing"), parts_needed=s.get("parts_needed"), note=s.get("note"), photo_path=s.get("photo_path"), created_by_name=s.get("created_by_name")))
        added += 1
    db.commit()
    return {"success": True, "restored": added, "skipped_already_on_app": skipped}

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
    return Response(content=buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=jobcards_{datetime.now().strftime('%Y-%m-%d')}.csv"})

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
        headers={"Content-Disposition": f"attachment; filename=workshop_extras_{datetime.now().strftime('%Y-%m-%d')}.csv"}
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
        headers={"Content-Disposition": f"attachment; filename=parts_{datetime.now().strftime('%Y-%m-%d')}.csv"}
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
        headers={"Content-Disposition": f"attachment; filename=manual_tasks_{datetime.now().strftime('%Y-%m-%d')}.csv"}
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
async def api_workshop_bookings(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
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
            "label": f"{job_display_id(job)} {job.vehicle_description or ''} {job.year or ''}".strip(),
            "_job": job,
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
            "label": f"{job_display_id(job)} {job.vehicle_description or ''} {job.year or ''}".strip(),
            "_job": job,
        })
    booking_jobs = [row.pop("_job") for row in out]
    counts = stock_repeat_counts(booking_jobs)
    decorated = []
    for row, job in zip(out, booking_jobs):
        row = with_display(row, job, counts)
        row["label"] = f"{job_display_label(job, counts)} {job.vehicle_description or ''} {job.year or ''}".strip()
        decorated.append(row)
    out = decorated
    out.sort(key=lambda x: (x.get("booked_date") or "9999", x.get("stock_number") or ""))
    return {"bookings": out}

def unread_count(db, user_id):
    return db.query(models.Notification).filter(models.Notification.user_id == user_id, models.Notification.is_read == False).count()

def send_web_push(db, user_ids, title, body, url="/dashboard"):
    if not user_ids:
        return
    try:
        from pywebpush import webpush, WebPushException
        from .vapid import VAPID_PRIVATE_KEY, VAPID_EMAIL, PUSH_ENABLED
    except Exception:
        return
    if not PUSH_ENABLED or not VAPID_PRIVATE_KEY:
        return
    subs = db.query(models.PushSubscription).filter(models.PushSubscription.user_id.in_(list(set(user_ids)))).all()
    for s in subs:
        payload = json.dumps({"title": title, "body": body, "url": url, "unread": unread_count(db, s.user_id)})
        try:
            webpush(
                subscription_info={"endpoint": s.endpoint, "keys": {"p256dh": s.p256dh, "auth": s.auth}},
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": VAPID_EMAIL},
            )
        except Exception:
            try:
                db.delete(s)
            except Exception:
                pass

def notify_named_users(db, names, message, job_id=None, link="/stock"):
    if not names:
        return
    wanted = [n.strip().lower() for n in names if n]
    users = db.query(models.User).filter(models.User.is_active == True).all()
    ids = []
    for u in users:
        blob = f"{u.username or ''} {u.full_name or ''}".lower()
        if any(n in blob for n in wanted):
            db.add(models.Notification(user_id=u.id, job_card_id=job_id, message=message))
            ids.append(u.id)
    send_web_push(db, ids, "Status Job Cards", message, link)

def notify_role(db, role, message, job_id=None):
    users = db.query(models.User).filter(models.User.role == role, models.User.is_active == True).all()
    ids = []
    for u in users:
        db.add(models.Notification(user_id=u.id, job_card_id=job_id, message=message))
        ids.append(u.id)
    send_web_push(db, ids, "Status Job Cards", message, f"/jobs/{job_id}" if job_id else "/dashboard")

def notify_salesman(db, job, message, skip_roles=()):
    users = job_salesman_users(db, job, skip_roles)
    ids = []
    for u in users:
        db.add(models.Notification(user_id=u.id, job_card_id=job.id, message=message))
        ids.append(u.id)
    send_web_push(db, ids, "Status Job Cards", message, f"/jobs/{job.id}")

def is_delivery_wash(name: str) -> bool:
    n = (name or "").lower()
    return "wash" in n

def work_tasks(tasks):
    return [t for t in (tasks or []) if not is_delivery_wash(getattr(t, "task_name", "") or "")]

def mark_work_complete(db, job, user_id=None):
    if job.status in ("Work Completed", "PDI in Progress", "PDI Completed", "Ready for Delivery", "Delivered / Closed", "Pending Admin Approval"):
        return False
    job.status = "Work Completed"
    job.work_completed_at = datetime.utcnow()
    if user_id:
        log_audit(db, user_id, "Work Completed", job.id, f"Work tasks done on {job_display_id(job)}. Wash is only at collection")
    if is_showroom(job):
        notify_signoff(db, job, f"Showroom work completed on {job_display_id(job)} — workshop mark ready. No sales sign-off, PDI or empty check")
    else:
        notify_signoff(db, job, f"Work completed on {job_display_id(job)} — sign PDI and mark ready. Wash bay is only before the client collects")
        if type_family(job.main_type) == "tanker":
            notify_signoff(db, job, f"TANKER EMPTY CHECK: {job_display_id(job)} — confirm compartments and pipelines to APIs are empty before delivery")
    return True

def work_is_done(tasks):
    real = work_tasks(tasks)
    return bool(real) and all((t.status or "") == "Completed" for t in real)

def notify_signoff(db, job, message):
    # Admin/accounts already get this message below; skip them here so nobody gets it twice.
    notify_salesman(db, job, message, skip_roles=("admin", "accounts"))
    notify_role(db, "workshop", message, job.id)
    notify_role(db, "admin", message, job.id)
    notify_role(db, "accounts", message, job.id)

@app.post("/api/jobs/{job_id}/request-update")
async def api_request_update(job_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    body = await request.json()
    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status == "Delivered / Closed":
        raise HTTPException(status_code=400, detail="Job is already delivered")
    who = body.get("full_name") or user_name(db, body.get("user_id")) or "Sales"
    note = (body.get("note") or "").strip()
    job.update_requested_at = datetime.utcnow()
    job.update_requested_by = who
    job.update_request_note = note or None
    msg = f"UPDATE REQUEST: {job_display_id(job)} {job.vehicle_description} — {who} needs a workshop update"
    if note:
        msg += f" ({note})"
    notify_role(db, "workshop", msg, job.id)
    notify_role(db, "admin", msg, job.id)
    notify_role(db, "accounts", msg, job.id)
    db.add(models.JobUpdate(
        job_card_id=job.id,
        category="progress",
        description=f"Sales requested an update" + (f": {note}" if note else ""),
        created_by_name=who,
        created_by=body.get("user_id")
    ))
    db.commit()
    return {"success": True}

@app.post("/api/jobs/{job_id}/clear-update-request")
async def api_clear_update_request(job_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    body = await request.json()
    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    who = body.get("full_name") or user_name(db, body.get("user_id")) or "Workshop"
    job.update_requested_at = None
    job.update_requested_by = None
    job.update_request_note = None
    db.add(models.JobUpdate(
        job_card_id=job.id,
        category="progress",
        description="Workshop responded to sales update request",
        created_by_name=who,
        created_by=body.get("user_id")
    ))
    db.commit()
    return {"success": True}

@app.get("/api/update-requests")
async def api_update_requests(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    jobs = active_jobs(db).filter(models.JobCard.update_requested_at != None).order_by(models.JobCard.update_requested_at.desc()).all()
    return {"requests": [{
        "id": j.id,
        "stock_number": j.stock_number,
        "vehicle_description": j.vehicle_description,
        "year": j.year,
        "status": j.status,
        "requested_by": j.update_requested_by,
        "requested_at": j.update_requested_at.isoformat() if j.update_requested_at else None,
        "note": j.update_request_note
    } for j in jobs if j.status != "Delivered / Closed"]}

def stock_row(s):
    return {
        "id": s.id,
        "description": s.description,
        "quantity": s.quantity,
        "notes": s.notes,
        "status": s.status,
        "created_by_name": s.created_by_name,
        "ordered_date": s.ordered_date,
        "supplier_invoice": s.supplier_invoice,
        "stock_received_by": s.stock_received_by,
        "stock_received_at": s.stock_received_at.isoformat() if s.stock_received_at else None,
        "workshop_received_by": s.workshop_received_by,
        "workshop_received_at": s.workshop_received_at.isoformat() if s.workshop_received_at else None,
        "last_updated_by": s.last_updated_by,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "closed": s.status == "Closed",
        "update_requested_at": s.update_requested_at.isoformat() if getattr(s, "update_requested_at", None) else None,
        "update_requested_by": getattr(s, "update_requested_by", None),
        "update_request_note": getattr(s, "update_request_note", None),
    }

def section_label(cat):
    c = (cat or "").lower()
    if c in ("parts",):
        return "Parts"
    if c in ("activity", "location", "progress", "extra_work"):
        return "Work / Prep & activity"
    if c in ("third_party",):
        return "3rd party"
    if c in ("pdi",):
        return "PDI"
    if c in ("supplies", "supply"):
        return "Hoses / supplies"
    return (cat or "Other").replace("_", " ").title()

@app.get("/api/admin/workshop-counts")
async def api_workshop_counts(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    if current_user.role != "admin" or (current_user.full_name or "").strip().lower() != "sebastian van biljon":
        raise HTTPException(status_code=403, detail="Only Sebastian can view workshop counts")
    workshop = db.query(models.User).filter(models.User.role == "workshop", models.User.is_active == True).all()
    tallies = {u.full_name: 0 for u in workshop}
    for u in db.query(models.JobUpdate).all():
        who = (u.created_by_name or "").strip()
        if who in tallies:
            tallies[who] += 1
    rows = [{"name": name, "total": total} for name, total in tallies.items()]
    rows.sort(key=lambda x: -x["total"])
    return {"workshop": rows}

@app.get("/api/admin/sales-counts")
async def api_sales_counts(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    if current_user.role != "admin" or (current_user.full_name or "").strip().lower() != "sebastian van biljon":
        raise HTTPException(status_code=403, detail="Only Sebastian can view sales counts")
    sales = db.query(models.User).filter(models.User.role == "sales", models.User.is_active == True).all()
    names = [u.full_name for u in sales]
    sold = {n: {"booked": 0, "open": 0, "delivered": 0} for n in names}
    showroom = {"booked": 0, "open": 0, "delivered": 0, "by": {}}
    jobs = db.query(models.JobCard).all()
    for j in jobs:
        purpose = (getattr(j, "job_purpose", None) or "sold").strip().lower()
        closed = j.status in CLOSED_STATUSES
        if purpose == "showroom":
            showroom["booked"] += 1
            showroom["delivered" if closed else "open"] += 1
            who = (j.salesman_name or "Workshop").strip() or "Workshop"
            slot = showroom["by"].setdefault(who, {"booked": 0, "open": 0})
            slot["booked"] += 1
            if not closed:
                slot["open"] += 1
            continue
        who = (j.salesman_name or "").strip()
        if who not in sold:
            sold[who or "Unassigned"] = {"booked": 0, "open": 0, "delivered": 0}
            who = who or "Unassigned"
        sold[who]["booked"] += 1
        sold[who]["delivered" if closed else "open"] += 1
    sold_rows = [{"name": n, **v} for n, v in sold.items()]
    sold_rows.sort(key=lambda x: -x["booked"])
    show_rows = [{"name": n, **v} for n, v in showroom["by"].items()]
    show_rows.sort(key=lambda x: -x["booked"])
    return {
        "sold": sold_rows,
        "showroom_booked": showroom["booked"],
        "showroom_open": showroom["open"],
        "showroom_delivered": showroom["delivered"],
        "showroom": show_rows,
    }

def company_match(provider, company):
    if not provider or not company:
        return False
    a = " ".join((provider or "").lower().replace("/", " ").replace("-", " ").split())
    b = " ".join((company or "").lower().replace("/", " ").replace("-", " ").split())
    if not a or not b or a in ("3rd party", "third party", "other"):
        return False
    if a == b:
        return True
    at = set(a.split())
    bt = set(b.split())
    if at & bt and (len(a) >= 2 and len(b) >= 2):
        # shared token like FK / PFT, not generic words
        generic = {"test", "the", "and", "tanker", "solutions", "station", "party", "3rd"}
        return bool((at & bt) - generic)
    return b in a or a in b

def sup_row(s, job=None):
    return {
        "id": s.id,
        "job_id": s.job_card_id,
        "stock_number": job.stock_number if job else None,
        "vehicle_description": job.vehicle_description if job else None,
        "year": job.year if job else None,
        "company": s.company,
        "status": s.status,
        "work_doing": s.work_doing,
        "parts_needed": s.parts_needed,
        "note": s.note,
        "photo_path": s.photo_path,
        "workshop_parts_decision": s.workshop_parts_decision,
        "workshop_parts_note": s.workshop_parts_note,
        "created_by_name": s.created_by_name,
        "created_at": s.created_at.isoformat() if s.created_at else None
    }

@app.get("/api/supplier/jobs")
async def api_supplier_jobs(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    if current_user.role != "supplier":
        raise HTTPException(status_code=403, detail="Supplier login only")
    company = (current_user.supplier_company or "").strip()
    if not company:
        return {"company": "", "jobs": []}
    jobs = active_jobs(db).order_by(models.JobCard.created_at.desc()).all()
    open_jobs = []
    closed_jobs = []
    for job in jobs:
        if not job_allocated_to_company(job, company):
            continue
        tasks = [t for t in (job.tasks or []) if company_match(getattr(t, "third_party_provider", None), company)]
        bookings = [b for b in (getattr(job, "third_party_bookings", None) or []) if company_match(getattr(b, "provider", None), company)]
        if not tasks and not bookings:
            continue
        latest = db.query(models.SupplierUpdate).filter(models.SupplierUpdate.job_card_id == job.id, models.SupplierUpdate.company == company).order_by(models.SupplierUpdate.created_at.desc()).first()
        task_done = bool(tasks) and all((t.status or "") == "Completed" for t in tasks)
        closed = (latest and latest.status == "Completed") or task_done
        row = {
            "id": job.id,
            "stock_number": job.stock_number,
            "vehicle_description": job.vehicle_description,
            "year": job.year,
            "service": (tasks[0].task_name if tasks else bookings[0].service),
            "booked_date": (getattr(tasks[0], "booked_date", None) if tasks else bookings[0].booked_date),
            "latest_status": "Completed" if closed else (latest.status if latest else "Booked"),
            "latest_work": latest.work_doing if latest else None,
            "closed": closed,
        }
        (closed_jobs if closed else open_jobs).append(row)
    return {"company": company, "jobs": open_jobs, "closed_jobs": closed_jobs}

@app.post("/api/supplier/jobs/{job_id}/update")
async def api_supplier_update(
    job_id: int,
    status_val: str = Form("Booked"),
    work_doing: str = Form(""),
    parts_needed: str = Form(""),
    note: str = Form(""),
    photo: UploadFile = File(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_active_user)
):
    if current_user.role != "supplier":
        raise HTTPException(status_code=403, detail="Supplier login only")
    company = (current_user.supplier_company or "").strip()
    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    allowed = any(company_match(getattr(t, "third_party_provider", None), company) for t in (job.tasks or []))
    allowed = allowed or any(company_match(getattr(b, "provider", None), company) for b in (getattr(job, "third_party_bookings", None) or []))
    if not allowed:
        raise HTTPException(status_code=403, detail="This job is not booked to your company")
    if status_val not in ("Booked", "In progress", "Waiting parts", "Completed"):
        raise HTTPException(status_code=400, detail="Invalid status")
    photo_path = None
    if photo and photo.filename:
        ext = os.path.splitext(photo.filename)[1].lower()
        if ext not in (".jpg", ".jpeg", ".png", ".webp", ".heic"):
            raise HTTPException(status_code=400, detail="Photo must be jpg, png or heic")
        fname = f"{job_display_id(job)}_{uuid.uuid4().hex[:8]}{ext}"
        dest = os.path.join(UPLOAD_DIR, "supplier", fname)
        with open(dest, "wb") as f:
            f.write(await photo.read())
        photo_path = "/uploads/supplier/" + fname
    row = models.SupplierUpdate(
        job_card_id=job.id,
        company=company,
        status=status_val,
        work_doing=(work_doing or "").strip() or None,
        parts_needed=(parts_needed or "").strip() or None,
        note=(note or "").strip() or None,
        photo_path=photo_path,
        created_by_name=current_user.full_name,
        created_by=current_user.id
    )
    db.add(row)

    stamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    who = current_user.full_name or company
    note_bits = []
    if row.work_doing:
        note_bits.append(row.work_doing)
    if row.note:
        note_bits.append(row.note)
    if row.parts_needed:
        note_bits.append("Parts noted: " + row.parts_needed)
    if photo_path:
        note_bits.append("Photo uploaded")
    line = f"{stamp} {who} ({company}): {status_val}" + ((" — " + " | ".join(note_bits)) if note_bits else "")

    task_status_map = {
        "Booked": "Not Started",
        "In progress": "In Progress",
        "Waiting parts": "Blocked",
        "Completed": "Completed",
    }
    new_task_status = task_status_map.get(status_val)
    matched_tasks = [t for t in (job.tasks or []) if company_match(getattr(t, "third_party_provider", None), company)]
    if not matched_tasks:
        # booking exists without a task — attach to any 3rd-party task name that matches the booking service
        bookings = [b for b in (getattr(job, "third_party_bookings", None) or []) if company_match(getattr(b, "provider", None), company)]
        if bookings:
            service = (bookings[0].service or "").lower()
            for t in (job.tasks or []):
                name = (t.task_name or "").lower()
                if service and service in name:
                    matched_tasks.append(t)
                    t.third_party_provider = t.third_party_provider or company
    for t in matched_tasks:
        if new_task_status:
            t.status = new_task_status
            t.last_updated_by_name = who
            if new_task_status == "Completed":
                t.completed_at = datetime.utcnow()
                t.completed_by = current_user.id
                if "roadworthy" in (t.task_name or "").lower() and not t.test_result:
                    t.test_result = "Pass"
            else:
                t.completed_at = None
                t.completed_by = None
        t.notes = (t.notes + "\n" + line) if t.notes else line
        t.task_location = f"3rd Party: {company}"
        row.task_id = t.id
    if matched_tasks:
        apply_job_location(db, job, f"3rd Party: {company}", who, current_user.id)
    db.add(models.JobUpdate(
        job_card_id=job.id,
        category="3rd party",
        description=f"{company}: {status_val}" + ((" — " + (row.work_doing or row.note or "")) if (row.work_doing or row.note) else ""),
        created_by_name=who,
        created_by=current_user.id
    ))
    if job.status == "Accepted by Workshop" and status_val in ("In progress", "Waiting parts", "Completed"):
        job.status = "In Progress"
    if status_val == "Completed":
        all_tasks = db.query(models.JobTask).filter(models.JobTask.job_card_id == job.id).all()
        if work_is_done(all_tasks):
            mark_work_complete(db, job, current_user.id)

    msg = f"SUPPLIER {company} on {job_display_id(job)}: {status_val}"
    if row.parts_needed:
        msg += " — parts needed (workshop note only)"
    if photo_path:
        msg += " — job card photo uploaded"
    if status_val == "Completed":
        msg += " — job card task marked complete"
    notify_role(db, "workshop", msg, job.id)
    notify_role(db, "admin", msg, job.id)
    notify_role(db, "sales", msg, job.id)
    log_audit(db, current_user.id, "Supplier update", job.id, msg)
    db.commit()
    return {"success": True, "closed": status_val == "Completed"}

@app.get("/api/supplier-updates")
async def api_all_supplier_updates(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    if current_user.role not in ("workshop", "admin", "accounts"):
        raise HTTPException(status_code=403, detail="Workshop and admin only")
    rows = db.query(models.SupplierUpdate).order_by(models.SupplierUpdate.created_at.desc()).limit(80).all()
    out = []
    for s in rows:
        job = db.query(models.JobCard).filter(models.JobCard.id == s.job_card_id).first()
        out.append(sup_row(s, job))
    return {"updates": out}

@app.post("/api/supplier-updates/{upd_id}/workshop")
async def api_supplier_workshop_reply(upd_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    if current_user.role not in ("workshop", "admin", "accounts"):
        raise HTTPException(status_code=403, detail="Workshop and admin only")
    row = db.query(models.SupplierUpdate).filter(models.SupplierUpdate.id == upd_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Update not found")
    body = await request.json()
    decision = body.get("workshop_parts_decision")
    if decision not in ("workshop_assist", "supplier_supply"):
        raise HTTPException(status_code=400, detail="Choose workshop assist or supplier must supply")
    row.workshop_parts_decision = decision
    row.workshop_parts_note = (body.get("workshop_parts_note") or "").strip() or None
    db.commit()
    return {"success": True}

@app.get("/api/stock-orders")
async def api_stock_orders(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    rows = db.query(models.WorkshopStockOrder).order_by(models.WorkshopStockOrder.id.desc()).all()
    return {"orders": [stock_row(s) for s in rows]}

@app.post("/api/stock-orders")
async def api_add_stock_order(request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    body = await request.json()
    role = (body.get("role") or "").lower()
    if role not in ("stock", "admin", "accounts"):
        raise HTTPException(status_code=403, detail="Only the stock controller can add keep-on-hand items")
    desc = (body.get("description") or "").strip()
    if not desc:
        raise HTTPException(status_code=400, detail="Description is required")
    who = body.get("full_name") or user_name(db, body.get("user_id")) or "Stock"
    row = models.WorkshopStockOrder(
        description=desc,
        quantity=(body.get("quantity") or "1").strip() or "1",
        notes=(body.get("notes") or "").strip() or None,
        status="To be ordered",
        created_by_name=who,
        created_by=body.get("user_id"),
        last_updated_by=who
    )
    db.add(row)
    db.flush()
    msg = f"WORKSHOP STOCK TO ORDER: {row.description} x{row.quantity}"
    notify_role(db, "workshop", msg)
    notify_role(db, "admin", msg)
    db.commit()
    return {"success": True, "id": row.id}

@app.post("/api/stock-orders/{item_id}/status")
async def api_stock_status(item_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    body = await request.json()
    role = (body.get("role") or "").lower()
    if role not in ("stock", "workshop", "admin", "accounts"):
        raise HTTPException(status_code=403, detail="Not allowed")
    row = db.query(models.WorkshopStockOrder).filter(models.WorkshopStockOrder.id == item_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Item not found")
    if row.status == "Closed":
        raise HTTPException(status_code=400, detail="Already closed")
    status = body.get("status") or row.status
    if status not in ("To be ordered", "Ordered", "Waiting for delivery", "Received"):
        raise HTTPException(status_code=400, detail="Invalid status")
    who = body.get("full_name") or user_name(db, body.get("user_id")) or "Staff"
    row.status = status
    row.last_updated_by = who
    if body.get("ordered_date"):
        row.ordered_date = body.get("ordered_date")
    if body.get("supplier_invoice") is not None:
        row.supplier_invoice = (body.get("supplier_invoice") or "").strip() or None
    if role == "workshop" or (who or "").lower().find("louis") >= 0:
        row.update_requested_at = None
        row.update_requested_by = None
        row.update_request_note = None
    msg = f"Workshop stock {status}: {row.description} x{row.quantity} — {who}"
    notify_role(db, "stock", msg)
    notify_role(db, "workshop", msg)
    notify_role(db, "admin", msg)
    db.commit()
    return {"success": True}

@app.post("/api/stock-orders/{item_id}/request-update")
async def api_stock_request_update(item_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    body = await request.json()
    role = (body.get("role") or "").lower()
    if role not in ("admin", "accounts", "stock"):
        raise HTTPException(status_code=403, detail="Admin / stock can request an update from Louis")
    row = db.query(models.WorkshopStockOrder).filter(models.WorkshopStockOrder.id == item_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Item not found")
    if row.status == "Closed":
        raise HTTPException(status_code=400, detail="Already closed")
    who = body.get("full_name") or user_name(db, body.get("user_id")) or "Admin"
    note = (body.get("note") or "").strip()
    row.update_requested_at = datetime.utcnow()
    row.update_requested_by = who
    row.update_request_note = note or None
    msg = f"STOCK UPDATE REQUEST for Louis: {row.description} x{row.quantity} — {who}"
    if note:
        msg += f" ({note})"
    notify_named_users(db, ["louis", "louis koekemoer"], msg, link="/stock")
    notify_role(db, "workshop", msg)
    notify_role(db, "admin", msg)
    db.commit()
    return {"success": True}

@app.post("/api/stock-orders/{item_id}/clear-update-request")
async def api_stock_clear_update(item_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    body = await request.json()
    row = db.query(models.WorkshopStockOrder).filter(models.WorkshopStockOrder.id == item_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Item not found")
    who = body.get("full_name") or user_name(db, body.get("user_id")) or "Workshop"
    row.update_requested_at = None
    row.update_requested_by = None
    row.update_request_note = None
    row.last_updated_by = who
    notify_role(db, "admin", f"Louis updated stock order: {row.description}", None)
    db.commit()
    return {"success": True}

@app.post("/api/stock-orders/{item_id}/sign-received")
async def api_stock_sign(item_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    body = await request.json()
    role = (body.get("role") or "").lower()
    who = body.get("full_name") or user_name(db, body.get("user_id")) or "Staff"
    row = db.query(models.WorkshopStockOrder).filter(models.WorkshopStockOrder.id == item_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Item not found")
    if row.status == "Closed":
        raise HTTPException(status_code=400, detail="Already closed")
    if role == "stock" or role in ("admin", "accounts"):
        row.stock_received_by = who
        row.stock_received_at = datetime.utcnow()
    elif role == "workshop":
        row.workshop_received_by = who
        row.workshop_received_at = datetime.utcnow()
    else:
        raise HTTPException(status_code=403, detail="Only stock controller and workshop can sign received")
    row.last_updated_by = who
    row.status = "Received"
    if row.stock_received_by and row.workshop_received_by:
        row.status = "Closed"
        msg = f"Workshop stock CLOSED (both signed received): {row.description}"
    else:
        msg = f"Workshop stock received signed by {who} ({role}). Waiting for the other sign-off: {row.description}"
    notify_role(db, "stock", msg)
    notify_role(db, "workshop", msg)
    db.commit()
    return {"success": True, "status": row.status}

@app.post("/api/jobs/{job_id}/parts/{part_id}/progress")
async def api_part_progress(job_id: int, part_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
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
async def api_part_followup(job_id: int, part_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
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
async def api_set_activity(job_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    body = await request.json()
    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    assert_editable(db, job, body.get("user_id"))

    assert_editable(db, job, body.get("user_id"))

    assert_editable(db, job, body.get("user_id"))
    location = body.get("location")
    if location:
        apply_job_location(db, job, location, body.get("full_name"), body.get("user_id"))
    job.current_activity = (body.get("activity") or "").strip() or None
    job.current_activity_notes = (body.get("notes") or "").strip() or None
    job.current_activity_at = datetime.utcnow()
    job.current_activity_by = body.get("full_name") or "Workshop"
    add_update(
        db, job.id, "activity",
        f"{job.current_location or ''} — {job.current_activity or ''}".strip(" —"),
        notes=job.current_activity_notes,
        created_by_name=job.current_activity_by,
        created_by=body.get("user_id"),
    )
    # Current activity is a note only. A real extra job is added under Work / Prep Tasks.
    msg = f"Update on {job_display_id(job)}: {job.current_location or ''} {job.current_activity or ''}".strip()
    # Admin/accounts get this message through notify_role below.
    sales = job_salesman_users(db, job, skip_roles=("admin", "accounts")) if job.salesman_name else []
    for u in sales:
        db.add(models.Notification(user_id=u.id, job_card_id=job.id, message=msg))
    send_web_push(db, [u.id for u in sales], "Status Job Cards", msg, f"/jobs/{job.id}")
    notify_role(db, "admin", msg, job.id)
    db.commit()
    return {"success": True}

@app.get("/admin/print-bookings", response_class=HTMLResponse)
async def admin_print_bookings_page(request: Request, current_user: models.User = Depends(auth.get_current_active_user)):
    return render_template("print_admin_bookings.html", request=request)

@app.get("/api/admin/job-bookings")
async def api_admin_job_bookings(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_admin(current_user)
    jobs = active_jobs(db).order_by(models.JobCard.created_at.desc()).all()
    counts = stock_repeat_counts(jobs)
    out = []
    for job in jobs:
        parts = db.query(models.PartItem).filter(models.PartItem.job_card_id == job.id).all()
        extras = db.query(models.JobTask).filter(models.JobTask.job_card_id == job.id, models.JobTask.is_custom == True).all()
        if not parts and not extras:
            continue
        out.append(with_display({
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
        }, job, counts))
    return {"jobs": out}

@app.get("/api/workshop/parts")
async def api_workshop_parts(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    parts = db.query(models.PartItem).order_by(models.PartItem.created_at.desc()).all()
    out = []
    jobs_for_parts = []
    for p in parts:
        job = db.query(models.JobCard).filter(models.JobCard.id == p.job_card_id).first()
        if job and is_archived(job):
            continue
        jobs_for_parts.append(job)
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
    counts = stock_repeat_counts([j for j in jobs_for_parts if j])
    out = [with_display(row, job, counts) for row, job in zip(out, jobs_for_parts)]
    return {"parts": out}

@app.get("/api/notifications")
async def api_notifications(user_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if user and user.role != "workshop":
        db.query(models.Notification).filter(
            models.Notification.user_id == user_id,
            models.Notification.message.like("Morning location check%")
        ).delete(synchronize_session=False)
        db.commit()
    q = db.query(models.Notification).filter(models.Notification.user_id == user_id)
    if not user or user.role != "workshop":
        q = q.filter(~models.Notification.message.like("Morning location check%"))
    rows = q.order_by(models.Notification.created_at.desc()).limit(40).all()
    visible = []
    for n in rows:
        if n.job_card_id:
            job = db.query(models.JobCard).filter(models.JobCard.id == n.job_card_id).first()
            if is_archived(job) and (not user or user.role != "admin"):
                continue
        visible.append(n)
    unread = sum(1 for n in visible if not n.is_read)
    return {"unread": unread, "notifications": [{
        "id": n.id,
        "message": n.message,
        "job_card_id": n.job_card_id,
        "is_read": n.is_read,
        "created_at": n.created_at.isoformat() if n.created_at else None
    } for n in visible[:30]]}

@app.post("/api/notifications/mark-read")
async def api_mark_notifications_read(request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    body = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    uid = body.get("user_id")
    if not uid:
        raise HTTPException(status_code=400, detail="user_id required")
    try:
        uid = int(uid)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="user_id required")
    q = db.query(models.Notification).filter(models.Notification.user_id == uid, models.Notification.is_read == False)
    if body.get("id"):
        q = q.filter(models.Notification.id == int(body.get("id")))
    if body.get("job_card_id"):
        q = q.filter(models.Notification.job_card_id == int(body.get("job_card_id")))
    q.update({"is_read": True}, synchronize_session=False)
    db.commit()
    return {"success": True}

@app.post("/api/jobs/{job_id}/tasks/{task_id}/approve")
async def api_approve_task(job_id: int, task_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
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
async def api_pdi_fails(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    jobs = active_jobs(db).filter(models.JobCard.status == "PDI Failed - Returned to Workshop").order_by(models.JobCard.created_at.desc()).all()
    counts = stock_repeat_counts(jobs)
    out = []
    for j in jobs:
        fails = db.query(models.PDIItem).filter(models.PDIItem.job_card_id == j.id, models.PDIItem.status == "Fail").all()
        out.append(with_display({
            "id": j.id,
            "job_number": j.job_number,
            "stock_number": j.stock_number,
            "vehicle_description": j.vehicle_description,
            "year": j.year,
            "salesman_name": j.salesman_name,
            "fails": [{"item": f.check_item, "notes": f.notes, "by": f.initials} for f in fails]
        }, j, counts))
    return {"jobs": out}

def can_book_wash(user) -> bool:
    if not user:
        return False
    role = (user.role or "").lower()
    name = (user.full_name or "").strip().lower()
    uname = (user.username or "").strip().lower()
    return role in ("sales", "admin", "accounts", "marketing") or uname == "damian" or name == "damian" or name.startswith("damian ")

@app.post("/api/jobs/{job_id}/wash-request")
async def api_wash_request(job_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    if not can_book_wash(current_user):
        raise HTTPException(status_code=403, detail="Sales / marketing can request a wash")
    try:
        body = await request.json()
    except Exception:
        body = {}
    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    notes = (body.get("notes") or "Wash for marketing photos").strip()
    wr = models.WashRequest(
        job_card_id=job.id,
        notes=notes,
        status="Requested",
        requested_by_name=current_user.full_name,
        requested_by=current_user.id,
    )
    db.add(wr)
    db.add(models.JobUpdate(
        job_card_id=job.id,
        category="wash_request",
        description="Wash requested for marketing / photos",
        notes=notes,
        created_by_name=current_user.full_name,
        created_by=current_user.id,
    ))
    db.commit()
    notify_role(db, "workshop", f"Wash requested for {job_display_id(job)} — {job.vehicle_description}", job.id)
    notify_role(db, "admin", f"Wash requested for {job_display_id(job)}", job.id)
    return {"success": True}

@app.post("/api/wash-requests")
async def api_book_showroom_wash(request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    if not can_book_wash(current_user):
        raise HTTPException(status_code=403, detail="Sales / marketing can request a wash")
    try:
        body = await request.json()
    except Exception:
        body = {}
    stock = (body.get("stock_number") or "").strip().upper()
    make = (body.get("make") or "").strip()
    vehicle_type = (body.get("vehicle_type") or body.get("type") or "").strip()
    notes = (body.get("notes") or "Wash for marketing photos").strip()
    if not stock or not make or not vehicle_type:
        raise HTTPException(status_code=400, detail="WS number, make and type are required")
    job = db.query(models.JobCard).filter(
        models.JobCard.stock_number == stock,
        ~models.JobCard.status.in_(CLOSED_STATUSES),
    ).order_by(models.JobCard.created_at.desc()).first()
    wr = models.WashRequest(
        job_card_id=job.id if job else None,
        stock_number=stock,
        make=make,
        vehicle_type=vehicle_type,
        notes=notes,
        status="Requested",
        requested_by_name=current_user.full_name,
        requested_by=current_user.id,
    )
    db.add(wr)
    if job:
        db.add(models.JobUpdate(
            job_card_id=job.id,
            category="wash_request",
            description="Wash requested for marketing / photos",
            notes=f"{stock} {make} {vehicle_type}. {notes}",
            created_by_name=current_user.full_name,
            created_by=current_user.id,
        ))
    db.commit()
    notify_role(db, "workshop", f"Wash requested for {stock} — {make} {vehicle_type}", job.id if job else None)
    notify_role(db, "admin", f"Wash requested for {stock} — {make} {vehicle_type}", job.id if job else None)
    return {"success": True, "stock_number": stock}

@app.get("/api/wash-requests")
async def api_list_wash_requests(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    rows = db.query(models.WashRequest).order_by(models.WashRequest.created_at.desc()).limit(80).all()
    out = []
    for r in rows:
        if r.status == "Done":
            continue
        job = db.query(models.JobCard).filter(models.JobCard.id == r.job_card_id).first() if r.job_card_id else None
        if job and job.status in CLOSED_STATUSES:
            continue
        stock = r.stock_number or (job.stock_number if job else "")
        make = r.make or ""
        vehicle_type = r.vehicle_type or (job.vehicle_description if job else "")
        out.append({
            "id": r.id,
            "job_id": job.id if job else None,
            "stock_number": stock,
            "make": make,
            "vehicle_type": vehicle_type,
            "vehicle_description": " ".join(x for x in [make, vehicle_type, job.vehicle_description if job else ""] if x).strip(),
            "year": job.year if job else "",
            "location": job.current_location if job else "Showroom / not on job card",
            "notes": r.notes,
            "status": r.status,
            "requested_by_name": r.requested_by_name,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return {"requests": out}

@app.post("/api/wash-requests/{item_id}/status")
async def api_wash_status(item_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    if current_user.role != "workshop":
        raise HTTPException(status_code=403, detail="Workshop only")
    try:
        body = await request.json()
    except Exception:
        body = {}
    wr = db.query(models.WashRequest).filter(models.WashRequest.id == item_id).first()
    if not wr:
        raise HTTPException(status_code=404, detail="Request not found")
    status = body.get("status") or "At wash bay"
    if status not in ("Requested", "At wash bay", "Done"):
        raise HTTPException(status_code=400, detail="Invalid status")
    wr.status = status
    wr.updated_by_name = current_user.full_name
    job = db.query(models.JobCard).filter(models.JobCard.id == wr.job_card_id).first() if wr.job_card_id else None
    if not job and wr.stock_number:
        job = db.query(models.JobCard).filter(
            models.JobCard.stock_number == wr.stock_number,
            ~models.JobCard.status.in_(CLOSED_STATUSES),
        ).order_by(models.JobCard.created_at.desc()).first()
    if job and status == "Done":
        notes = (wr.notes or "").lower()
        marketing = "photo" in notes or "marketing" in notes or "showroom" in notes
        if not marketing:
            for t in (job.tasks or []):
                if is_delivery_wash_task(t.task_name) and (t.status or "") != "Completed":
                    t.status = "Completed"
                    t.completed_at = datetime.utcnow()
                    t.last_updated_by_name = current_user.full_name
            db.add(models.JobUpdate(
                job_card_id=job.id,
                category="wash",
                description="Wash / clean for delivery completed",
                notes=wr.notes,
                created_by_name=current_user.full_name,
                created_by=current_user.id,
            ))
    if job and status == "At wash bay" and "Wash Bay" in LOCATIONS:
        job.current_location = "Wash Bay"
        wr.job_card_id = job.id
    if wr.job_card_id:
        db.add(models.JobUpdate(
            job_card_id=wr.job_card_id,
            category="wash_request",
            description=f"Wash request {status}",
            notes=wr.notes,
            created_by_name=current_user.full_name,
            created_by=current_user.id,
        ))
    label = wr.stock_number or (job.stock_number if job else "vehicle")
    detail = " ".join(x for x in [wr.make, wr.vehicle_type] if x).strip()
    if status == "Done":
        msg = f"Wash completed for {label}" + (f" — {detail}" if detail else "")
    elif status == "At wash bay":
        msg = f"Wash started at wash bay for {label}" + (f" — {detail}" if detail else "")
    else:
        msg = f"Wash request {status} for {label}"
    notify_role(db, "marketing", msg, job.id if job else None)
    if wr.requested_by:
        who = db.query(models.User).filter(models.User.id == wr.requested_by, models.User.is_active == True).first()
        if who and (who.role or "") != "marketing":
            db.add(models.Notification(user_id=who.id, job_card_id=job.id if job else None, message=msg))
            send_web_push(db, [who.id], "Status Job Cards", msg, "/dashboard")
    db.commit()
    return {"success": True}

# ---------- TASK PHOTOS AND PHOTO ARCHIVE ----------
# Workshop takes BEFORE / AFTER photos on tasks. Admin / accounts download all photos of a job
# as one zip named by WS number, and may then delete exactly those photos from the app.
# Reminders are information only: nothing here is checked by Mark Ready, PDI, sign-off or delivery.
import re as _re
import io as _io
import zipfile as _zipfile
from datetime import timezone as _timezone

SAST_TZ = _timezone(timedelta(hours=2))  # South Africa has no daylight saving
TASK_PHOTO_DIR = os.path.join(UPLOAD_DIR, "tasks")
TASK_PHOTO_EXTS = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".heic": "image/heic", ".heif": "image/heif"}
MAX_TASK_PHOTO_BYTES = 15 * 1024 * 1024
MAX_PHOTOS_PER_STAGE = 10
PHOTO_TASK_NAMES = ("brake test", "service before delivery")
PHOTO_TASK_RE = _re.compile(r"brake|under\s*-?\s*carr|suspension", _re.IGNORECASE)

def sast_text(dt):
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_timezone.utc)
    return dt.astimezone(SAST_TZ).strftime("%d %b %Y %H:%M") + " SAST"

def needs_photo_reminder(job, task) -> bool:
    """Sold jobs only: brake tests, service before delivery, and any brake / undercarriage / suspension task."""
    if not job or not task or is_showroom(job):
        return False
    name = (getattr(task, "task_name", "") or "").strip()
    low = name.lower()
    return any(k in low for k in PHOTO_TASK_NAMES) or bool(PHOTO_TASK_RE.search(name))

def task_photo_info(job, task, job_photos, photos_archived):
    mine = [p for p in job_photos if p.task_id == task.id]
    reminder = needs_photo_reminder(job, task) and not is_archived(job) and not photos_archived and job.status != "Delivered / Closed"
    missing = []
    if reminder:
        if not any(p.stage == "before" for p in mine):
            missing.append("before")
        if not any(p.stage == "after" for p in mine):
            missing.append("after")
    return {
        "photos": [{
            "id": p.id,
            "stage": p.stage,
            "uploaded_by_name": p.uploaded_by_name,
            "uploaded_at_sast": sast_text(p.uploaded_at),
        } for p in mine],
        "photo_reminder": reminder,
        "photos_missing": missing,
    }

def _safe_name_part(value, fallback="photo"):
    cleaned = _re.sub(r"[^A-Za-z0-9]+", "-", (value or "").strip()).strip("-")
    return (cleaned[:40] or fallback)

def _supplier_photo_abs(photo_path):
    if not photo_path or not photo_path.startswith("/uploads/supplier/"):
        return None
    return os.path.join(UPLOAD_DIR, "supplier", os.path.basename(photo_path))

def _task_photo_abs(photo_path):
    if not photo_path:
        return None
    return os.path.join(TASK_PHOTO_DIR, os.path.basename(photo_path))

def job_photo_items(db, job):
    """Every photo file on this job that exists on disk: task photos and supplier job-card photos."""
    items = []
    task_names = {t.id: t.task_name for t in (job.tasks or [])}
    for p in db.query(models.TaskPhoto).filter(models.TaskPhoto.job_card_id == job.id).order_by(models.TaskPhoto.id).all():
        path = _task_photo_abs(p.photo_path)
        if path and os.path.isfile(path):
            items.append({"key": f"t:{p.id}", "path": path, "folder": "Before" if p.stage == "before" else "After",
                          "label": task_names.get(p.task_id) or "task", "stage": p.stage})
    for s in db.query(models.SupplierUpdate).filter(models.SupplierUpdate.job_card_id == job.id).order_by(models.SupplierUpdate.id).all():
        path = _supplier_photo_abs(s.photo_path)
        if path and os.path.isfile(path):
            items.append({"key": f"s:{s.id}", "path": path, "folder": "Supplier",
                          "label": s.company or "supplier", "stage": "supplier", "photo_path": s.photo_path})
    return items

def _photo_job_for_user(db, job_id, current_user):
    job = db.query(models.JobCard).filter(models.JobCard.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not current_user or current_user.role == "supplier":
        raise HTTPException(status_code=403, detail="Not allowed")
    hide_archived(job, current_user)
    return job

def _looks_like_image(head: bytes, ext: str) -> bool:
    if ext in (".jpg", ".jpeg"):
        return head[:3] == b"\xff\xd8\xff"
    if ext == ".png":
        return head[:8] == b"\x89PNG\r\n\x1a\n"
    if ext == ".webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    if ext in (".heic", ".heif"):
        return head[4:8] == b"ftyp"
    return False

@app.post("/api/jobs/{job_id}/tasks/{task_id}/photos")
async def api_task_photo_upload(job_id: int, task_id: int, stage: str = Form(...), files: List[UploadFile] = File(...),
                                db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    job = _photo_job_for_user(db, job_id, current_user)
    if not (current_user.role == "workshop" or is_admin_user(current_user)):
        raise HTTPException(status_code=403, detail="Only workshop or admin can add task photos")
    assert_editable(db, job, current_user.id)
    task = db.query(models.JobTask).filter(models.JobTask.id == task_id, models.JobTask.job_card_id == job.id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    stage = (stage or "").strip().lower()
    if stage not in ("before", "after"):
        raise HTTPException(status_code=400, detail="Stage must be before or after")
    files = [f for f in (files or []) if f and f.filename]
    if not files:
        raise HTTPException(status_code=400, detail="Choose a photo")
    existing = db.query(models.TaskPhoto).filter(models.TaskPhoto.task_id == task.id, models.TaskPhoto.stage == stage).count()
    if existing + len(files) > MAX_PHOTOS_PER_STAGE:
        raise HTTPException(status_code=400, detail=f"Maximum {MAX_PHOTOS_PER_STAGE} {stage} photos per task")
    saved = []
    for f in files:
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in TASK_PHOTO_EXTS:
            raise HTTPException(status_code=400, detail="Photo must be jpg, png, webp or heic")
        raw = await f.read(MAX_TASK_PHOTO_BYTES + 1)
        if len(raw) > MAX_TASK_PHOTO_BYTES:
            raise HTTPException(status_code=400, detail="Photo is too large (max 15 MB)")
        if not _looks_like_image(raw[:16], ext):
            raise HTTPException(status_code=400, detail="That file is not a photo")
        saved.append((ext, raw))
    os.makedirs(TASK_PHOTO_DIR, exist_ok=True)
    rows = []
    for ext, raw in saved:
        fname = f"{job.id}_{uuid.uuid4().hex}{'.jpg' if ext == '.jpeg' else ext}"
        with open(os.path.join(TASK_PHOTO_DIR, fname), "wb") as out:
            out.write(raw)
        row = models.TaskPhoto(job_card_id=job.id, task_id=task.id, stage=stage, photo_path=f"tasks/{fname}",
                               uploaded_by=current_user.id, uploaded_by_name=current_user.full_name, uploaded_at=datetime.utcnow())
        db.add(row)
        rows.append(row)
    db.commit()
    log_audit(db, current_user.id, "Task photo added", job.id, f"{job_display_id(job)} {task.task_name}: {len(rows)} {stage} photo(s)")
    return {"success": True, "added": len(rows)}

@app.get("/api/task-photos/{photo_id}")
async def api_task_photo_get(photo_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    photo = db.query(models.TaskPhoto).filter(models.TaskPhoto.id == photo_id).first()
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")
    _photo_job_for_user(db, photo.job_card_id, current_user)
    path = _task_photo_abs(photo.photo_path)
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Photo file not found")
    ext = os.path.splitext(path)[1].lower()
    return FileResponse(path, media_type=TASK_PHOTO_EXTS.get(ext, "application/octet-stream"))

@app.post("/api/jobs/{job_id}/tasks/{task_id}/photo-skipped")
async def api_task_photo_skipped(job_id: int, task_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    job = _photo_job_for_user(db, job_id, current_user)
    task = db.query(models.JobTask).filter(models.JobTask.id == task_id, models.JobTask.job_card_id == job.id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    try:
        body = await request.json()
    except Exception:
        body = {}
    stage = (body.get("stage") or "").strip().lower()
    if stage not in ("before", "after"):
        stage = "photo"
    log_audit(db, current_user.id, "Task photo skipped", job.id, f"{job_display_id(job)} {task.task_name}: {stage} photo skipped")
    return {"success": True}

@app.post("/api/jobs/{job_id}/photos/download")
async def api_job_photos_download(job_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    job = _photo_job_for_user(db, job_id, current_user)
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Only admin or accounts can download job photos")
    items = job_photo_items(db, job)
    if not items:
        raise HTTPException(status_code=400, detail="There are no photos on this job")
    base = _safe_name_part(_re.sub(r"\s+", "", job.stock_number or ""), "") or _safe_name_part(job.job_number, f"job{job.id}")
    zip_name = f"{base}_photos_{datetime.now(SAST_TZ).strftime('%Y-%m-%d')}.zip"
    buf = _io.BytesIO()
    counters = {}
    with _zipfile.ZipFile(buf, "w", _zipfile.ZIP_DEFLATED) as zf:
        for it in items:
            label = _safe_name_part(it["label"], "task")
            k = (it["folder"], label, it["stage"])
            counters[k] = counters.get(k, 0) + 1
            ext = os.path.splitext(it["path"])[1].lower() or ".jpg"
            zf.write(it["path"], f"{it['folder']}/{base}_{label}_{it['stage']}_{counters[k]}{ext}")
    manifest = [{"key": it["key"], "photo_path": it.get("photo_path")} for it in items]
    rec = models.PhotoArchive(job_card_id=job.id, zip_name=zip_name, photo_count=len(items), manifest=json.dumps(manifest),
                              downloaded_by=current_user.id, downloaded_by_name=current_user.full_name, downloaded_at=datetime.utcnow())
    db.add(rec)
    db.commit()
    log_audit(db, current_user.id, "Photos downloaded", job.id, f"{job_display_id(job)} {zip_name}: {len(items)} photos")
    return Response(content=buf.getvalue(), media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="{zip_name}"',
        "X-Photo-Archive-Id": str(rec.id),
        "X-Photo-Count": str(len(items)),
    })

@app.post("/api/jobs/{job_id}/photos/delete")
async def api_job_photos_delete(job_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    """Second, explicit step after a download. Deletes only the photos that were in that zip. Never deletes job records."""
    job = _photo_job_for_user(db, job_id, current_user)
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Only admin or accounts can delete job photos")
    try:
        body = await request.json()
    except Exception:
        body = {}
    if body.get("confirm") is not True:
        raise HTTPException(status_code=400, detail="Confirm that the zip is saved before deleting")
    rec = db.query(models.PhotoArchive).filter(models.PhotoArchive.id == body.get("archive_id"), models.PhotoArchive.job_card_id == job.id).first()
    if not rec or rec.deleted_at:
        raise HTTPException(status_code=400, detail="Download the photos zip first")
    if rec.downloaded_by != current_user.id:
        raise HTTPException(status_code=400, detail="Only the person who downloaded the zip can delete these photos")
    try:
        manifest = json.loads(rec.manifest or "[]")
    except Exception:
        manifest = []
    files_to_remove = []
    deleted = 0
    for m in manifest:
        key = (m or {}).get("key") or ""
        kind, _, raw_id = key.partition(":")
        if not raw_id.isdigit():
            continue
        if kind == "t":
            p = db.query(models.TaskPhoto).filter(models.TaskPhoto.id == int(raw_id), models.TaskPhoto.job_card_id == job.id).first()
            if p:
                files_to_remove.append(_task_photo_abs(p.photo_path))
                db.delete(p)
                deleted += 1
        elif kind == "s":
            s = db.query(models.SupplierUpdate).filter(models.SupplierUpdate.id == int(raw_id), models.SupplierUpdate.job_card_id == job.id).first()
            if s and s.photo_path and s.photo_path == m.get("photo_path"):
                files_to_remove.append(_supplier_photo_abs(s.photo_path))
                s.photo_path = None  # the supplier update itself stays
                deleted += 1
    now = datetime.utcnow()
    rec.deleted_by = current_user.id
    rec.deleted_by_name = current_user.full_name
    rec.deleted_at = now
    rec.deleted_count = deleted
    text_line = f"Photos archived by {current_user.full_name} on {sast_text(now)}, {deleted} photo{'' if deleted == 1 else 's'} ({rec.zip_name})"
    db.add(models.JobUpdate(job_card_id=job.id, category="progress", description=text_line,
                            notes="Photos downloaded as zip and removed from the app", created_by_name=current_user.full_name, created_by=current_user.id))
    db.commit()
    log_audit(db, current_user.id, "Photos archived and deleted", job.id, f"{job_display_id(job)} {rec.zip_name}: {deleted} photos deleted from the app")
    for path in files_to_remove:
        try:
            if path and os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass
    return {"success": True, "deleted": deleted, "message": text_line}

# ---------- YARD CHECK (no client, price, task or photo data) ----------
def require_yard(user):
    if not user_has_yard_access(user):
        raise HTTPException(status_code=403, detail="Yard check access only")

def yard_can_start(user):
    return user.role in ("admin", "accounts")

def yard_lock(db):
    # Acquire SQLite's write lock before reading the active round. Serialises a
    # tick against closing a round and prevents simultaneous new rounds.
    db.execute(text("UPDATE stock_takes SET id = id WHERE closed_at IS NULL"))

def yard_current(db):
    current = db.query(models.StockTake).filter(models.StockTake.closed_at == None).first()
    if not current:
        # First visit only. Subsequent resets require admin/accounts.
        current = models.StockTake(started_at=datetime.utcnow(), started_by_name="System")
        db.add(current)
        db.flush()
    return current

def yard_stamp(value):
    return value.isoformat() + "Z" if value else None

def yard_rows(db, current):
    jobs = active_jobs(db).order_by(models.JobCard.stock_number, models.JobCard.id).all()
    counts = stock_repeat_counts(jobs)
    items = {i.job_card_id: i for i in db.query(models.StockTakeItem).filter(models.StockTakeItem.stock_take_id == current.id).all()}
    rows = []
    for job in jobs:
        item = items.get(job.id)
        rows.append({
            "job_id": job.id,
            "display_id": job_display_id(job),
            "label": job_display_label(job, counts),
            "on_site": bool(item and item.on_site),
            "on_site_by": item.on_site_by_name if item else None,
            "on_site_at": yard_stamp(item.on_site_at) if item else None,
            "sticker_fitted": bool(item and item.sticker_fitted),
            "sticker_by": item.sticker_by_name if item else None,
            "sticker_at": yard_stamp(item.sticker_at) if item else None,
        })
    return rows

def yard_summary(rows):
    return {
        "total": len(rows),
        "on_site": sum(r["on_site"] for r in rows),
        "stickers": sum(r["sticker_fitted"] for r in rows),
        "missing": sum(not (r["on_site"] and r["sticker_fitted"]) for r in rows),
    }

def yard_round_payload(current):
    return {"id": current.id, "started_at": yard_stamp(current.started_at),
            "started_by": current.started_by_name, "closed_at": yard_stamp(current.closed_at),
            "closed_by": current.closed_by_name, "source": current.source or "jobs"}

@app.get("/yard", response_class=HTMLResponse)
async def yard_page(request: Request, current_user: models.User = Depends(auth.get_current_active_user)):
    if not user_has_yard_access(current_user):
        return RedirectResponse(url="/dashboard")
    return render_template("yard.html", request=request, page_title="Yard check", yard_only=current_user.role == "yard", can_start=yard_can_start(current_user), can_manage=is_stock_manager(current_user), sections=YARD_SECTIONS)

@app.get("/api/yard/current")
async def api_yard_current(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_yard(current_user)
    yard_lock(db)
    current = yard_current(db)
    if current.source == "list":
        # Stock-list round: vehicles from the confirmed list (auto-dropped once their sales job is delivered).
        yard_sync_delivered(db)
        rows = yard_list_rows(db, current)
        result = {"round": yard_round_payload(current), "rows": rows, "summary": yard_summary(rows), "can_start": yard_can_start(current_user),
                  "mode": "list", "pending": yard_pending_rows(db, current_user), "can_manage": is_stock_manager(current_user)}
    else:
        rows = yard_rows(db, current)
        result = {"round": yard_round_payload(current), "rows": rows, "summary": yard_summary(rows), "can_start": yard_can_start(current_user)}
    db.commit()
    return result

@app.post("/api/yard/{round_id}/tick")
async def api_yard_tick(round_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_yard(current_user)
    body = await request.json()
    field = body.get("field")
    if field not in ("on_site", "sticker_fitted") or type(body.get("checked")) is not bool:
        raise HTTPException(status_code=400, detail="Choose an On site or WS sticker tick (true or false).")
    yard_lock(db)
    current = db.query(models.StockTake).filter(models.StockTake.id == round_id).first()
    if not current or current.closed_at:
        raise HTTPException(status_code=409, detail="This stock take is closed. Refresh to use the current one.")
    if current.source == "list":
        if type(body.get("unit_id")) is not int:
            raise HTTPException(status_code=400, detail="Choose a vehicle")
        unit = db.query(models.YardStockUnit).filter(models.YardStockUnit.id == body.get("unit_id"), models.YardStockUnit.status == "active").first()
        if not unit:
            raise HTTPException(status_code=404, detail="Vehicle is not on the yard list")
        uitem = db.query(models.StockTakeUnitItem).filter(models.StockTakeUnitItem.stock_take_id == current.id, models.StockTakeUnitItem.unit_id == unit.id).first()
        if not uitem:
            uitem = models.StockTakeUnitItem(stock_take_id=current.id, unit_id=unit.id)
            db.add(uitem)
        setattr(uitem, field, body["checked"])
        prefix = "on_site" if field == "on_site" else "sticker"
        setattr(uitem, prefix + "_by", current_user.id)
        setattr(uitem, prefix + "_by_name", current_user.full_name)
        setattr(uitem, prefix + "_at", datetime.utcnow())
        db.commit()
        return {"success": True}
    job = active_jobs(db).filter(models.JobCard.id == body.get("job_id")).first()
    if not job:
        raise HTTPException(status_code=404, detail="Open WS number not found")
    item = db.query(models.StockTakeItem).filter(models.StockTakeItem.stock_take_id == current.id, models.StockTakeItem.job_card_id == job.id).first()
    if not item:
        item = models.StockTakeItem(stock_take_id=current.id, job_card_id=job.id)
        db.add(item)
    setattr(item, field, body["checked"])
    prefix = "on_site" if field == "on_site" else "sticker"
    setattr(item, prefix + "_by", current_user.id)
    setattr(item, prefix + "_by_name", current_user.full_name)
    setattr(item, prefix + "_at", datetime.utcnow())
    db.commit()
    return {"success": True}

@app.post("/api/yard/start")
async def api_yard_start(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_yard(current_user)
    if not yard_can_start(current_user):
        raise HTTPException(status_code=403, detail="Only admin/accounts can start a new stock take.")
    yard_lock(db)
    current = yard_current(db)
    if current.source == "list":
        # A fresh round on the same confirmed stock list.
        yard_sync_delivered(db)
        new = yard_close_and_start(db, current, current_user, "list", current.upload_id)
        db.commit()
        return {"success": True, "id": new.id, "closed_id": current.id}
    rows = yard_rows(db, current)
    summary = yard_summary(rows)
    current.closed_at = datetime.utcnow()
    current.closed_by = current_user.id
    current.closed_by_name = current_user.full_name
    current.total_jobs, current.on_site_count, current.sticker_count = summary["total"], summary["on_site"], summary["stickers"]
    current.results = json.dumps(rows)
    db.flush()
    new = models.StockTake(started_at=datetime.utcnow(), started_by=current_user.id, started_by_name=current_user.full_name)
    db.add(new)
    db.commit()
    return {"success": True, "id": new.id, "closed_id": current.id}

YARD_PRINT_OTHER = "ADDED BY HAND / YARD FINDS"

def yard_print_groups(db, current):
    """Vehicles of the current round for the printed yard sheet. Only WS, make, model and reg: no price, CRM or client data."""
    groups = {s: [] for s in YARD_SECTIONS}
    groups[YARD_PRINT_OTHER] = []
    if current.source == "list":
        units = db.query(models.YardStockUnit).filter(models.YardStockUnit.status == "active").all()
        units.sort(key=lambda u: u.stock_number or "")
        for u in units:
            key = u.section if (u.source == "upload" and u.section in YARD_SECTIONS) else YARD_PRINT_OTHER
            groups[key].append({"ws": u.stock_number, "make": u.make or "", "model": u.model or "", "reg": u.registrations or ""})
    else:
        jobs = active_jobs(db).order_by(models.JobCard.stock_number, models.JobCard.id).all()
        counts = stock_repeat_counts(jobs)
        for j in jobs:
            groups[YARD_PRINT_OTHER].append({"ws": job_display_label(j, counts), "make": j.vehicle_description or "",
                                             "model": "", "reg": getattr(j, "registration_number", None) or ""})
    return [(name, rows) for name, rows in groups.items() if rows]

@app.get("/yard/print", response_class=HTMLResponse)
async def yard_print_page(request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    if not (user_has_yard_access(current_user) or is_stock_manager(current_user)) or current_user.role == "supplier":
        return RedirectResponse(url="/dashboard")
    yard_lock(db)
    current = yard_current(db)
    if current.source == "list":
        yard_sync_delivered(db)
    groups = yard_print_groups(db, current)
    upload = None
    if current.upload_id:
        upload = db.query(models.YardStockUpload).filter(models.YardStockUpload.id == current.upload_id).first()
    db.commit()
    return render_template("yard_print.html", request=request, round_id=current.id, groups=groups,
                           total=sum(len(r) for _, r in groups), list_mode=current.source == "list",
                           upload_date=sast_text(upload.confirmed_at) if upload and upload.confirmed_at else None,
                           printed_at=sast_text(datetime.utcnow()))

@app.get("/api/yard/history")
async def api_yard_history(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_yard(current_user)
    rounds = db.query(models.StockTake).filter(models.StockTake.closed_at != None).order_by(models.StockTake.id.desc()).all()
    return {"rounds": [dict(yard_round_payload(r), total=r.total_jobs, on_site=r.on_site_count, stickers=r.sticker_count) for r in rounds]}

@app.get("/api/yard/history/{round_id}")
async def api_yard_history_detail(round_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_yard(current_user)
    current = db.query(models.StockTake).filter(models.StockTake.id == round_id, models.StockTake.closed_at != None).first()
    if not current:
        raise HTTPException(status_code=404, detail="Past stock take not found")
    rows = json.loads(current.results or "[]")
    return {"round": yard_round_payload(current), "rows": rows, "summary": yard_summary(rows), "read_only": True,
            "mode": "list" if current.source == "list" else "jobs"}

# ---------- YARD STOCK LIST (stock managers; no price, CRM, extras or mileage) ----------
from .yard_stock_parser import parse_pdf as yard_parse_pdf, parse_xlsx as yard_parse_xlsx, StockParseError, stock_key as yard_stock_key, match_key as yard_match_key, validate_row as yard_validate_row, SECTIONS as YARD_SECTIONS, clean as yard_clean

YARD_PHOTO_DIR = os.path.join(UPLOAD_DIR, "yard")
os.makedirs(YARD_PHOTO_DIR, exist_ok=True)
MAX_STOCK_FILE_BYTES = 10 * 1024 * 1024
MAX_YARD_PHOTO_BYTES = 15 * 1024 * 1024
YARD_PHOTO_TYPES = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".heic": "image/heic"}
YARD_PHOTO_MAX_SIDE = 1280
YARD_PHOTO_JPEG_QUALITY = 80

def is_stock_manager(user) -> bool:
    """Admin/accounts (is_admin_user) always; anyone else only with the admin-granted stock_manager flag."""
    if not user or not getattr(user, "is_active", True) or (getattr(user, "role", "") or "") in ("supplier", "yard"):
        return False
    return is_admin_user(user) or bool(getattr(user, "stock_manager", False))

def require_stock_manager(user):
    if not is_stock_manager(user):
        raise HTTPException(status_code=403, detail="Stock list managers only")

def can_create_job(user) -> bool:
    """Roles that already get the Create job tab: sales, workshop, admin and accounts."""
    if not user or not getattr(user, "is_active", True):
        return False
    return (getattr(user, "role", "") or "") in ("sales", "workshop", "admin", "accounts")

def can_view_yard_stock(user) -> bool:
    """Stock list managers plus sales and workshop (view only)."""
    if not user or not getattr(user, "is_active", True):
        return False
    if is_stock_manager(user):
        return True
    return (getattr(user, "role", "") or "") in ("sales", "workshop")

def require_yard_stock_viewer(user):
    if not (can_view_yard_stock(user) or can_create_job(user)):
        raise HTTPException(status_code=403, detail="Not allowed")

# Stock-list section -> closest existing create-job main_type. The form stays editable.
STOCK_SECTION_TO_MAIN_TYPE = {
    "TANKERS": "Tanker (other)",
    "TRUCK TRACTORS": "Truck Tractor",
    "RIGIDS": "Rigid (other)",
    "TRAILERS": "Trailer (other)",
}

def yard_job_prefill(u):
    """Map an active yard_stock_units row onto the existing create-job field names."""
    make = (u.make or "").strip()
    model = (u.model or "").strip()
    desc = (u.description or "").strip()
    vehicle_description = " ".join(part for part in (make, model) if part) or desc
    sub_type = desc if vehicle_description != desc else (model or "")
    regs = (u.registrations or "").strip()
    return {
        "unit_id": u.id,
        "stock_number": u.stock_number,
        "year": u.year or "",
        "vehicle_description": vehicle_description,
        "main_type": STOCK_SECTION_TO_MAIN_TYPE.get((u.section or "").upper(), ""),
        "sub_type": sub_type,
        "registration_number": regs,
        "vin_number": "",
        "section": u.section,
        "make": u.make,
        "model": u.model,
        "description": u.description,
        "registrations": u.registrations,
        "availability": u.availability,
        "photo_url": yard_unit_photo_url(u),
    }

def yard_photo_kind(raw: bytes):
    """Return the file extension from the file's own bytes, never from its name or browser type."""
    if raw[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return ".webp"
    if raw[4:8] == b"ftyp" and raw[8:12] in (b"heic", b"heix", b"mif1", b"msf1", b"hevc", b"heim", b"heis"):
        return ".heic"
    return None

def yard_normalize_photo(raw: bytes, ext: str):
    """Fix EXIF orientation, shrink to 1280 on the longest side, re-encode as JPEG ~80, and strip EXIF/GPS.
    If the bytes cannot be decoded (typical for HEIC without a plugin), keep the original file as uploaded."""
    try:
        from io import BytesIO
        from PIL import Image, ImageOps
        im = Image.open(BytesIO(raw))
        im = ImageOps.exif_transpose(im) or im
        if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
            if im.mode == "P":
                im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, (26, 32, 40))
            alpha = im.split()[-1] if im.mode in ("RGBA", "LA") else None
            bg.paste(im, mask=alpha)
            im = bg
        elif im.mode != "RGB":
            im = im.convert("RGB")
        w, h = im.size
        longest = max(w, h)
        if longest > YARD_PHOTO_MAX_SIDE:
            scale = YARD_PHOTO_MAX_SIDE / float(longest)
            im = im.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.Resampling.LANCZOS)
        for key in list(im.info.keys()):
            im.info.pop(key, None)
        out = BytesIO()
        im.save(out, format="JPEG", quality=YARD_PHOTO_JPEG_QUALITY, optimize=True, progressive=True)
        data = out.getvalue()
        if not data or data[:3] != b"\xff\xd8\xff":
            return raw, ext
        return data, ".jpg"
    except Exception:
        return raw, ext

async def yard_save_photo(upload: UploadFile) -> str:
    if upload is None or not getattr(upload, "filename", None):
        raise HTTPException(status_code=400, detail="A photo is required")
    raw = await upload.read(MAX_YARD_PHOTO_BYTES + 1)
    if len(raw) > MAX_YARD_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="Photo is larger than 15 MB")
    ext = yard_photo_kind(raw)
    if not ext or len(raw) < 100:
        raise HTTPException(status_code=400, detail="Photo must be a JPEG, PNG, WEBP or HEIC image")
    raw, ext = yard_normalize_photo(raw, ext)
    rel = f"yard/{uuid.uuid4().hex}{ext}"
    with open(os.path.join(UPLOAD_DIR, rel), "wb") as fh:
        fh.write(raw)
    return rel

def yard_unit_photo_url(unit):
    if not unit or not unit.photo_path:
        return None
    stamp = int(unit.photo_at.timestamp()) if unit.photo_at else 0
    return f"/api/yard/stock/units/{unit.id}/photo?v={stamp}"

def yard_audit(db, user_id, action, details):
    # Added to the caller's transaction. Never contains prices, client data or photo bytes.
    db.add(models.AuditLog(user_id=user_id, action=action, details=details))

def yard_system_user_id(db):
    admin = db.query(models.User).filter(models.User.role == "admin").order_by(models.User.id).first()
    return admin.id if admin else 1

def yard_delivered_sales_jobs(db):
    """Sales jobs (job_purpose 'sold', or blank on older cards) at Delivered / Closed. Showroom jobs never count."""
    q = db.query(models.JobCard).filter(models.JobCard.status == DELIVERED_STATUS)
    out = {}
    for job in q.all():
        if (job.job_purpose or "sold") == "showroom":
            continue
        key = yard_match_key(job.stock_number)
        if key:
            out.setdefault(key, []).append(job)
    return out

def yard_sync_delivered(db):
    """Soft-remove active list vehicles whose sales job was delivered after the vehicle was listed.
    Only unambiguous keys: a key shared by two active vehicles is never auto-removed."""
    units = db.query(models.YardStockUnit).filter(models.YardStockUnit.status == "active").all()
    counts = {}
    for u in units:
        if u.match_key:
            counts[u.match_key] = counts.get(u.match_key, 0) + 1
    delivered = yard_delivered_sales_jobs(db)
    removed = 0
    for u in units:
        if not u.match_key or counts.get(u.match_key) != 1:
            continue
        jobs = [j for j in delivered.get(u.match_key, []) if (j.delivered_at or j.archived_at)]
        jobs = [j for j in jobs if u.listed_at is None or (j.delivered_at or j.archived_at).replace(tzinfo=None) > u.listed_at]
        if not jobs:
            continue
        job = sorted(jobs, key=lambda j: (j.delivered_at or j.archived_at).replace(tzinfo=None))[-1]
        u.status = "removed"
        u.removed_kind = "delivered"
        u.removed_at = datetime.utcnow()
        u.removed_by_name = "System"
        u.removed_job_id = job.id
        u.removed_reason = f"Sales job {job.job_number} delivered"
        yard_audit(db, yard_system_user_id(db), "Yard stock auto-removed", f"{u.stock_number} off the yard list: {job.job_number} delivered")
        removed += 1
    if removed:
        db.flush()
    return removed

def yard_photo_map(db):
    """match_key -> unit with a photo, only where exactly one listed vehicle owns that key (active first)."""
    units = db.query(models.YardStockUnit).filter(models.YardStockUnit.photo_path != None, models.YardStockUnit.status.in_(("active", "removed", "replaced"))).all()
    by_key = {}
    for u in units:
        if u.match_key:
            by_key.setdefault(u.match_key, []).append(u)
    out = {}
    for key, group in by_key.items():
        active = [u for u in group if u.status == "active"]
        if len(active) == 1:
            out[key] = active[0]
        elif not active and len({u.stock_number for u in group}) == 1:
            out[key] = sorted(group, key=lambda u: u.photo_at or datetime.min)[-1]
    return out

def job_photo_url(job, photo_map=None):
    """A real yard photo for the same WS replaces the generic stand-in; otherwise the stand-in as before."""
    if photo_map:
        unit = photo_map.get(yard_match_key(job.stock_number))
        if unit:
            return yard_unit_photo_url(unit)
    return match_stock_photo(job.vehicle_description, job.main_type, job.sub_type, job.year)

def yard_unit_payload(u, full=False):
    data = {
        "unit_id": u.id, "stock_number": u.stock_number, "section": u.section, "year": u.year,
        "make": u.make, "model": u.model, "description": u.description, "registrations": u.registrations,
        "availability": u.availability, "photo_url": yard_unit_photo_url(u), "status": u.status, "source": u.source,
        "photo_by": u.photo_by_name, "photo_at": yard_stamp(u.photo_at),
    }
    if full:
        data.update({
            "created_by": u.created_by_name, "listed_at": yard_stamp(u.listed_at),
            "decided_by": u.decided_by_name, "decided_at": yard_stamp(u.decided_at), "decision_note": u.decision_note,
            "removed_kind": u.removed_kind, "removed_by": u.removed_by_name, "removed_at": yard_stamp(u.removed_at),
            "removed_reason": u.removed_reason,
        })
    return data

def yard_list_rows(db, current):
    units = db.query(models.YardStockUnit).filter(models.YardStockUnit.status == "active").all()
    order = {s: i for i, s in enumerate(YARD_SECTIONS)}
    units.sort(key=lambda u: (order.get(u.section, 99), u.stock_number))
    items = {i.unit_id: i for i in db.query(models.StockTakeUnitItem).filter(models.StockTakeUnitItem.stock_take_id == current.id).all()}
    rows = []
    for u in units:
        item = items.get(u.id)
        row = yard_unit_payload(u)
        row.update({
            "label": u.stock_number,
            "on_site": bool(item and item.on_site),
            "on_site_by": item.on_site_by_name if item else None,
            "on_site_at": yard_stamp(item.on_site_at) if item else None,
            "sticker_fitted": bool(item and item.sticker_fitted),
            "sticker_by": item.sticker_by_name if item else None,
            "sticker_at": yard_stamp(item.sticker_at) if item else None,
        })
        rows.append(row)
    return rows

def yard_pending_rows(db, user):
    q = db.query(models.YardStockUnit).filter(models.YardStockUnit.status == "pending")
    if not is_stock_manager(user):
        q = q.filter(models.YardStockUnit.created_by == user.id)
    return [yard_unit_payload(u, full=True) for u in q.order_by(models.YardStockUnit.id).all()]

def yard_close_and_start(db, current, user, source, upload_id=None):
    """Close the current round exactly as /api/yard/start does (snapshot kept) and open a new one."""
    rows = yard_list_rows(db, current) if current.source == "list" else yard_rows(db, current)
    summary = yard_summary(rows)
    current.closed_at = datetime.utcnow()
    current.closed_by = user.id
    current.closed_by_name = user.full_name
    current.total_jobs, current.on_site_count, current.sticker_count = summary["total"], summary["on_site"], summary["stickers"]
    current.results = json.dumps(rows)
    db.flush()
    new = models.StockTake(started_at=datetime.utcnow(), started_by=user.id, started_by_name=user.full_name, source=source, upload_id=upload_id)
    db.add(new)
    db.flush()
    return new

def yard_form_fields(form):
    row = {k: yard_clean(form.get(k), 600 if k == "description" else 120) for k in ("stock_number", "section", "year", "make", "model", "description", "registrations", "availability")}
    row["stock_number"] = yard_stock_key(row["stock_number"])
    row["section"] = row["section"].upper()
    if not row["stock_number"] or len(row["stock_number"]) > 32:
        raise HTTPException(status_code=400, detail="Enter the WS / stock number")
    if row["section"] not in YARD_SECTIONS:
        raise HTTPException(status_code=400, detail="Choose a section")
    if not row["make"] and not row["description"]:
        raise HTTPException(status_code=400, detail="Enter the make or a description")
    return row

@app.get("/yard/stock", response_class=HTMLResponse)
async def yard_stock_page(request: Request, current_user: models.User = Depends(auth.get_current_active_user)):
    if not can_view_yard_stock(current_user):
        return RedirectResponse(url="/yard" if user_has_yard_access(current_user) else "/dashboard")
    return render_template(
        "yard_stock.html",
        request=request,
        page_title="Stock list",
        sections=YARD_SECTIONS,
        is_stock_manager=is_stock_manager(current_user),
        can_start_job=can_create_job(current_user),
        view_only=not is_stock_manager(current_user),
    )

@app.post("/api/yard/stock/upload")
async def api_yard_stock_upload(file: UploadFile = File(None), db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_stock_manager(current_user)
    if file is None or not getattr(file, "filename", None):
        raise HTTPException(status_code=400, detail="Choose the stock list file (PDF or .xlsx)")
    raw = await file.read(MAX_STOCK_FILE_BYTES + 1)
    if len(raw) > MAX_STOCK_FILE_BYTES:
        raise HTTPException(status_code=413, detail="Stock list file is larger than 10 MB")
    name = os.path.basename(file.filename or "")
    ext = os.path.splitext(name)[1].lower()
    try:
        if ext == ".pdf" and raw[:5] == b"%PDF-":
            parsed, kind = yard_parse_pdf(raw), "pdf"
        elif ext == ".xlsx" and raw[:4] == b"PK\x03\x04":
            parsed, kind = yard_parse_xlsx(raw), "xlsx"
        else:
            raise HTTPException(status_code=400, detail="Upload the stock list as a PDF or .xlsx file")
    except StockParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        raw = None  # the original file is never written to disk
    yard_sync_delivered(db)
    delivered = yard_delivered_sales_jobs(db)
    active = {u.stock_number: u for u in db.query(models.YardStockUnit).filter(models.YardStockUnit.status == "active").all()}
    for row in parsed["rows"]:
        d = row["data"]
        jobs = delivered.get(yard_match_key(d["stock_number"]) or "", [])
        if jobs:
            row["issues"].append("Job cards show this WS delivered (" + ", ".join(sorted(j.job_number for j in jobs))[:80] + "): check it is still in stock")
        if any(i.startswith("Duplicate stock number") for i in row["issues"]):
            row["include"] = False
        unit = active.get(d["stock_number"])
        row["existing"] = bool(unit)
        row["has_photo"] = bool(unit and unit.photo_path)
        # Only vehicles from an earlier list upload drop off when unticked; hand-added ones stay.
        row["existing_upload"] = bool(unit and unit.source == "upload")
    listed = {r["data"]["stock_number"] for r in parsed["rows"]}
    # Only vehicles that came from an earlier list upload drop off; hand-added vehicles and approved finds stay until removed by hand.
    parsed["dropping"] = sorted(s for s, u in active.items() if s not in listed and u.source == "upload")
    open_round = db.query(models.StockTake).filter(models.StockTake.closed_at == None).first()
    # "update": confirming updates the current list-based yard check (ticks kept); "start": first list round.
    parsed["mode"] = "update" if (open_round and open_round.source == "list") else "start"
    parsed["round_id"] = open_round.id if (open_round and open_round.source == "list") else None
    safe_name = re.sub(r"[^A-Za-z0-9 ._()-]", "_", name)[:120]
    for old in db.query(models.YardStockUpload).filter(models.YardStockUpload.status == "preview").all():
        old.status = "discarded"
    up = models.YardStockUpload(file_type=kind, file_name=safe_name, row_count=len(parsed["rows"]),
                                flagged_count=sum(bool(r["issues"]) for r in parsed["rows"]),
                                preview=json.dumps(parsed), status="preview",
                                uploaded_by=current_user.id, uploaded_by_name=current_user.full_name)
    db.add(up)
    db.flush()
    yard_audit(db, current_user.id, "Yard stock list uploaded", f"Upload {up.id} ({kind}): {up.row_count} rows, {up.flagged_count} flagged; preview only")
    db.commit()
    return {"upload_id": up.id, "file_type": kind, "file_name": safe_name, **parsed}

@app.get("/api/yard/stock/upload/{upload_id}")
async def api_yard_stock_upload_get(upload_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_stock_manager(current_user)
    up = db.query(models.YardStockUpload).filter(models.YardStockUpload.id == upload_id).first()
    if not up:
        raise HTTPException(status_code=404, detail="Upload not found")
    return {"upload_id": up.id, "status": up.status, "file_type": up.file_type, "file_name": up.file_name, **json.loads(up.preview or "{}")}

@app.post("/api/yard/stock/upload/{upload_id}/discard")
async def api_yard_stock_upload_discard(upload_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_stock_manager(current_user)
    up = db.query(models.YardStockUpload).filter(models.YardStockUpload.id == upload_id, models.YardStockUpload.status == "preview").first()
    if not up:
        raise HTTPException(status_code=404, detail="No preview to discard")
    up.status = "discarded"
    db.commit()
    return {"success": True}

@app.post("/api/yard/stock/upload/{upload_id}/confirm")
async def api_yard_stock_upload_confirm(upload_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_stock_manager(current_user)
    try:
        body = await request.json()
    except Exception:
        body = {}
    include = body.get("include")
    if not isinstance(include, list) or not all(type(i) is int for i in include):
        raise HTTPException(status_code=400, detail="Send the list of rows to include")
    yard_lock(db)
    up = db.query(models.YardStockUpload).filter(models.YardStockUpload.id == upload_id).first()
    if not up or up.status != "preview":
        raise HTTPException(status_code=409, detail="This preview was already confirmed or replaced. Upload again.")
    preview = json.loads(up.preview or "{}")
    rows = preview.get("rows", [])
    picked = sorted(set(i for i in include if 0 <= i < len(rows)))
    if not picked:
        raise HTTPException(status_code=400, detail="Include at least one vehicle")
    chosen = {}
    for i in picked:
        data, _issues = yard_validate_row(rows[i]["data"])
        if not data["stock_number"]:
            raise HTTPException(status_code=400, detail=f"Line {i + 1} has no stock number")
        if data["stock_number"] in chosen:
            raise HTTPException(status_code=400, detail=f"{data['stock_number']} is included twice. Untick one.")
        chosen[data["stock_number"]] = data
    yard_sync_delivered(db)
    now = datetime.utcnow()
    active = {u.stock_number: u for u in db.query(models.YardStockUnit).filter(models.YardStockUnit.status == "active").all()}
    kept = added = dropped = 0
    for stock, data in chosen.items():
        unit = active.get(stock)
        if unit:
            # Same vehicle on the new list: refresh its details, keep its photo and listing date.
            for k in ("section", "year", "make", "model", "description", "registrations", "availability"):
                setattr(unit, k, data[k])
            unit.upload_id = up.id
            kept += 1
        else:
            db.add(models.YardStockUnit(stock_number=stock, match_key=yard_match_key(stock), source="upload", status="active",
                                        upload_id=up.id, listed_at=now, created_by=current_user.id, created_by_name=current_user.full_name,
                                        **{k: data[k] for k in ("section", "year", "make", "model", "description", "registrations", "availability")}))
            added += 1
    for stock, unit in active.items():
        # Hand-added vehicles (single) and approved yard finds are kept; they go only by hand or on Delivered.
        if stock not in chosen and unit.source == "upload":
            unit.status = "replaced"
            unit.removed_kind = "replaced"
            unit.removed_at = now
            unit.removed_by = current_user.id
            unit.removed_by_name = current_user.full_name
            unit.removed_reason = f"Not on new list (upload {up.id})"
            dropped += 1
    db.flush()
    current = yard_current(db)
    if current.source == "list":
        # No reset: the current list-based yard check carries on. Remaining vehicles keep their ticks
        # (ticks are stored per vehicle), new vehicles start unticked, dropped ones leave the round.
        current.upload_id = up.id
        round_id, closed_id = current.id, None
        note = f"Stock take {current.id} updated (ticks kept)."
    else:
        # First stock-list upload (or the round is job-based): start a list round as before.
        new = yard_close_and_start(db, current, current_user, "list", up.id)
        round_id, closed_id = new.id, current.id
        note = f"Stock take {current.id} closed, {new.id} started."
    up.status = "confirmed"
    up.confirmed_by, up.confirmed_by_name, up.confirmed_at = current_user.id, current_user.full_name, now
    up.stock_take_id = round_id
    yard_audit(db, current_user.id, "Yard stock list confirmed",
               f"Upload {up.id}: {len(chosen)} vehicles ({added} new, {kept} unchanged, {dropped} off the list). {note}")
    db.commit()
    return {"success": True, "round_id": round_id, "closed_id": closed_id, "updated": closed_id is None,
            "added": added, "kept": kept, "dropped": dropped}

@app.get("/api/yard/stock/units")
async def api_yard_stock_units(status: str = "active", db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_stock_manager(current_user)
    if status not in ("active", "pending", "removed"):
        raise HTTPException(status_code=400, detail="Unknown list")
    yard_sync_delivered(db)
    db.commit()
    statuses = ("removed", "replaced", "rejected") if status == "removed" else (status,)
    units = db.query(models.YardStockUnit).filter(models.YardStockUnit.status.in_(statuses)).all()
    order = {s: i for i, s in enumerate(YARD_SECTIONS)}
    units.sort(key=lambda u: (order.get(u.section, 99), u.stock_number) if status != "removed" else (-(u.removed_at or u.decided_at or datetime.min).timestamp(),))
    return {"units": [yard_unit_payload(u, full=True) for u in units[:500]],
            "counts": {s: db.query(models.YardStockUnit).filter(models.YardStockUnit.status == s).count() for s in ("active", "pending")}}

async def yard_create_unit(request, db, current_user, status, source):
    form = await request.form()
    row = yard_form_fields(form)
    photo = form.get("photo")
    if not hasattr(photo, "read"):
        raise HTTPException(status_code=400, detail="A photo is required")
    existing = db.query(models.YardStockUnit).filter(models.YardStockUnit.stock_number == row["stock_number"], models.YardStockUnit.status.in_(("active", "pending"))).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"{row['stock_number']} is already on the list" + (" (waiting for approval)" if existing.status == "pending" else ""))
    rel = await yard_save_photo(photo)
    now = datetime.utcnow()
    unit = models.YardStockUnit(match_key=yard_match_key(row["stock_number"]), source=source, status=status, listed_at=now,
                                created_by=current_user.id, created_by_name=current_user.full_name,
                                photo_path=rel, photo_by=current_user.id, photo_by_name=current_user.full_name, photo_at=now, **row)
    db.add(unit)
    db.flush()
    db.add(models.YardUnitPhoto(unit_id=unit.id, photo_path=rel, added_by=current_user.id, added_by_name=current_user.full_name, added_at=now))
    return unit

@app.post("/api/yard/stock/units")
async def api_yard_stock_add(request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_stock_manager(current_user)
    unit = await yard_create_unit(request, db, current_user, "active", "single")
    yard_audit(db, current_user.id, "Yard stock vehicle added", f"{unit.stock_number} added with photo")
    db.commit()
    return {"success": True, "unit": yard_unit_payload(unit, full=True)}

@app.post("/api/yard/stock/finds")
async def api_yard_stock_find(request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_yard(current_user)
    unit = await yard_create_unit(request, db, current_user, "pending", "yard_find")
    yard_audit(db, current_user.id, "Yard find reported", f"{unit.stock_number} found in the yard; waiting for approval")
    db.commit()
    return {"success": True, "unit": yard_unit_payload(unit, full=True)}

def yard_get_unit(db, unit_id):
    unit = db.query(models.YardStockUnit).filter(models.YardStockUnit.id == unit_id).first()
    if not unit:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return unit

@app.post("/api/yard/stock/units/{unit_id}/decision")
async def api_yard_stock_decision(unit_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_stock_manager(current_user)
    body = await request.json()
    decision = body.get("decision")
    note = yard_clean(body.get("note"), 300)
    if decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="Approve or reject")
    if decision == "reject" and not note:
        raise HTTPException(status_code=400, detail="Give a reason for rejecting")
    yard_lock(db)
    unit = yard_get_unit(db, unit_id)
    if unit.status != "pending":
        raise HTTPException(status_code=409, detail="This vehicle is no longer waiting for approval")
    if decision == "approve" and db.query(models.YardStockUnit).filter(models.YardStockUnit.stock_number == unit.stock_number, models.YardStockUnit.status == "active").first():
        raise HTTPException(status_code=409, detail=f"{unit.stock_number} is already on the list. Reject this one with a note.")
    unit.status = "active" if decision == "approve" else "rejected"
    unit.decided_by, unit.decided_by_name, unit.decided_at, unit.decision_note = current_user.id, current_user.full_name, datetime.utcnow(), note or None
    if decision == "approve":
        unit.listed_at = datetime.utcnow()
    yard_audit(db, current_user.id, "Yard find " + ("approved" if decision == "approve" else "rejected"), f"{unit.stock_number}" + (f": {note}" if note else ""))
    db.commit()
    return {"success": True, "status": unit.status}

@app.post("/api/yard/stock/units/{unit_id}/remove")
async def api_yard_stock_remove(unit_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_stock_manager(current_user)
    body = await request.json()
    reason = yard_clean(body.get("reason"), 300)
    if len(reason) < 3:
        raise HTTPException(status_code=400, detail="Say why it comes off the list")
    unit = yard_get_unit(db, unit_id)
    if unit.status != "active":
        raise HTTPException(status_code=409, detail="Only vehicles on the list can be removed")
    unit.status, unit.removed_kind = "removed", "manual"
    unit.removed_at, unit.removed_by, unit.removed_by_name, unit.removed_reason = datetime.utcnow(), current_user.id, current_user.full_name, reason
    yard_audit(db, current_user.id, "Yard stock removed", f"{unit.stock_number} off the yard list: {reason}")
    db.commit()
    return {"success": True}

@app.post("/api/yard/stock/units/{unit_id}/restore")
async def api_yard_stock_restore(unit_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_stock_manager(current_user)
    unit = yard_get_unit(db, unit_id)
    if unit.status not in ("removed", "replaced"):
        raise HTTPException(status_code=409, detail="Only removed vehicles can be put back")
    if db.query(models.YardStockUnit).filter(models.YardStockUnit.stock_number == unit.stock_number, models.YardStockUnit.status == "active").first():
        raise HTTPException(status_code=409, detail=f"{unit.stock_number} is already on the list")
    previous = unit.removed_reason or unit.removed_kind
    unit.status = "active"
    # A restored vehicle must not be removed again for the same delivered job.
    unit.listed_at = datetime.utcnow()
    unit.removed_kind = unit.removed_reason = unit.removed_at = unit.removed_by = unit.removed_by_name = unit.removed_job_id = None
    yard_audit(db, current_user.id, "Yard stock restored", f"{unit.stock_number} back on the yard list (was: {previous})")
    db.commit()
    return {"success": True}

@app.post("/api/yard/stock/units/{unit_id}/photo")
async def api_yard_stock_photo(unit_id: int, photo: UploadFile = File(None), db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    require_stock_manager(current_user)
    unit = yard_get_unit(db, unit_id)
    if unit.status in ("rejected",):
        raise HTTPException(status_code=409, detail="This vehicle was rejected")
    rel = await yard_save_photo(photo)
    now = datetime.utcnow()
    db.add(models.YardUnitPhoto(unit_id=unit.id, photo_path=rel, replaced_path=unit.photo_path, added_by=current_user.id, added_by_name=current_user.full_name, added_at=now))
    replaced = bool(unit.photo_path)
    unit.photo_path, unit.photo_by, unit.photo_by_name, unit.photo_at = rel, current_user.id, current_user.full_name, now
    yard_audit(db, current_user.id, "Yard stock photo " + ("replaced" if replaced else "added"), f"{unit.stock_number} photo")
    db.commit()
    return {"success": True, "photo_url": yard_unit_photo_url(unit), "photo_by": unit.photo_by_name, "photo_at": yard_stamp(unit.photo_at)}

@app.get("/api/yard/stock/units/{unit_id}/photo")
async def api_yard_stock_photo_get(unit_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    unit = yard_get_unit(db, unit_id)
    allowed = is_stock_manager(current_user) or (unit.status in ("active", "removed", "replaced") and current_user.role != "supplier") or unit.created_by == current_user.id
    if not allowed or not unit.photo_path:
        raise HTTPException(status_code=404, detail="Photo not found")
    path = os.path.realpath(os.path.join(UPLOAD_DIR, unit.photo_path))
    if not path.startswith(os.path.realpath(YARD_PHOTO_DIR) + os.sep) or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Photo not found")
    return FileResponse(path, media_type=YARD_PHOTO_TYPES.get(os.path.splitext(path)[1], "application/octet-stream"),
                        headers={"Content-Disposition": "inline", "Cache-Control": "private, max-age=86400"})

def yard_photo_map_cached(db):
    """One photo lookup per request session."""
    if "_yard_photos" not in db.info:
        db.info["_yard_photos"] = yard_photo_map(db)
    return db.info["_yard_photos"]


def yard_active_units_query(db):
    """Active list vehicles only (not pending, rejected, removed or replaced; delivered units are removed)."""
    yard_sync_delivered(db)
    db.commit()
    units = db.query(models.YardStockUnit).filter(models.YardStockUnit.status == "active").all()
    order = {s: i for i, s in enumerate(YARD_SECTIONS)}
    units.sort(key=lambda u: (order.get(u.section, 99), u.stock_number or ""))
    return units

def yard_picker_matches(units, q: str):
    q = (q or "").strip().upper()
    q_key = "".join(q.split())
    if not q:
        return units
    out = []
    for u in units:
        blob = " ".join([
            u.stock_number or "",
            u.make or "",
            u.model or "",
            u.description or "",
            u.registrations or "",
            u.year or "",
            u.section or "",
        ]).upper()
        key = "".join((u.stock_number or "").split()).upper()
        if q in blob or (q_key and q_key in key):
            out.append(u)
    return out

@app.get("/api/yard/stock/picker")
async def api_yard_stock_picker(q: str = "", unit_id: int = None, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    """Search or fetch active stock-list vehicles for the create-job picker and view-only list. Login required."""
    require_yard_stock_viewer(current_user)
    if unit_id is not None:
        unit = yard_get_unit(db, unit_id)
        if unit.status != "active":
            raise HTTPException(status_code=404, detail="Vehicle not found")
        row = yard_unit_payload(unit)
        row.update(yard_job_prefill(unit))
        return {"units": [row]}
    units = yard_picker_matches(yard_active_units_query(db), q)[:500]
    out = []
    for u in units:
        row = yard_unit_payload(u)
        row.update(yard_job_prefill(u))
        out.append(row)
    return {"units": out}
