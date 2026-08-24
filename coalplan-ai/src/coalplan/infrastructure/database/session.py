from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect, text
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
    _ensure_lightweight_sqlite_migrations(engine)
    _ensure_standard_search_indexes(engine)


def _ensure_lightweight_sqlite_migrations(engine) -> None:
    if engine.dialect.name != "sqlite":
        return
    inspector = inspect(engine)
    if "project_outline_nodes" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("project_outline_nodes")}
    with engine.begin() as connection:
        if "target_word_count" not in columns:
            connection.execute(text("ALTER TABLE project_outline_nodes ADD COLUMN target_word_count INTEGER"))
        additions = {
            "origin": "TEXT NOT NULL DEFAULT 'template'",
            "template_anchor_id": "TEXT",
            "source_hints_json": "TEXT NOT NULL DEFAULT '[]'",
            "matched_skill_keys_json": "TEXT NOT NULL DEFAULT '[]'",
            "chapter_summary_json": "TEXT NOT NULL DEFAULT '{}'",
        }
        for column, ddl in additions.items():
            if column not in columns:
                connection.execute(text(f"ALTER TABLE project_outline_nodes ADD COLUMN {column} {ddl}"))
    inspector = inspect(engine)
    if "constraint_atoms" in inspector.get_table_names():
        constraint_columns = {column["name"] for column in inspector.get_columns("constraint_atoms")}
        if "review_method" not in constraint_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE constraint_atoms ADD COLUMN review_method TEXT NOT NULL DEFAULT 'semantic_review'"))
    if "compliance_findings" in inspector.get_table_names():
        finding_columns = {column["name"] for column in inspector.get_columns("compliance_findings")}
        if "run_id" not in finding_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE compliance_findings ADD COLUMN run_id TEXT NOT NULL DEFAULT ''"))


def _ensure_standard_search_indexes(engine) -> None:
    """Create optional local FTS indexes used to shrink LLM candidate sets."""
    if engine.dialect.name != "sqlite":
        return
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if not {"standard_documents", "constraint_atoms"}.issubset(tables):
        return
    with engine.begin() as connection:
        try:
            connection.execute(text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS standard_document_search "
                "USING fts5(document_id UNINDEXED, search_text)"
            ))
            connection.execute(text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS constraint_atom_search "
                "USING fts5(atom_id UNINDEXED, document_id UNINDEXED, search_text)"
            ))
        except Exception:
            # SQLite builds without FTS5 continue through the existing LLM path.
            return
