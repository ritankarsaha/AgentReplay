from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Sequence

from sqlalchemy import Table, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import Project, Run, SpanModel
from .schemas import SpanIn


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
) -> None:
    """Lazily create a `runs` row on first span seen for `run_id`, else bump `last_seen_at`.

    Resolves the open question in PROGRESS.md: the SDK sends spans only, no
    explicit run-start/run-end signal, so the ingest API derives `runs` rows
    from the spans themselves.

    `agent_version`/`framework` (CLAUDE.md §3.4) are set from the batch on
    insert. On conflict, a null value from a later batch never clobbers a
    previously-recorded value (`COALESCE(excluded, existing)`).
    """
    table = Run.__table__
    stmt = _insert(session, table).values(
        id=run_id,
        project_id=project_id,
        agent_version=agent_version,
        framework=framework,
        started_at=started_at,
        last_seen_at=last_seen_at,
        status="ok",
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[table.c.id],
        set_={
            "last_seen_at": stmt.excluded.last_seen_at,
            "agent_version": func.coalesce(stmt.excluded.agent_version, table.c.agent_version),
            "framework": func.coalesce(stmt.excluded.framework, table.c.framework),
        },
    )
    await session.execute(stmt)


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
) -> int:
    """Upsert the `runs` rows touched by this batch, then insert the spans."""
    if not spans:
        return 0

    first_seen: dict[str, datetime] = {}
    last_seen: dict[str, datetime] = {}
    for span in spans:
        if span.run_id not in first_seen or span.started_at < first_seen[span.run_id]:
            first_seen[span.run_id] = span.started_at
        if span.run_id not in last_seen or span.started_at > last_seen[span.run_id]:
            last_seen[span.run_id] = span.started_at

    for run_id, started_at in first_seen.items():
        await upsert_run(
            session,
            project_id=project_id,
            run_id=run_id,
            started_at=started_at,
            last_seen_at=last_seen[run_id],
            agent_version=agent_version,
            framework=framework,
        )

    return await insert_spans(session, spans)


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
