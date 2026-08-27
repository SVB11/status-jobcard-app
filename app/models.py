from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, Float, Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base
import enum

class UserRole(str, enum.Enum):
    SALES = "sales"
    WORKSHOP = "workshop"
    ACCOUNTS = "accounts"
    ADMIN = "admin"

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
    role = Column(String, nullable=False)  # sales, workshop, accounts, admin
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

    # Dual sign-offs
    pdi_signed_workshop = Column(Boolean, default=False)
    pdi_signed_workshop_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    pdi_signed_workshop_at = Column(DateTime(timezone=True), nullable=True)
    pdi_signed_sales = Column(Boolean, default=False)
    pdi_signed_sales_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    pdi_signed_sales_at = Column(DateTime(timezone=True), nullable=True)

    ready_sales = Column(Boolean, default=False)
    ready_workshop = Column(Boolean, default=False)

    # Relationships
    created_by_user = relationship("User", back_populates="jobs_created", foreign_keys=[created_by])
    tasks = relationship("JobTask", back_populates="job_card", cascade="all, delete-orphan")
    pdi_items = relationship("PDIItem", back_populates="job_card", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="job_card")
    updates = relationship("JobUpdate", back_populates="job_card", cascade="all, delete-orphan")
    third_party_bookings = relationship("ThirdPartyBooking", back_populates="job_card", cascade="all, delete-orphan")
    parts = relationship("PartItem", back_populates="job_card", cascade="all, delete-orphan")

class JobTask(Base):
    __tablename__ = "job_tasks"

    id = Column(Integer, primary_key=True, index=True)
    job_card_id = Column(Integer, ForeignKey("job_cards.id"), nullable=False)
    task_name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    is_custom = Column(Boolean, default=False)  # True if added by workshop or free-text
    status = Column(String, default="Not Started")
    notes = Column(Text, nullable=True)
    task_location = Column(String, nullable=True)
    third_party_provider = Column(String, nullable=True)
    booked_date = Column(String, nullable=True)
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
    part_progress = Column(String, default="To be ordered")
    ordered_date = Column(String, nullable=True)
    follow_up = Column(Boolean, default=False)
    follow_up_note = Column(Text, nullable=True)
    created_by_name = Column(String, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    job_card = relationship("JobCard", back_populates="parts")

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

class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    job_card_id = Column(Integer, ForeignKey("job_cards.id"), nullable=True)
    message = Column(String, nullable=False)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
