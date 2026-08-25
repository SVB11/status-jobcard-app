from .database import SessionLocal, engine, Base
from . import models
from .auth import get_password_hash

def seed_database():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    # Check if users already exist
    existing = db.query(models.User).first()
    if existing:
        print("Database already seeded.")
        db.close()
        return

    # Create initial users
    users = [
        # Admin
        models.User(
            username="admin",
            full_name="System Admin",
            hashed_password=get_password_hash("admin123"),
            role="admin"
        ),
        # Sales examples
        models.User(
            username="sales1",
            full_name="Sales Person 1",
            hashed_password=get_password_hash("sales123"),
            role="sales"
        ),
        models.User(
            username="sales2",
            full_name="Sales Person 2",
            hashed_password=get_password_hash("sales123"),
            role="sales"
        ),
        # Workshop examples
        models.User(
            username="workshop1",
            full_name="Workshop Tech 1",
            hashed_password=get_password_hash("workshop123"),
            role="workshop"
        ),
        models.User(
            username="workshop2",
            full_name="Workshop Tech 2",
            hashed_password=get_password_hash("workshop123"),
            role="workshop"
        ),
        # Accounts
        models.User(
            username="accounts",
            full_name="Accounts User",
            hashed_password=get_password_hash("accounts123"),
            role="accounts"
        ),
    ]

    for user in users:
        db.add(user)

    db.commit()
    print("Database seeded successfully with initial users.")
    print("\nLogin credentials:")
    print("  Admin     → username: admin     password: admin123")
    print("  Sales     → username: sales1    password: sales123")
    print("  Workshop  → username: workshop1 password: workshop123")
    print("  Accounts  → username: accounts  password: accounts123")
    db.close()

if __name__ == "__main__":
    seed_database()
