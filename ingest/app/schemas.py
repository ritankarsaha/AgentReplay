from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel

from .models import LoginEvent, Run, SpanModel



class SpanIn(BaseModel):
    """Mirrors `agentreplay.span.Span.to_dict()` — the SDK wire format."""

    id: str
    run_id: str
    parent_id: Optional[str] = None
    type: str
    name: str
    input: dict
    # Any JSON value, not just objects: a `@agentreplay.tool`-decorated
    # function can return a list/str/int/etc., and `output jsonb` (§3.5)
    # accepts any JSON.
    output: Optional[Any] = None
    error: Optional[dict] = None
    started_at: datetime
    duration_ms: float
    fingerprint: str


class SpanBatchIn(BaseModel):
    """Body of `POST /v1/spans` — see `agentreplay/exporter.py` SPANS_PATH contract."""

    project_id: str

    agent_version: Optional[str] = None
    framework: Optional[str] = None
    spans: List[SpanIn]


class IngestResponse(BaseModel):
    accepted: int



class SpanOut(BaseModel):
    id: str
    run_id: str
    parent_id: Optional[str]
    type: str
    name: str
    input: dict
    output: Optional[Any]
    error: Optional[dict]
    started_at: datetime
    duration_ms: float
    fingerprint: Optional[str]


class RunOut(BaseModel):
    id: str
    project_id: str
    agent_version: Optional[str]
    framework: Optional[str]
    started_at: datetime
    last_seen_at: datetime
    status: str
    failure_class: Optional[str]
    root_span_id: Optional[str]
    metadata: dict
    classification_status: str
    diagnosis: Optional[dict] = None


class RunDetailOut(RunOut):
    spans: List[SpanOut]


class RunListOut(BaseModel):
    runs: List[RunOut]


class AssertionSpecOut(BaseModel):
    """`POST /v1/runs/{run_id}/assertion-spec` response (CLAUDE.md §4 chunk 4.3).

    Also what ends up nested under `RunOut.diagnosis["assertion_spec"]`
    once generated — no separate read endpoint needed, `diagnosis` already
    serializes the whole column.
    """

    must_call_tools: List[str]
    must_not_call_tools: List[str]
    max_steps: Optional[int]
    no_exception: bool
    rationale: str
    model: str
    semantic_rubric: Optional[str] = None


class GenerateTestRequest(BaseModel):
    """Body of `POST /v1/runs/{run_id}/generate-test` (CLAUDE.md §4 chunk 4.5).

    `entrypoint` can't be inferred server-side (the server never sees the
    user's agent code) — the viewer must prompt for it, same
    `"module.path:function_name"` convention the CLI's `--entrypoint` flag
    uses.
    """

    entrypoint: str


class GenerateTestOut(BaseModel):
    """`POST /v1/runs/{run_id}/generate-test` response — two file contents
    to display with copy/download buttons, not files written anywhere.
    """

    run_id: str
    fixture_filename: str
    fixture_source: str
    test_filename: str
    test_source: str
    assertion_spec: Optional[dict] = None


def span_to_out(span: SpanModel) -> SpanOut:
    return SpanOut(
        id=span.id,
        run_id=span.run_id,
        parent_id=span.parent_id,
        type=span.type,
        name=span.name,
        input=span.input,
        output=span.output,
        error=span.error,
        started_at=span.started_at,
        duration_ms=span.duration_ms,
        fingerprint=span.fingerprint,
    )


def run_to_out(run: Run) -> RunOut:
    return RunOut(
        id=run.id,
        project_id=run.project_id,
        agent_version=run.agent_version,
        framework=run.framework,
        started_at=run.started_at,
        last_seen_at=run.last_seen_at,
        status=run.status,
        failure_class=run.failure_class,
        root_span_id=run.root_span_id,
        metadata=run.extra_metadata,
        classification_status=run.classification_status,
        diagnosis=run.diagnosis,
    )


def run_to_detail_out(run: Run) -> RunDetailOut:
    base = run_to_out(run)
    return RunDetailOut(**base.model_dump(), spans=[span_to_out(s) for s in run.spans])


class LoginEventIn(BaseModel):
    """Body of `POST /v1/auth-events` — `web/auth.ts`'s `events.signIn`.

    No `id`/`project_id` (unlike `SpanIn`) -- the viewer has no natural id
    to assign, and project comes from the authenticated API key, not the
    body, matching the `generate-test` endpoint's convention.
    """

    email: str
    name: Optional[str] = None
    image: Optional[str] = None
    provider: str


class LoginEventOut(BaseModel):
    id: str
    project_id: str
    email: str
    name: Optional[str]
    image: Optional[str]
    provider: str
    created_at: datetime


class LoginEventListOut(BaseModel):
    events: List[LoginEventOut]


def login_event_to_out(event: LoginEvent) -> LoginEventOut:
    return LoginEventOut(
        id=event.id,
        project_id=event.project_id,
        email=event.email,
        name=event.name,
        image=event.image,
        provider=event.provider,
        created_at=event.created_at,
    )
