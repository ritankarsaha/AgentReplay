"""Celery task wrapping the classifier (chunk 3.6).

Kept deliberately thin: all real logic lives in `classifier.py` (testable
directly, no Celery/Redis needed). This module is just the sync-Celery <->
async-SQLAlchemy adapter, plus `enqueue_classification()` — the one function
`routers/spans.py` calls, swappable in tests the same way
`exporter._build_client` is (see `tests/conftest.py`).
"""

from __future__ import annotations

import asyncio

from .celery_app import celery_app
from .classifier import classify_run_async
from .config import get_settings
from .db import make_engine, make_session_factory


async def _run(run_id: str) -> None:
    """Classify one run, using a fresh engine/connection pool for this call.

    Deliberately does NOT reuse `db.SessionLocal` (the FastAPI app's
    module-level engine, bound to its one long-lived event loop). Each
    Celery task invocation gets its own `asyncio.run()` — a brand new event
    loop every time — and asyncpg connections are pinned to the loop they
    were created on. Reusing a pooled connection across loops raises
    `RuntimeError: ... attached to a different loop` on the task's first
    real query (hit and confirmed live while verifying this chunk). A fresh
    engine per task, disposed afterward, costs a new connection per
    classification call instead of pooling across them — an acceptable
    trade for a task that fires once per failure, not a hot path.
    """
    settings = get_settings()
    engine = make_engine(settings.database_url, ssl_mode=settings.database_ssl_mode)
    try:
        session_factory = make_session_factory(engine)
        async with session_factory() as session:
            await classify_run_async(run_id, session, settings)
    finally:
        await engine.dispose()


@celery_app.task(name="agentreplay.classify_run")
def classify_run_task(run_id: str) -> None:
    asyncio.run(_run(run_id))


def enqueue_classification(run_id: str) -> None:
    """Enqueue `run_id` for classification. The one seam `routers/spans.py` calls.

    A plain function (not a direct `.delay()` call at the call site) so
    tests can monkeypatch this single name instead of mocking Celery/Redis —
    same pattern as `exporter._build_client`.
    """
    classify_run_task.delay(run_id)
