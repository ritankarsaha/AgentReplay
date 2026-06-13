from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel

from .models import Run, SpanModel



class SpanIn(BaseModel):
    """Mirrors `agentreplay.span.Span.to_dict()` — the SDK wire format."""

    id: str
    run_id: str
    parent_id: Optional[str] = None
    type: str
    name: str
    input: dict
    output: Optional[dict] = None
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
    output: Optional[dict]
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


class RunDetailOut(RunOut):
    spans: List[SpanOut]


class RunListOut(BaseModel):
    runs: List[RunOut]


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
    )


def run_to_detail_out(run: Run) -> RunDetailOut:
    base = run_to_out(run)
    return RunDetailOut(**base.model_dump(), spans=[span_to_out(s) for s in run.spans])
