from .database import SessionLocal, engine, Base
from . import models
from .auth import get_password_hash

STAFF = [
    # Sales
    ("calvin", "Calvin Kempenaar", "sales", "Calvin123"),
    ("rob", "Rob Ling", "sales", "Rob123"),
    ("drickus", "Drickus van Biljon", "sales", "Drickus123"),
    ("stanley", "Stanley Johnson", "sales", "Stanley123"),
    ("sebastian_sales", "Sebastian van Biljon", "sales", "Sebastian123"),
    # Workshop
    ("jean", "Jean-Pierre De Fillet", "workshop", "Jean123"),
    ("tiaan", "Tiaan Van Wyk", "workshop", "Tiaan123"),
    ("louis", "Louis Koekemoer", "workshop", "Louis123"),
    # Admin (Sebastian listed in sales and admin — admin covers both)
    ("tanita", "Tanita van Biljon", "admin", "Tanita123"),
    ("siegfried", "Siegfried van Biljon", "admin", "Siegfried123"),
    ("chantelle", "Chantelle Willemse", "admin", "Chantelle123"),
    ("sebastian", "Sebastian van Biljon", "admin", "Sebastian123"),
    # Accounts
    ("cindy", "Cindy van Biljon", "accounts", "Cindy123"),
    # Keep a system admin login
    ("admin", "System Admin", "admin", "admin123"),
]

def seed_database():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    added = []
    for username, full_name, role, password in STAFF:
        exists = db.query(models.User).filter(models.User.username == username).first()
        if exists:
            if not getattr(exists, "password_plain", None):
                exists.password_plain = password
            continue
        db.add(models.User(
            username=username,
            full_name=full_name,
            hashed_password=get_password_hash(password),
            password_plain=password,
            must_change_password=False,
            role=role
        ))
        added.append(username)
    db.commit()
    if added:
        print("Added users:", ", ".join(added))
    else:
        print("All staff users already exist.")
    db.close()

if __name__ == "__main__":
    seed_database()
