"""Regression-case lifecycle.

Two ways a case comes into existence: `create_case_from_run()` promotes an
already-recorded run's failure; `create_case_from_capture()` captures a
production incident with no full recorded run behind it. Both create a
`proposed` case — never silently `active` — funneling into the
`proposed -> active -> muted/archived` (or `-> rejected`) status machine
enforced by `can_transition()`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from agentreplay.testgen.fixture import build_fixture_data

from .assertion_spec import generate_assertion_spec_for_run
from .config import Settings
from .models import RegressionCase, Run
from .testgen import span_to_fixture_dict, validate_entrypoint_shape

_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "proposed": {"active", "rejected"},
    "active": {"muted", "archived"},
    "muted": {"active", "archived"},
    "archived": set(),
    "rejected": set(),
}

VALID_STATUSES = frozenset(_ALLOWED_TRANSITIONS.keys())
VALID_PRIORITIES = frozenset({"P0", "P1", "P2"})


class InvalidStatusTransition(Exception):
    """Raised by `apply_status_transition()` for a not-allowed status edge."""

    def __init__(self, current: str, target: str) -> None:
        super().__init__(
            f"cannot transition a regression case from '{current}' to '{target}' "
            f"(allowed from '{current}': {sorted(_ALLOWED_TRANSITIONS.get(current, set())) or 'none'})"
        )
        self.current = current
        self.target = target


def can_transition(current: str, target: str) -> bool:
    return target in _ALLOWED_TRANSITIONS.get(current, set())


def apply_status_transition(case: RegressionCase, target: str) -> None:
    if target not in VALID_STATUSES:
        raise ValueError(f"'{target}' is not a valid status (one of {sorted(VALID_STATUSES)})")
    if not can_transition(case.status, target):
        raise InvalidStatusTransition(case.status, target)
    case.status = target


async def create_case_from_run(
    run: Run,
    session: AsyncSession,
    settings: Settings,
    *,
    entrypoint: str,
    title: Optional[str] = None,
    priority: str = "P1",
    created_by: Optional[str] = None,
) -> RegressionCase:
    """Promote `run`'s failure into a `proposed` regression case.

    `run` must already have its `.spans` loaded. Generates an assertion spec
    first if `run` doesn't already have one (raises `RunNotClassifiedError`/
    `AssertionSpecNotConfigured` uncaught). Raises `EntrypointFormatError`
    first for a malformed `entrypoint`.
    """
    validate_entrypoint_shape(entrypoint)

    diagnosis = run.diagnosis or {}
    assertion_spec = diagnosis.get("assertion_spec")
    if assertion_spec is None:
        spec = await generate_assertion_spec_for_run(run, session, settings)
        assertion_spec = spec.to_dict()

    fixture = build_fixture_data(run.id, [span_to_fixture_dict(s) for s in run.spans])

    case = RegressionCase(
        id=str(uuid.uuid4()),
        project_id=run.project_id,
        source_run_id=run.id,
        title=title or f"Regression case from run {run.id}",
        entrypoint=entrypoint,
        recorded_input=fixture.recorded_input,
        tool_spans=fixture.tool_spans,
        assertion_spec=assertion_spec,
        priority=priority,
        status="proposed",
        evidence_level="native_structured",
        created_by=created_by,
    )
    session.add(case)
    await session.flush()
    await session.refresh(case)
    return case


async def create_case_from_capture(
    session: AsyncSession,
    *,
    project_id: str,
    entrypoint: str,
    recorded_input: Any,
    tool_spans: Optional[list] = None,
    assertion_spec: Optional[dict] = None,
    title: Optional[str] = None,
    priority: str = "P1",
    source_case_key: Optional[str] = None,
    incident_id: Optional[str] = None,
    external_url: Optional[str] = None,
    observed_at: Optional[datetime] = None,
    failure_class: Optional[str] = None,
    created_by: Optional[str] = None,
) -> RegressionCase:
    """Capture a production incident into a `proposed` case with no source run.

    `evidence_level="derived_summary"` distinguishes this from a run-backed
    case (`"native_structured"`). Raises `EntrypointFormatError` for a
    malformed `entrypoint`.
    """
    validate_entrypoint_shape(entrypoint)

    case = RegressionCase(
        id=str(uuid.uuid4()),
        project_id=project_id,
        source_run_id=None,
        title=title or f"Captured incident {source_case_key or incident_id or 'unlabeled'}",
        entrypoint=entrypoint,
        recorded_input=recorded_input,
        tool_spans=tool_spans or [],
        assertion_spec=assertion_spec,
        priority=priority,
        status="proposed",
        evidence_level="derived_summary",
        source_case_key=source_case_key,
        incident_id=incident_id,
        external_url=external_url,
        observed_at=observed_at,
        created_by=created_by,
        extra_metadata={"failure_class": failure_class} if failure_class else {},
    )
    session.add(case)
    await session.flush()
    await session.refresh(case)
    return case
