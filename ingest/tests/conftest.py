from __future__ import annotations

from typing import AsyncIterator

import httpx
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db, make_session_factory
from app.main import app
from app.models import Project

TEST_API_KEY = "test-api-key"
TEST_PROJECT_ID = "test-project"
OTHER_API_KEY = "other-api-key"
OTHER_PROJECT_ID = "other-project"


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    """An AsyncClient against the FastAPI app, backed by an isolated in-memory SQLite db.

    Seeds two projects (TEST_* and OTHER_*) so cross-tenant isolation can be tested.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = make_session_factory(engine)

    async def _get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _get_db

    async with session_factory() as session:
        session.add(Project(id=TEST_PROJECT_ID, name="Test Project", api_key=TEST_API_KEY))
        session.add(Project(id=OTHER_PROJECT_ID, name="Other Project", api_key=OTHER_API_KEY))
        await session.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    await engine.dispose()


def auth_headers(api_key: str = TEST_API_KEY) -> dict:
    return {"Authorization": f"Bearer {api_key}"}
