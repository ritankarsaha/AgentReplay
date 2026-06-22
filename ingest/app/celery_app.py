"""Celery app instance for the classifier (chunk 3.6, CLAUDE.md §2 "Redis/Celery").

`redis_url` doubles as both broker and result backend — one moving part for
v1, not a separate broker + separate backend. Run a worker with::

    celery -A app.celery_app worker --loglevel=info

(from `ingest/`, same venv as the FastAPI app — the worker imports `app.tasks`,
which imports the rest of the app package).
"""

from __future__ import annotations

from celery import Celery

from .config import get_settings

_settings = get_settings()

celery_app = Celery(
    "agentreplay_ingest",
    broker=_settings.redis_url,
    backend=_settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # Classification calls an external LLM API — don't let a stuck worker
    # process hold a task forever.
    task_time_limit=120,
    task_soft_time_limit=90,
)

# Importing registers `classify_run_task` with this app instance.
from . import tasks  # noqa: E402,F401
