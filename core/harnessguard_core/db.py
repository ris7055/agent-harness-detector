"""SQLAlchemy engine/session helpers and idempotent schema init (SPEC section 8.1)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings

_SCHEMA_SQL = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine, _session_factory
    if _engine is None:
        _engine = create_engine(get_settings().database_url, pool_pre_ping=True)
        _session_factory = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_session() -> Session:
    get_engine()
    assert _session_factory is not None
    return _session_factory()


def reset_engine() -> None:
    """Drop the cached engine/session factory (used by tests after changing DATABASE_URL)."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def _statements(sql: str) -> list[str]:
    out = []
    for chunk in sql.split(";"):
        body = "\n".join(
            line for line in chunk.splitlines() if not line.strip().startswith("--")
        ).strip()
        if body:
            out.append(body)
    return out


def init_db() -> None:
    """Apply schema.sql. Idempotent (CREATE TABLE/INDEX IF NOT EXISTS)."""
    engine = get_engine()
    with engine.begin() as conn:
        for stmt in _statements(_SCHEMA_SQL):
            conn.execute(text(stmt))
