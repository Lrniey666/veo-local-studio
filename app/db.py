from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .paths import DATA_DIR, ensure_runtime_dirs

ensure_runtime_dirs()
DB_PATH = DATA_DIR / "veo_app.db"
DATABASE_URL = f"sqlite:///{DB_PATH.as_posix()}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
