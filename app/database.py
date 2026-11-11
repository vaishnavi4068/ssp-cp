"""Database engine, session management, and migration runner for SPP Control Plane (`ssp-cp`).

Supports:
- AlloyDB for PostgreSQL via env vars / Secret Manager (ADR-GLB-004, ADR-GLB-005).
- Plain PostgreSQL URL (`DATABASE_URL`) for local/CI tests.
"""

from __future__ import annotations

from collections.abc import Generator

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings

_ENGINE: Engine | None = None
_SESSION_LOCAL: sessionmaker | None = None


def run_alembic_upgrade(database_url: str) -> None:
    """Run Alembic migrations (`upgrade head`) against the target PostgreSQL / AlloyDB database."""
    repo_root = get_settings().repo_root
    alembic_ini = repo_root / "alembic.ini"
    cfg = Config(str(alembic_ini))
    cfg.set_main_option("script_location", str(repo_root / "db" / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")


def init_engine(database_url: str | None = None, run_migrations: bool = True) -> Engine:
    global _ENGINE, _SESSION_LOCAL
    url = database_url or get_settings().database_url
    _ENGINE = create_engine(url, pool_pre_ping=True, future=True)
    _SESSION_LOCAL = sessionmaker(bind=_ENGINE, autoflush=False, autocommit=False, expire_on_commit=False)
    if run_migrations:
        run_alembic_upgrade(url)
    return _ENGINE


def get_engine() -> Engine:
    global _ENGINE
    if _ENGINE is None:
        init_engine()
    assert _ENGINE is not None
    return _ENGINE


def get_session_factory() -> sessionmaker:
    global _SESSION_LOCAL
    if _SESSION_LOCAL is None:
        init_engine()
    assert _SESSION_LOCAL is not None
    return _SESSION_LOCAL


def get_db() -> Generator[Session, None, None]:
    session_factory = get_session_factory()
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


def check_db_ready(db: Session) -> bool:
    try:
        db.execute(text("SELECT 1 FROM idp.resource_kind LIMIT 1"))
        return True
    except Exception:
        return False
