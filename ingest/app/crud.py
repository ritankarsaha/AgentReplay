from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Set, Tuple

from sqlalchemy import Table, case, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .security import generate_api_key, generate_project_id, hash_api_key
from .models import Agent, Incident, LoginEvent, Project, RegressionCase, Run, SpanModel, TestResult
from .schemas import SpanIn

# Must match `agentreplay/fail.py`'s `FAIL_SPAN_TYPE`/`FAIL_SPAN_NAME` — the
# SDK's `agentreplay.fail()` (chunk 3.5) has no dedicated write endpoint; it
# rides the normal `POST /v1/spans` batch as a span with this exact
# (type, name), and `_failure_signals()` below recognizes it during ingest.
FAILURE_SPAN_TYPE = "checkpoint"
FAILURE_SPAN_NAME = "agentreplay.fail"

# Must match `controlplane/govern/monitor.py`.
HALT_SPAN_TYPE = "alert"
HALT_SPAN_NAME = "agentreplay.halt"
_INCIDENT_KINDS = {"scope_violation": "scope_violation", "spend_gate": "spend_breach"}


def _insert(session: AsyncSession, table: Table):
    """Dialect-appropriate `INSERT ... ON CONFLICT` builder (Postgres prod / SQLite tests)."""
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        return pg_insert(table)
    return sqlite_insert(table)


async def get_project_by_api_key(session: AsyncSession, api_key: str) -> Optional[Project]:
    return await session.scalar(
        select(Project).where(Project.api_key_hash == hash_api_key(api_key))
    )


async def get_project_for_owner(
    session: AsyncSession, *, project_id: str, owner_email: str
) -> Optional[Project]:
    return await session.scalar(
        select(Project).where(Project.id == project_id, Project.owner_email == owner_email)
    )


async def list_projects_for_owner(session: AsyncSession, *, owner_email: str) -> List[Project]:
    result = await session.scalars(
        select(Project).where(Project.owner_email == owner_email).order_by(Project.created_at)
    )
    return list(result)


async def create_project(
    session: AsyncSession, *, name: str, owner_email: Optional[str]
) -> Tuple[Project, str]:
    """Create a project and return it with its one-time plaintext API key."""
    api_key, key_hash, prefix = generate_api_key()
    project = Project(
        id=generate_project_id(),
        name=name,
        api_key_hash=key_hash,
        api_key_prefix=prefix,
        owner_email=owner_email,
    )
    session.add(project)
    await session.flush()
    return project, api_key


async def rotate_project_key(session: AsyncSession, project: Project) -> str:
    api_key, key_hash, prefix = generate_api_key()
    project.api_key_hash = key_hash
    project.api_key_prefix = prefix
    await session.flush()
    return api_key


class ForeignRunError(Exception):
    """A batch referenced a `run_id` that already belongs to another project."""


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
            # `halted` is terminal: a late batch must not downgrade it.
            "status": case(
                (table.c.status == "halted", "halted"),
                (stmt.excluded.status == "halted", "halted"),
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


def _halt_signals(spans: Sequence[SpanIn]) -> Dict[str, SpanIn]:
    """Latest `agentreplay.halt` alert span per run (the monitor's kill-switch signal)."""
    latest: Dict[str, SpanIn] = {}
    for span in spans:
        if span.type != HALT_SPAN_TYPE or span.name != HALT_SPAN_NAME:
            continue
        existing = latest.get(span.run_id)
        if existing is None or span.started_at >= existing.started_at:
            latest[span.run_id] = span
    return latest


async def _open_incidents(
    session: AsyncSession, *, project_id: str, halts: Dict[str, SpanIn]
) -> None:
    """One incident per halt alert; the alert span id is the incident id, so re-sends are no-ops."""
    if not halts:
        return
    agent_ids = {
        s.input.get("agent_id") for s in halts.values() if isinstance(s.input, dict) and s.input.get("agent_id")
    }
    known: Set[str] = set()
    if agent_ids:
        rows = await session.execute(
            select(Agent.id).where(Agent.project_id == project_id, Agent.id.in_(agent_ids))
        )
        known = {row[0] for row in rows}
    table = Incident.__table__
    for run_id, span in halts.items():
        payload = span.input if isinstance(span.input, dict) else {}
        agent_id = payload.get("agent_id")
        stmt = _insert(session, table).values(
            id=span.id,
            project_id=project_id,
            run_id=run_id,
            agent_id=agent_id if agent_id in known else None,
            kind=_INCIDENT_KINDS.get(payload.get("kind"), "scope_violation"),
            severity=payload.get("severity") or "high",
            culprit_span_id=payload.get("culprit_span_id"),
            status="open",
        )
        await session.execute(stmt.on_conflict_do_nothing(index_elements=[table.c.id]))


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

    # Tenancy guard: `runs.id` is globally unique, so without this a project
    # could append spans to (and bump) another project's run by reusing its id.
    batch_run_ids = {s.run_id for s in spans}
    owners = await session.execute(
        select(Run.id, Run.project_id).where(Run.id.in_(batch_run_ids))
    )
    if any(owner != project_id for _, owner in owners):
        raise ForeignRunError("run_id belongs to a different project")

    first_seen: dict[str, datetime] = {}
    last_seen: dict[str, datetime] = {}
    for span in spans:
        if span.run_id not in first_seen or span.started_at < first_seen[span.run_id]:
            first_seen[span.run_id] = span.started_at
        if span.run_id not in last_seen or span.started_at > last_seen[span.run_id]:
            last_seen[span.run_id] = span.started_at

    failure_signals = _failure_signals(spans)
    halt_signals = _halt_signals(spans)

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
            status="halted" if run_id in halt_signals else ("failure" if run_id in failure_signals else None),
            failure_class=failure_class,
            root_span_id=root_span_id,
        )

    accepted = await insert_spans(session, spans)
    await _open_incidents(session, project_id=project_id, halts=halt_signals)
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


async def list_regression_cases(
    session: AsyncSession,
    *,
    project_id: str,
    status: Optional[str] = None,
    limit: int = 100,
) -> List[RegressionCase]:
    """`status=None` returns every status; the CI gate always passes `status="active"`."""
    stmt = select(RegressionCase).where(RegressionCase.project_id == project_id)
    if status is not None:
        stmt = stmt.where(RegressionCase.status == status)
    stmt = stmt.order_by(RegressionCase.created_at.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_regression_case(
    session: AsyncSession, *, project_id: str, case_id: str
) -> Optional[RegressionCase]:
    stmt = select(RegressionCase).where(
        RegressionCase.project_id == project_id, RegressionCase.id == case_id
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def insert_test_result(
    session: AsyncSession,
    *,
    case_id: str,
    agent_version: Optional[str],
    trials: int,
    passes: int,
    verdict: str,
    details: list,
) -> TestResult:
    result = TestResult(
        id=str(uuid.uuid4()),
        case_id=case_id,
        agent_version=agent_version,
        trials=trials,
        passes=passes,
        pass_rate=(passes / trials) if trials else 0.0,
        verdict=verdict,
        details=details,
        created_at=datetime.now(timezone.utc),
        judged_at=datetime.now(timezone.utc),
    )
    session.add(result)
    await session.flush()
    await session.refresh(result)
    return result


async def list_test_results(
    session: AsyncSession, *, case_id: str, limit: int = 50
) -> List[TestResult]:
    stmt = (
        select(TestResult)
        .where(TestResult.case_id == case_id)
        .order_by(TestResult.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def insert_login_event(
    session: AsyncSession,
    *,
    project_id: str,
    email: str,
    name: Optional[str],
    image: Optional[str],
    provider: str,
) -> LoginEvent:
    event = LoginEvent(
        id=str(uuid.uuid4()),
        project_id=project_id,
        email=email,
        name=name,
        image=image,
        provider=provider,
    )
    session.add(event)
    await session.flush()
    await session.refresh(event)
    return event


async def list_login_events(session: AsyncSession, *, limit: int = 50) -> List[LoginEvent]:
    """All sign-ins, newest first -- an operator-wide audit log, not tenant data."""
    stmt = (
        select(LoginEvent)
        .order_by(LoginEvent.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
