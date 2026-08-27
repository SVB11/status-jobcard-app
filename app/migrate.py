from sqlalchemy import text, inspect
from .database import engine

NEW_COLUMNS = {
    "job_cards": {
        "vin_number": "VARCHAR",
        "registration_number": "VARCHAR",
        "third_party_place": "VARCHAR",
        "third_party_date": "VARCHAR",
        "parts_to_order": "TEXT",
        "workshop_entered_at": "DATETIME",
    }
}

def migrate_schema():
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    if "job_cards" not in tables:
        return
    existing = {c["name"] for c in inspector.get_columns("job_cards")}
    with engine.begin() as conn:
        for col, coltype in NEW_COLUMNS["job_cards"].items():
            if col not in existing:
                conn.execute(text(f"ALTER TABLE job_cards ADD COLUMN {col} {coltype}"))
