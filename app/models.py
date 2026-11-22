from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, Float, UniqueConstraint, Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base
import enum

class UserRole(str, enum.Enum):
    SALES = "sales"
    WORKSHOP = "workshop"
    ACCOUNTS = "accounts"
    ADMIN = "admin"
    STOCK = "stock"
    SUPPLIER = "supplier"
    MARKETING = "marketing"

class JobStatus(str, enum.Enum):
    SUBMITTED = "Submitted to Workshop"
    ACCEPTED = "Accepted by Workshop"
    IN_PROGRESS = "In Progress"
    WORK_COMPLETED = "Work Completed"
    PDI_IN_PROGRESS = "PDI in Progress"
    PDI_COMPLETED = "PDI Completed"
    READY_FOR_DELIVERY = "Ready for Delivery"
    DELIVERED = "Delivered / Closed"

class Priority(str, enum.Enum):
    NORMAL = "Normal"
    HIGH = "High"
    URGENT = "Urgent"

class TaskStatus(str, enum.Enum):
    NOT_STARTED = "Not Started"
    IN_PROGRESS = "In Progress"
    COMPLETED = "Completed"
    BLOCKED = "Blocked"

class PDIStatus(str, enum.Enum):
    PASS = "Pass"
    FAIL = "Fail"
    NA = "N/A"

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    must_change_password = Column(Boolean, default=False)
    password_changed_at = Column(DateTime(timezone=True), nullable=True)
    role = Column(String, nullable=False)  # sales, workshop, accounts, admin, stock, supplier
    supplier_company = Column(String, nullable=True)
    yard_access = Column(Boolean, default=False)
    stock_manager = Column(Boolean, default=False)  # may upload/add/remove yard stock and add photos
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    jobs_created = relationship("JobCard", back_populates="created_by_user", foreign_keys="JobCard.created_by")
    audit_logs = relationship("AuditLog", back_populates="user")

class JobCard(Base):
    __tablename__ = "job_cards"

    id = Column(Integer, primary_key=True, index=True)
    job_number = Column(String, unique=True, index=True)  # e.g. JC-2026-0001

    # Vehicle Information
    stock_number = Column(String, nullable=False, index=True)  # WS####
    vehicle_description = Column(String, nullable=False)
    year = Column(String, nullable=False)
    main_type = Column(String, nullable=False)  # Tanker, Truck Tractor, Trailer, Tipper, Other
    sub_type = Column(String, nullable=False)
    vin_number = Column(String, nullable=True)
    chassis_number = Column(String, nullable=True)
    registration_number = Column(String, nullable=True)

    # Client & Sales
    client_name = Column(String, nullable=False)
    customer_order_ref = Column(String, nullable=True)
    salesman_name = Column(String, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"))

    # Job Details
    priority = Column(String, default="Normal")
    target_delivery_date = Column(String, nullable=True)
    current_location = Column(String, nullable=True)
    internal_notes = Column(Text, nullable=True)
    quotation_invoice_number = Column(String, nullable=True)
    estimated_workshop_hours = Column(Float, nullable=True)
    other_instructions = Column(Text, nullable=True)
    third_party_place = Column(String, nullable=True)
    third_party_date = Column(String, nullable=True)
    parts_to_order = Column(Text, nullable=True)
    workshop_entered_at = Column(DateTime(timezone=True), nullable=True)
    current_activity = Column(String, nullable=True)
    current_activity_notes = Column(Text, nullable=True)
    current_activity_at = Column(DateTime(timezone=True), nullable=True)
    current_activity_by = Column(String, nullable=True)
    update_requested_at = Column(DateTime(timezone=True), nullable=True)
    update_requested_by = Column(String, nullable=True)
    update_request_note = Column(Text, nullable=True)
    job_purpose = Column(String, default="sold")

    # Status & Tracking
    status = Column(String, default="Submitted to Workshop")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    accepted_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    work_completed_at = Column(DateTime(timezone=True), nullable=True)
    pdi_completed_at = Column(DateTime(timezone=True), nullable=True)
    ready_for_delivery_sales_at = Column(DateTime(timezone=True), nullable=True)
    ready_for_delivery_workshop_at = Column(DateTime(timezone=True), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    delivered_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    archived_at = Column(DateTime(timezone=True), nullable=True)
    archived_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    archive_reason = Column(Text, nullable=True)
    admin_override = Column(Boolean, default=False)

    # Dual sign-offs
    pdi_signed_workshop = Column(Boolean, default=False)
    pdi_signed_workshop_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    pdi_signed_workshop_at = Column(DateTime(timezone=True), nullable=True)
    pdi_signed_sales = Column(Boolean, default=False)
    pdi_signed_sales_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    pdi_signed_sales_at = Column(DateTime(timezone=True), nullable=True)

    ready_sales = Column(Boolean, default=False)
    ready_workshop = Column(Boolean, default=False)
    ready_sales_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    ready_workshop_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    empty_signed_workshop = Column(Boolean, default=False)
    empty_signed_workshop_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    empty_signed_workshop_at = Column(DateTime(timezone=True), nullable=True)
    empty_signed_sales = Column(Boolean, default=False)
    empty_signed_sales_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    empty_signed_sales_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    created_by_user = relationship("User", back_populates="jobs_created", foreign_keys=[created_by])
    tasks = relationship("JobTask", back_populates="job_card", cascade="all, delete-orphan")
    pdi_items = relationship("PDIItem", back_populates="job_card", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="job_card")
    updates = relationship("JobUpdate", back_populates="job_card", cascade="all, delete-orphan")
    third_party_bookings = relationship("ThirdPartyBooking", back_populates="job_card", cascade="all, delete-orphan")
    parts = relationship("PartItem", back_populates="job_card", cascade="all, delete-orphan")
    supplies = relationship("SupplyItem", back_populates="job_card", cascade="all, delete-orphan")

class JobTask(Base):
    __tablename__ = "job_tasks"

    id = Column(Integer, primary_key=True, index=True)
    job_card_id = Column(Integer, ForeignKey("job_cards.id"), nullable=False)
    task_name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    is_custom = Column(Boolean, default=False)  # True if added by workshop or free-text
    needs_approval = Column(Boolean, default=False)
    approved_by_name = Column(String, nullable=True)
    status = Column(String, default="Not Started")
    notes = Column(Text, nullable=True)
    last_updated_by_name = Column(String, nullable=True)
    task_location = Column(String, nullable=True)
    third_party_provider = Column(String, nullable=True)
    booked_date = Column(String, nullable=True)
    test_result = Column(String, nullable=True)
    fail_list = Column(Text, nullable=True)
    # Who is doing the task (set when it moves to In Progress). Additive columns.
    responsible_user_id = Column(Integer, nullable=True)
    responsible_name = Column(String, nullable=True)
    assisting_names = Column(Text, nullable=True)
    paint_team = Column(String, nullable=True)
    assigned_at = Column(DateTime, nullable=True)
    assigned_by_name = Column(String, nullable=True)
    completed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    job_card = relationship("JobCard", back_populates="tasks")

class PDIItem(Base):
    __tablename__ = "pdi_items"

    id = Column(Integer, primary_key=True, index=True)
    job_card_id = Column(Integer, ForeignKey("job_cards.id"), nullable=False)
    section = Column(String, nullable=True)
    item_number = Column(Integer, nullable=True)
    check_item = Column(String, nullable=False)
    acceptance_criteria = Column(Text, nullable=True)
    status = Column(String, nullable=True)  # Pass / Fail / N/A
    notes = Column(Text, nullable=True)
    initials = Column(String, nullable=True)

    job_card = relationship("JobCard", back_populates="pdi_items")

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    job_card_id = Column(Integer, ForeignKey("job_cards.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    action = Column(String, nullable=False)
    details = Column(Text, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="audit_logs")
    job_card = relationship("JobCard", back_populates="audit_logs")

class IntegrityEvent(Base):
    """Overrides, bulk completions and reopens. Admin Overrides report reads this."""
    __tablename__ = "integrity_events"

    id = Column(Integer, primary_key=True, index=True)
    job_card_id = Column(Integer, ForeignKey("job_cards.id"), nullable=False)
    event_type = Column(String, nullable=False)
    side = Column(String, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    on_behalf_of = Column(Integer, ForeignKey("users.id"), nullable=True)
    reason = Column(Text, nullable=True)
    override = Column(Boolean, default=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    job_card = relationship("JobCard")
    user = relationship("User", foreign_keys=[user_id])


class ThirdPartyBooking(Base):
    __tablename__ = "third_party_bookings"

    id = Column(Integer, primary_key=True, index=True)
    job_card_id = Column(Integer, ForeignKey("job_cards.id"), nullable=False)
    service = Column(String, nullable=False)
    provider = Column(String, nullable=False)
    booked_date = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    created_by_name = Column(String, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    job_card = relationship("JobCard", back_populates="third_party_bookings")


class PartItem(Base):
    __tablename__ = "part_items"

    id = Column(Integer, primary_key=True, index=True)
    job_card_id = Column(Integer, ForeignKey("job_cards.id"), nullable=False)
    description = Column(String, nullable=False)
    order_number = Column(String, nullable=True)
    quantity = Column(String, nullable=True)
    price = Column(String, nullable=True)
    supplier_invoice = Column(String, nullable=True)
    part_progress = Column(String, default="To be ordered")
    ordered_date = Column(String, nullable=True)
    follow_up = Column(Boolean, default=False)
    follow_up_note = Column(Text, nullable=True)
    order_number_by = Column(String, nullable=True)
    created_by_name = Column(String, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    job_card = relationship("JobCard", back_populates="parts")

class SupplyItem(Base):
    __tablename__ = "supply_items"

    id = Column(Integer, primary_key=True, index=True)
    job_card_id = Column(Integer, ForeignKey("job_cards.id"), nullable=False)
    category = Column(String, nullable=False)
    item_type = Column(String, nullable=False)
    quantity = Column(String, default="1")
    notes = Column(Text, nullable=True)
    status = Column(String, default="Booked")
    created_by_name = Column(String, nullable=True)
    completed_by_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    job_card = relationship("JobCard", back_populates="supplies")


class JobUpdate(Base):
    """Permanent workshop/sales updates. Cannot be deleted once submitted."""
    __tablename__ = "job_updates"

    id = Column(Integer, primary_key=True, index=True)
    job_card_id = Column(Integer, ForeignKey("job_cards.id"), nullable=False)
    category = Column(String, nullable=False)  # extra_work, activity, parts, third_party, location, progress
    description = Column(String, nullable=False)
    notes = Column(Text, nullable=True)
    created_by_name = Column(String, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    job_card = relationship("JobCard", back_populates="updates")

class ThirdPartyCompany(Base):
    __tablename__ = "third_party_companies"

    id = Column(Integer, primary_key=True, index=True)
    category = Column(String, nullable=False)  # Barrel Test, Pressure Test, etc.
    name = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    job_card_id = Column(Integer, ForeignKey("job_cards.id"), nullable=True)
    message = Column(String, nullable=False)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    endpoint = Column(String, nullable=False, unique=True)
    p256dh = Column(String, nullable=False)
    auth = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class SupplierUpdate(Base):
    __tablename__ = "supplier_updates"

    id = Column(Integer, primary_key=True, index=True)
    job_card_id = Column(Integer, ForeignKey("job_cards.id"), nullable=False)
    task_id = Column(Integer, ForeignKey("job_tasks.id"), nullable=True)
    company = Column(String, nullable=False)
    status = Column(String, default="Booked")
    work_doing = Column(Text, nullable=True)
    parts_needed = Column(Text, nullable=True)
    note = Column(Text, nullable=True)
    photo_path = Column(String, nullable=True)
    workshop_parts_decision = Column(String, nullable=True)
    workshop_parts_note = Column(Text, nullable=True)
    created_by_name = Column(String, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class WorkshopStockOrder(Base):
    """Keep-on-hand workshop stock requested by the stock controller."""
    __tablename__ = "workshop_stock_orders"

    id = Column(Integer, primary_key=True, index=True)
    description = Column(String, nullable=False)
    quantity = Column(String, default="1")
    notes = Column(Text, nullable=True)
    status = Column(String, default="To be ordered")
    created_by_name = Column(String, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    ordered_date = Column(String, nullable=True)
    supplier_invoice = Column(String, nullable=True)
    stock_received_by = Column(String, nullable=True)
    stock_received_at = Column(DateTime(timezone=True), nullable=True)
    workshop_received_by = Column(String, nullable=True)
    workshop_received_at = Column(DateTime(timezone=True), nullable=True)
    last_updated_by = Column(String, nullable=True)
    update_requested_at = Column(DateTime(timezone=True), nullable=True)
    update_requested_by = Column(String, nullable=True)
    update_request_note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class WashRequest(Base):
    __tablename__ = "wash_requests"

    id = Column(Integer, primary_key=True, index=True)
    job_card_id = Column(Integer, ForeignKey("job_cards.id"), nullable=True)
    stock_number = Column(String, nullable=True)
    make = Column(String, nullable=True)
    vehicle_type = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    status = Column(String, default="Requested")
    requested_by_name = Column(String, nullable=True)
    requested_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class TaskPhoto(Base):
    """Workshop BEFORE / AFTER photos on a job task. Files live under UPLOAD_DIR/tasks/."""
    __tablename__ = "task_photos"

    id = Column(Integer, primary_key=True, index=True)
    job_card_id = Column(Integer, ForeignKey("job_cards.id"), nullable=False, index=True)
    task_id = Column(Integer, ForeignKey("job_tasks.id"), nullable=True)
    stage = Column(String, nullable=False)  # before / after
    photo_path = Column(String, nullable=False)  # relative to UPLOAD_DIR, e.g. tasks/12_ab12cd.jpg
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    uploaded_by_name = Column(String, nullable=True)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())

class PhotoArchive(Base):
    """One row per photo zip download. deleted_* is set when the photos are then removed from the app."""
    __tablename__ = "photo_archives"

    id = Column(Integer, primary_key=True, index=True)
    job_card_id = Column(Integer, ForeignKey("job_cards.id"), nullable=False, index=True)
    zip_name = Column(String, nullable=True)
    photo_count = Column(Integer, default=0)
    manifest = Column(Text, nullable=True)  # JSON list of photo keys in the zip
    downloaded_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    downloaded_by_name = Column(String, nullable=True)
    downloaded_at = Column(DateTime(timezone=True), server_default=func.now())
    deleted_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    deleted_by_name = Column(String, nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    deleted_count = Column(Integer, nullable=True)


class StockTake(Base):
    """Yard check round. closed_at is NULL for the current one; closed rounds are read-only."""
    __tablename__ = "stock_takes"

    id = Column(Integer, primary_key=True)
    started_at = Column(DateTime, server_default=func.now())
    started_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    started_by_name = Column(String, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    closed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    closed_by_name = Column(String, nullable=True)
    total_jobs = Column(Integer, nullable=True)
    on_site_count = Column(Integer, nullable=True)
    sticker_count = Column(Integer, nullable=True)
    results = Column(Text, nullable=True)  # JSON snapshot written when the round is closed
    source = Column(String, nullable=True)  # NULL/jobs = open job cards (original); list = yard stock list
    upload_id = Column(Integer, nullable=True)  # yard_stock_uploads.id (no FK: avoids a create-order cycle)


class StockTakeItem(Base):
    """One open job's ticks in a yard check round."""
    __tablename__ = "stock_take_items"
    __table_args__ = (UniqueConstraint("stock_take_id", "job_card_id"),)

    id = Column(Integer, primary_key=True)
    stock_take_id = Column(Integer, ForeignKey("stock_takes.id"), nullable=False)
    job_card_id = Column(Integer, ForeignKey("job_cards.id"), nullable=False)
    on_site = Column(Boolean, default=False)
    on_site_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    on_site_by_name = Column(String, nullable=True)
    on_site_at = Column(DateTime, nullable=True)
    sticker_fitted = Column(Boolean, default=False)
    sticker_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    sticker_by_name = Column(String, nullable=True)
    sticker_at = Column(DateTime, nullable=True)


class YardStockUpload(Base):
    """A parsed stock list awaiting or past confirmation. Only allow-listed fields are kept:
    no price, CRM, extras or mileage, and the uploaded file itself is never stored."""
    __tablename__ = "yard_stock_uploads"

    id = Column(Integer, primary_key=True)
    file_type = Column(String, nullable=False)  # pdf / xlsx
    file_name = Column(String, nullable=True)   # sanitised display name only
    row_count = Column(Integer, default=0)
    flagged_count = Column(Integer, default=0)
    preview = Column(Text, nullable=True)       # JSON: [{data, issues, include}], warnings, counts
    status = Column(String, default="preview")  # preview / confirmed / discarded
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    uploaded_by_name = Column(String, nullable=True)
    uploaded_at = Column(DateTime, server_default=func.now())
    confirmed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    confirmed_by_name = Column(String, nullable=True)
    confirmed_at = Column(DateTime, nullable=True)
    stock_take_id = Column(Integer, ForeignKey("stock_takes.id"), nullable=True)


class YardStockUnit(Base):
    """One vehicle on the yard stock list. Never hard-deleted; removal is a soft status."""
    __tablename__ = "yard_stock_units"

    id = Column(Integer, primary_key=True)
    stock_number = Column(String, nullable=False)      # as listed, spaces removed, upper case
    match_key = Column(String, nullable=True, index=True)  # conservative WS/CWS/SPWS key, see yard_stock_parser.match_key
    section = Column(String, nullable=True)
    year = Column(String, nullable=True)
    make = Column(String, nullable=True)
    model = Column(String, nullable=True)
    description = Column(String, nullable=True)
    registrations = Column(String, nullable=True)
    availability = Column(String, nullable=True)
    source = Column(String, nullable=False, default="upload")  # upload / single / yard_find
    status = Column(String, nullable=False, default="active")   # active / pending / rejected / removed / replaced
    upload_id = Column(Integer, ForeignKey("yard_stock_uploads.id"), nullable=True)
    listed_at = Column(DateTime, server_default=func.now())
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_by_name = Column(String, nullable=True)
    photo_path = Column(String, nullable=True)  # relative to UPLOAD_DIR, yard/<random>.<ext>
    photo_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    photo_by_name = Column(String, nullable=True)
    photo_at = Column(DateTime, nullable=True)
    decided_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    decided_by_name = Column(String, nullable=True)
    decided_at = Column(DateTime, nullable=True)
    decision_note = Column(Text, nullable=True)
    removed_at = Column(DateTime, nullable=True)
    removed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    removed_by_name = Column(String, nullable=True)
    removed_kind = Column(String, nullable=True)  # manual / delivered / replaced
    removed_reason = Column(Text, nullable=True)
    removed_job_id = Column(Integer, ForeignKey("job_cards.id"), nullable=True)


class YardUnitPhoto(Base):
    """Append-only photo log: who added or replaced a vehicle photo and when. Old files are kept."""
    __tablename__ = "yard_unit_photos"

    id = Column(Integer, primary_key=True)
    unit_id = Column(Integer, ForeignKey("yard_stock_units.id"), nullable=False, index=True)
    photo_path = Column(String, nullable=False)
    replaced_path = Column(String, nullable=True)
    added_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    added_by_name = Column(String, nullable=True)
    added_at = Column(DateTime, server_default=func.now())


class StockTakeUnitItem(Base):
    """Ticks for a stock-list unit in a list-based yard check round."""
    __tablename__ = "stock_take_unit_items"
    __table_args__ = (UniqueConstraint("stock_take_id", "unit_id"),)

    id = Column(Integer, primary_key=True)
    stock_take_id = Column(Integer, ForeignKey("stock_takes.id"), nullable=False)
    unit_id = Column(Integer, ForeignKey("yard_stock_units.id"), nullable=False)
    on_site = Column(Boolean, default=False)
    on_site_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    on_site_by_name = Column(String, nullable=True)
    on_site_at = Column(DateTime, nullable=True)
    sticker_fitted = Column(Boolean, default=False)
    sticker_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    sticker_by_name = Column(String, nullable=True)
    sticker_at = Column(DateTime, nullable=True)
