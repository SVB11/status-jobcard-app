from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
import shutil

DATABASE_URL = os.getenv("DATABASE_URL")
SQLITE_FILE = None

if DATABASE_URL and DATABASE_URL.startswith("postgres"):
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_DATABASE_URL = DATABASE_URL
    engine = create_engine(SQLALCHEMY_DATABASE_URL)
else:
    app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    local_db = os.path.join(app_root, "status_jobcard.db")
    data_db = "/data/status_jobcard.db"
    db_path = os.getenv("SQLITE_PATH")
    if not db_path:
        if os.path.isdir("/data"):
            if os.path.exists(data_db) and os.path.getsize(data_db) > 0:
                db_path = data_db
            elif os.path.exists(local_db) and os.path.getsize(local_db) > 1024:
                try:
                    shutil.copy2(local_db, data_db)
                    db_path = data_db
                except Exception:
                    db_path = local_db
            else:
                db_path = data_db
        else:
            db_path = local_db
    SQLALCHEMY_DATABASE_URL = f"sqlite:///{db_path}"
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
    )
    SQLITE_FILE = db_path

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
