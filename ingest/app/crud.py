from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Sequence, Set, Tuple

from sqlalchemy import Table, case, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import Project, Run, SpanModel
from .schemas import SpanIn

# Must match `agentreplay/fail.py`'s `FAIL_SPAN_TYPE`/`FAIL_SPAN_NAME` — the
# SDK's `agentreplay.fail()` (chunk 3.5) has no dedicated write endpoint; it
# rides the normal `POST /v1/spans` batch as a span with this exact
# (type, name), and `_failure_signals()` below recognizes it during ingest.
FAILURE_SPAN_TYPE = "checkpoint"
FAILURE_SPAN_NAME = "agentreplay.fail"


def _insert(session: AsyncSession, table: Table):
    """Dialect-appropriate `INSERT ... ON CONFLICT` builder (Postgres prod / SQLite tests)."""
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        return pg_insert(table)
    return sqlite_insert(table)


async def get_project_by_api_key(session: AsyncSession, api_key: str) -> Optional[Project]:
    return await session.scalar(select(Project).where(Project.api_key == api_key))


async def upsert_run(
    session: AsyncSession,
    *,
    project_id: str,
    run_id: str,
    started_at: datetime,
    last_seen_at: datetime,
    agent_version: Optional[str] = None,
    framework: Optional[str] = None,
    status: Optional[str] = None,
    failure_class: Optional[str] = None,
    root_span_id: Optional[str] = None,
) -> None:
    """Lazily create a `runs` row on first span seen for `run_id`, else bump `last_seen_at`.

    Resolves the open question in PROGRESS.md: the SDK sends spans only, no
    explicit run-start/run-end signal, so the ingest API derives `runs` rows
    from the spans themselves.

    `agent_version`/`framework` (CLAUDE.md §3.4) are set from the batch on
    insert. On conflict, a null value from a later batch never clobbers a
    previously-recorded value (`COALESCE(excluded, existing)`).

    `status` (chunk 3.5, `agentreplay.fail()`/auto-detect-on-exception) is
    `None` for a normal batch (defaults to `"ok"` on first insert, untouched
    on conflict) or `"failure"` when this batch carries a fail signal
    (`_failure_signals()`). Escalate-only: once a run is `"failure"`, a
    later batch without a fail signal can never flip it back to `"ok"`.
    `failure_class`/`root_span_id` use the same latest-non-null-wins
    COALESCE convention as `agent_version`/`framework`.
    """
    table = Run.__table__
    stmt = _insert(session, table).values(
        id=run_id,
        project_id=project_id,
        agent_version=agent_version,
        framework=framework,
        started_at=started_at,
        last_seen_at=last_seen_at,
        status=status or "ok",
        failure_class=failure_class,
        root_span_id=root_span_id,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[table.c.id],
        set_={
            "last_seen_at": stmt.excluded.last_seen_at,
            "agent_version": func.coalesce(stmt.excluded.agent_version, table.c.agent_version),
            "framework": func.coalesce(stmt.excluded.framework, table.c.framework),
            "status": case(
                (stmt.excluded.status == "failure", "failure"),
                else_=table.c.status,
            ),
            "failure_class": func.coalesce(stmt.excluded.failure_class, table.c.failure_class),
            "root_span_id": func.coalesce(stmt.excluded.root_span_id, table.c.root_span_id),
        },
    )
    await session.execute(stmt)


def _failure_signals(spans: Sequence[SpanIn]) -> Dict[str, Tuple[Optional[str], Optional[str]]]:
    """Scan a span batch for `agentreplay.fail()` signals, keyed by `run_id`.

    Returns `{run_id: (failure_class, root_span_id)}` for every run with at
    least one matching span in this batch. If a run has more than one (e.g.
    the caller invoked `agentreplay.fail()` twice), the chronologically
    latest one wins — same "most recent wins" intuition as
    `upsert_run`'s COALESCE fields, just resolved within the batch first.
    """
    latest: Dict[str, Tuple[Optional[str], Optional[str], datetime]] = {}
    for span in spans:
        if span.type != FAILURE_SPAN_TYPE or span.name != FAILURE_SPAN_NAME:
            continue
        failure_class = span.input.get("failure_class") if span.input else None
        root_span_id = (span.input.get("span_id") if span.input else None) or span.id
        existing = latest.get(span.run_id)
        if existing is None or span.started_at >= existing[2]:
            latest[span.run_id] = (failure_class, root_span_id, span.started_at)
    return {run_id: (fc, rsid) for run_id, (fc, rsid, _) in latest.items()}


async def insert_spans(session: AsyncSession, spans: Sequence[SpanIn]) -> int:
    """Bulk-insert spans, skipping any whose `id` already exists (idempotent re-sends)."""
    if not spans:
        return 0

    table = SpanModel.__table__
    rows = [
        {
            "id": s.id,
            "run_id": s.run_id,
            "parent_id": s.parent_id,
            "type": s.type,
            "name": s.name,
            "input": s.input,
            "output": s.output,
            "error": s.error,
            "started_at": s.started_at,
            "duration_ms": s.duration_ms,
            "fingerprint": s.fingerprint,
        }
        for s in spans
    ]
    stmt = _insert(session, table).values(rows)
    stmt = stmt.on_conflict_do_nothing(index_elements=[table.c.id])
    await session.execute(stmt)
    return len(rows)


async def ingest_batch(
    session: AsyncSession,
    *,
    project_id: str,
    spans: Sequence[SpanIn],
    agent_version: Optional[str] = None,
    framework: Optional[str] = None,
) -> Tuple[int, Set[str]]:
    """Upsert the `runs` rows touched by this batch, then insert the spans.

    Returns `(accepted_span_count, failed_run_ids)` — the second element is
    every `run_id` with an `agentreplay.fail()` signal in *this* batch
    (chunk 3.5), so the caller (`routers/spans.py`) knows which runs to
    enqueue for classification (chunk 3.6). Includes runs already
    `status="failure"` from an earlier batch, not just newly-failed ones —
    harmless to re-enqueue, since `classify_run_async` is idempotent.
    """
    if not spans:
        return 0, set()

    first_seen: dict[str, datetime] = {}
    last_seen: dict[str, datetime] = {}
    for span in spans:
        if span.run_id not in first_seen or span.started_at < first_seen[span.run_id]:
            first_seen[span.run_id] = span.started_at
        if span.run_id not in last_seen or span.started_at > last_seen[span.run_id]:
            last_seen[span.run_id] = span.started_at

    failure_signals = _failure_signals(spans)

    for run_id, started_at in first_seen.items():
        failure_class, root_span_id = failure_signals.get(run_id, (None, None))
        await upsert_run(
            session,
            project_id=project_id,
            run_id=run_id,
            started_at=started_at,
            last_seen_at=last_seen[run_id],
            agent_version=agent_version,
            framework=framework,
            status="failure" if run_id in failure_signals else None,
            failure_class=failure_class,
            root_span_id=root_span_id,
        )

    accepted = await insert_spans(session, spans)
    return accepted, set(failure_signals.keys())


async def list_runs(session: AsyncSession, *, project_id: str, limit: int = 50) -> List[Run]:
    stmt = (
        select(Run)
        .where(Run.project_id == project_id)
        .order_by(Run.started_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_run_with_spans(session: AsyncSession, *, project_id: str, run_id: str) -> Optional[Run]:
    stmt = (
        select(Run)
        .options(selectinload(Run.spans))
        .where(Run.project_id == project_id, Run.id == run_id)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_run_with_spans_by_id(session: AsyncSession, *, run_id: str) -> Optional[Run]:
    """Project-agnostic lookup for the classifier (chunk 3.6).

    Unlike `get_run_with_spans`, not scoped by `project_id` — the Celery
    worker (`tasks.py`) is an internal, trusted caller (it only ever
    receives a `run_id` it generated itself when enqueueing), not a request
    on behalf of an API-key-authenticated project.
    """
    stmt = select(Run).options(selectinload(Run.spans)).where(Run.id == run_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()
