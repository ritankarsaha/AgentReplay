from __future__ import annotations

from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import get_settings


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models (runs, spans, projects, ...)."""


def make_engine(database_url: str, echo: bool = False, ssl_mode: str = "require") -> AsyncEngine:
    connect_args = {}
    if database_url.startswith("postgresql+asyncpg"):
        if ssl_mode != "disable":

            connect_args["ssl"] = "require"

        connect_args["statement_cache_size"] = 0
    return create_async_engine(database_url, echo=echo, pool_pre_ping=True, connect_args=connect_args)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


_settings = get_settings()
engine: AsyncEngine = make_engine(
    _settings.database_url, echo=_settings.sql_echo, ssl_mode=_settings.database_ssl_mode
)
SessionLocal: async_sessionmaker[AsyncSession] = make_session_factory(engine)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped session.

    Commits on clean exit, rolls back on exception. Tests override this
    dependency with one bound to a temporary SQLite database.
    """
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
