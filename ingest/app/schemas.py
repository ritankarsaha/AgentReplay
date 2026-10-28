from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field

from .models import LoginEvent, RegressionCase, Run, SpanModel, TestResult



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

    # Optional: the API key already identifies the project. If supplied it
    # must match (routers/spans.py), which catches a mis-pasted key early.
    project_id: Optional[str] = None

    agent_version: Optional[str] = None
    framework: Optional[str] = None
    spans: List[SpanIn] = Field(max_length=5000)


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


class RegisterCaseRequest(BaseModel):
    """Body of `POST /v1/regression-cases` — promote a run's failure into a case."""

    run_id: str
    entrypoint: str
    title: Optional[str] = None
    priority: str = "P1"
    created_by: Optional[str] = None


class CaptureProductionRequest(BaseModel):
    """Body of `POST /v1/regression-cases/capture-production` — capture an
    incident with no full recorded run behind it.
    """

    entrypoint: str
    recorded_input: Any = None
    tool_spans: List[dict] = []
    assertion_spec: Optional[dict] = None
    title: Optional[str] = None
    priority: str = "P1"
    source_case_key: Optional[str] = None
    incident_id: Optional[str] = None
    external_url: Optional[str] = None
    observed_at: Optional[datetime] = None
    failure_class: Optional[str] = None
    created_by: Optional[str] = None


class UpdateCaseStatusRequest(BaseModel):
    """Body of `PATCH /v1/regression-cases/{case_id}` — a status transition."""

    status: str


class RegressionCaseOut(BaseModel):
    id: str
    project_id: str
    source_run_id: Optional[str]
    title: str
    entrypoint: str
    recorded_input: Any
    tool_spans: List[dict]
    assertion_spec: Optional[dict]
    priority: str
    status: str
    evidence_level: str
    source_case_key: Optional[str]
    incident_id: Optional[str]
    external_url: Optional[str]
    observed_at: Optional[datetime]
    created_by: Optional[str]
    metadata: dict
    created_at: datetime
    updated_at: datetime


class RegressionCaseListOut(BaseModel):
    cases: List[RegressionCaseOut]


class TestResultTrialOut(BaseModel):
    trial: int
    passed: bool
    error: Optional[str] = None
    duration_ms: float = 0.0


class RegisterResultRequest(BaseModel):
    """Body of `POST /v1/regression-cases/{case_id}/results`."""

    agent_version: Optional[str] = None
    trials: int
    passes: int
    verdict: str
    details: List[TestResultTrialOut] = []


class TestResultOut(BaseModel):
    id: str
    case_id: str
    agent_version: Optional[str]
    trials: int
    passes: int
    pass_rate: float
    verdict: str
    details: list
    judged_at: datetime
    created_at: datetime


class TestResultListOut(BaseModel):
    results: List[TestResultOut]


def regression_case_to_out(case: RegressionCase) -> RegressionCaseOut:
    return RegressionCaseOut(
        id=case.id,
        project_id=case.project_id,
        source_run_id=case.source_run_id,
        title=case.title,
        entrypoint=case.entrypoint,
        recorded_input=case.recorded_input,
        tool_spans=case.tool_spans,
        assertion_spec=case.assertion_spec,
        priority=case.priority,
        status=case.status,
        evidence_level=case.evidence_level,
        source_case_key=case.source_case_key,
        incident_id=case.incident_id,
        external_url=case.external_url,
        observed_at=case.observed_at,
        created_by=case.created_by,
        metadata=case.extra_metadata,
        created_at=case.created_at,
        updated_at=case.updated_at,
    )


def test_result_to_out(result: TestResult) -> TestResultOut:
    return TestResultOut(
        id=result.id,
        case_id=result.case_id,
        agent_version=result.agent_version,
        trials=result.trials,
        passes=result.passes,
        pass_rate=result.pass_rate,
        verdict=result.verdict,
        details=result.details,
        judged_at=result.judged_at,
        created_at=result.created_at,
    )


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
