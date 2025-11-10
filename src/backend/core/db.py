"""Database utilities built on SQLAlchemy 2.0."""
from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

from .config import get_settings

SettingsT = get_settings()

engine_kwargs: dict[str, object] = {"pool_pre_ping": True}
if SettingsT.database_url.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
    if ":memory:" in SettingsT.database_url:
        engine_kwargs["poolclass"] = StaticPool
    else:
        engine_kwargs["poolclass"] = NullPool

engine = create_engine(SettingsT.database_url, **engine_kwargs)

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)

class Base(DeclarativeBase):
    pass


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """Provide a transactional scope around a series of operations."""

    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:  # pragma: no cover - defensive rollback
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Create database tables if they do not exist."""

    # Import models lazily to avoid circular imports.
    from ..models import user  # noqa: F401

    Base.metadata.create_all(bind=engine)
