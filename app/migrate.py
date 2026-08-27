from sqlalchemy import text, inspect
from .database import engine

NEW_COLUMNS = {
    "users": {
        "password_plain": "VARCHAR",
    },
    "job_cards": {
        "vin_number": "VARCHAR",
        "chassis_number": "VARCHAR",
        "registration_number": "VARCHAR",
        "third_party_place": "VARCHAR",
        "third_party_date": "VARCHAR",
        "parts_to_order": "TEXT",
        "workshop_entered_at": "DATETIME",
        "current_activity": "VARCHAR",
        "current_activity_notes": "TEXT",
        "current_activity_at": "DATETIME",
        "current_activity_by": "VARCHAR",
    },
    "part_items": {
        "quantity": "VARCHAR",
        "price": "VARCHAR",
        "supplier_invoice": "VARCHAR",
        "part_progress": "VARCHAR",
        "ordered_date": "VARCHAR",
        "follow_up": "BOOLEAN",
        "follow_up_note": "TEXT",
        "order_number_by": "VARCHAR",
    },
    "job_tasks": {
        "task_location": "VARCHAR",
        "third_party_provider": "VARCHAR",
        "booked_date": "VARCHAR",
        "last_updated_by_name": "VARCHAR",
        "needs_approval": "BOOLEAN",
        "approved_by_name": "VARCHAR",
    },
}

def migrate_schema():
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    with engine.begin() as conn:
        for table, cols in NEW_COLUMNS.items():
            if table not in tables:
                continue
            existing = {c["name"] for c in inspector.get_columns(table)}
            for col, coltype in cols.items():
                if col not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}"))
