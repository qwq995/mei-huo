from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import sessionmaker

from .models import Base


def sqlite_url_for_storage(storage_dir: Path) -> str:
    path = storage_dir / "coalplan.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path.as_posix()}"


def create_session_factory(database_url: str):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    poolclass = NullPool if database_url.startswith("sqlite") else None
    engine = create_engine(database_url, connect_args=connect_args, poolclass=poolclass, future=True)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def init_database(session_factory) -> None:
    engine = session_factory.kw["bind"]
    Base.metadata.create_all(engine)
