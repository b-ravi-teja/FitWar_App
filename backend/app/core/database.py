"""Async SQLAlchemy engine/session setup, the declarative base, and a DB health check.

`domain/` must never import this module — only `repositories/` and `core/deps.py` do.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import DateTime, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for every ORM model in the app.

    Every bare `Mapped[datetime]` column maps to `TIMESTAMPTZ`, not a naive
    timestamp — Architecture §11 requires all timestamps stored as UTC-aware, and
    this makes that the default instead of something each model has to remember.
    """

    type_annotation_map: ClassVar[dict[type, Any]] = {datetime: DateTime(timezone=True)}


def create_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        settings.database.url,
        pool_size=settings.database.pool_size,
        pool_pre_ping=True,
        echo=False,
    )


_engine: AsyncEngine = create_engine()
_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=_engine,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, committed on success, rolled back on error."""
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Explicit transaction helper for use outside the request lifecycle (workers, scripts)."""
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def database_healthy() -> bool:
    try:
        async with _engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def dispose_engine() -> None:
    await _engine.dispose()
