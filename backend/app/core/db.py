"""Database engine, session factory, and FastAPI dependency.

Usage:
    from app.core.db import get_db
    def my_route(db: Session = Depends(get_db)): ...
"""

from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


@lru_cache
def get_engine():
    """Return a cached SQLAlchemy engine built from settings."""
    settings = get_settings()
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        echo=False,
    )


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    """Return a cached session factory."""
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yield a database session and close it after the request."""
    factory = get_session_factory()
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ping_db() -> bool:
    """Return True if the DB is reachable and PostGIS is installed, else False."""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT PostGIS_Version()"))
        return True
    except Exception:
        return False
