from __future__ import annotations

from typing import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db import Base, get_db, make_session_factory
from app.main import app
from app.models import Project
from app.security import hash_api_key, rate_limiter


@pytest.fixture(autouse=True)
def _isolate_settings_from_real_env_file(monkeypatch):

    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("AGENTREPLAY_INGEST_VIEWER_SERVICE_TOKEN", VIEWER_TOKEN)
    rate_limiter.reset()

TEST_API_KEY = "test-api-key"
TEST_PROJECT_ID = "test-project"
OTHER_API_KEY = "other-api-key"
OTHER_PROJECT_ID = "other-project"
OWNER_EMAIL = "owner@example.com"
VIEWER_TOKEN = "test-viewer-token"


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
        session.add(Project(id=TEST_PROJECT_ID, name="Test Project", api_key_hash=hash_api_key(TEST_API_KEY), owner_email=OWNER_EMAIL))
        session.add(Project(id=OTHER_PROJECT_ID, name="Other Project", api_key_hash=hash_api_key(OTHER_API_KEY), owner_email="other@example.com"))
        await session.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    await engine.dispose()


def auth_headers(api_key: str = TEST_API_KEY) -> dict:
    return {"Authorization": f"Bearer {api_key}"}


def viewer_headers(email: str = OWNER_EMAIL, project_id: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {VIEWER_TOKEN}", "X-Viewer-Email": email}
    if project_id:
        headers["X-Project-Id"] = project_id
    return headers
