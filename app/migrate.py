from sqlalchemy import text, inspect
from .database import engine

NEW_COLUMNS = {
    "users": {
        "must_change_password": "BOOLEAN",
        "supplier_company": "VARCHAR",
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
        "update_requested_at": "DATETIME",
        "update_requested_by": "VARCHAR",
        "update_request_note": "TEXT",
        "empty_signed_workshop": "BOOLEAN",
        "empty_signed_workshop_by": "INTEGER",
        "empty_signed_workshop_at": "DATETIME",
        "empty_signed_sales": "BOOLEAN",
        "empty_signed_sales_by": "INTEGER",
        "empty_signed_sales_at": "DATETIME",
        "job_purpose": "VARCHAR",
        "ready_sales_by": "INTEGER",
        "ready_workshop_by": "INTEGER",
        "archived_at": "DATETIME",
        "archived_by": "INTEGER",
        "archive_reason": "TEXT",
        "delivered_at": "DATETIME",
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
        "test_result": "VARCHAR",
        "fail_list": "TEXT",
    },
    "supplier_updates": {
        "photo_path": "VARCHAR",
    },
    "workshop_stock_orders": {
        "update_requested_at": "DATETIME",
        "update_requested_by": "VARCHAR",
        "update_request_note": "TEXT",
    },
    "wash_requests": {
        "stock_number": "VARCHAR",
        "make": "VARCHAR",
        "vehicle_type": "VARCHAR",
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
        if "wash_requests" in tables:
            info = conn.execute(text("PRAGMA table_info(wash_requests)")).fetchall()
            job_col = next((row for row in info if row[1] == "job_card_id"), None)
            # SQLite cannot drop NOT NULL. Rebuild so showroom washes need no job card.
            if job_col and job_col[3] == 1:
                conn.execute(text("""
                    CREATE TABLE wash_requests_new (
                        id INTEGER PRIMARY KEY,
                        job_card_id INTEGER,
                        stock_number VARCHAR,
                        make VARCHAR,
                        vehicle_type VARCHAR,
                        notes TEXT,
                        status VARCHAR,
                        requested_by_name VARCHAR,
                        requested_by INTEGER,
                        updated_by_name VARCHAR,
                        created_at DATETIME
                    )
                """))
                conn.execute(text("""
                    INSERT INTO wash_requests_new
                    (id, job_card_id, notes, status, requested_by_name, requested_by, updated_by_name, created_at)
                    SELECT id, job_card_id, notes, status, requested_by_name, requested_by, updated_by_name, created_at
                    FROM wash_requests
                """))
                conn.execute(text("DROP TABLE wash_requests"))
                conn.execute(text("ALTER TABLE wash_requests_new RENAME TO wash_requests"))
        if "users" in tables:
            user_cols = {c["name"] for c in inspector.get_columns("users")}
            if "password_plain" in user_cols:
                conn.execute(text("UPDATE users SET password_plain = NULL"))
                conn.execute(text("ALTER TABLE users DROP COLUMN password_plain"))
        if "job_cards" in tables:
            cols = {c["name"] for c in inspector.get_columns("job_cards")}
            if "archived_at" in cols:
                admin = conn.execute(text("SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1")).fetchone()
                admin_id = admin[0] if admin else 1
                rows = conn.execute(text("""
                    SELECT id, job_number FROM job_cards
                    WHERE archived_at IS NULL
                      AND (
                        current_location = 'Out / Delivered'
                        OR status IN ('Delivered / Closed', 'Delivered', 'Closed')
                      )
                """)).fetchall()
                for row in rows:
                    conn.execute(text("""
                        UPDATE job_cards
                        SET archived_at = CURRENT_TIMESTAMP,
                            archived_by = :uid,
                            archive_reason = 'Archived by migration',
                            status = 'Delivered / Closed',
                            current_location = 'Out / Delivered',
                            delivered_at = COALESCE(delivered_at, CURRENT_TIMESTAMP)
                        WHERE id = :jid
                    """), {"uid": admin_id, "jid": row[0]})
                    conn.execute(text("""
                        INSERT INTO job_updates (job_card_id, category, description, notes, created_by_name, created_by, created_at)
                        VALUES (:jid, 'progress', :desc, 'Archived by migration', 'System', :uid, CURRENT_TIMESTAMP)
                    """), {"jid": row[0], "uid": admin_id, "desc": f"Job delivered and archived {row[1]}"})
                    conn.execute(text("""
                        INSERT INTO audit_logs (job_card_id, user_id, action, details, timestamp)
                        VALUES (:jid, :uid, 'Job delivered and archived', :details, CURRENT_TIMESTAMP)
                    """), {"jid": row[0], "uid": admin_id, "details": f"{row[1]} Archived by migration"})
