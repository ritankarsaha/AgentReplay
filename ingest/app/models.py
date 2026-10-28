from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class Project(Base):
    """Maps an API key to a project, for ingest auth (§7 multi-tenancy)."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # sha256 of the API key (app/security.py) -- the plaintext is shown once
    # at creation/rotation and never stored. `api_key_prefix` is the
    # non-secret display prefix. `owner_email` is the viewer user who owns
    # the project (NULL for operator-created projects, reachable only by
    # their API key).
    api_key_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    api_key_prefix: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    owner_email: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Run(Base):
    """One agent run (§3.5). Lazily created from the first span we see for `run_id`."""

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    agent_version: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    framework: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="ok", server_default="ok")
    failure_class: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    root_span_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    extra_metadata: Mapped[dict] = mapped_column(
        "metadata", JSONVariant, nullable=False, default=dict, server_default="{}"
    )

    # Chunk 3.6 — Sonnet/MAST classifier (CLAUDE.md §3.6). `failure_class`/
    # `root_span_id` above double as the classifier's output fields too (it
    # overwrites them with its own verdict); `classification_status`/
    # `diagnosis` are additive. `classification_status` is one of
    # "none" (default, not classified — either not a failure, or a failure
    # not yet picked up by a worker), "done", or "error" — see
    # `app/classifier.py`. `diagnosis` is the full classifier output blob
    # (human-readable text, suggested assertion, model/backend used,
    # timestamp; or the error message on failure) — see that module's
    # docstring for the exact shape.
    classification_status: Mapped[str] = mapped_column(
        String, nullable=False, default="none", server_default="none"
    )
    diagnosis: Mapped[Optional[dict]] = mapped_column(JSONVariant, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    spans: Mapped[list["SpanModel"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )


class SpanModel(Base):
    """One recorded unit of work (§3.5), as exported by `agentreplay.exporter`."""

    __tablename__ = "spans"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    type: Mapped[str] = mapped_column(String, nullable=False)  # llm | tool | node | checkpoint
    name: Mapped[str] = mapped_column(String, nullable=False)
    input: Mapped[dict] = mapped_column(JSONVariant, nullable=False, default=dict)
    # Any JSON value (object/array/scalar) — see SpanIn.output in schemas.py.
    output: Mapped[Optional[Any]] = mapped_column(JSONVariant, nullable=True)
    error: Mapped[Optional[dict]] = mapped_column(JSONVariant, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False)
    fingerprint: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped["Run"] = relationship(back_populates="spans")


class RegressionCase(Base):
    """One regression case. `status` is a state machine (proposed ->
    active -> muted/archived, or -> rejected from proposed) — see
    `app/regression.py:can_transition()`. `source_run_id` is set when
    promoted from a recorded run; `source_case_key`/`incident_id`/
    `external_url`/`observed_at` are set instead for a captured production
    incident with no run behind it. `recorded_input`/`tool_spans` are
    snapshotted onto the case so it keeps working even if the source
    run/trace is later pruned.
    """

    __tablename__ = "regression_cases"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    source_run_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)

    title: Mapped[str] = mapped_column(String, nullable=False)
    entrypoint: Mapped[str] = mapped_column(String, nullable=False)
    recorded_input: Mapped[Any] = mapped_column(JSONVariant, nullable=True)
    tool_spans: Mapped[list] = mapped_column(JSONVariant, nullable=False, default=list)
    assertion_spec: Mapped[Optional[dict]] = mapped_column(JSONVariant, nullable=True)

    # P0 | P1 | P2
    priority: Mapped[str] = mapped_column(String, nullable=False, default="P1", server_default="P1")
    # proposed | active | muted | archived | rejected
    status: Mapped[str] = mapped_column(String, nullable=False, default="proposed", server_default="proposed")

    # native_structured (full recorded trace) | derived_summary (captured, partial evidence)
    evidence_level: Mapped[str] = mapped_column(
        String, nullable=False, default="native_structured", server_default="native_structured"
    )
    source_case_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    incident_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    external_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    observed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    extra_metadata: Mapped[dict] = mapped_column(
        "metadata", JSONVariant, nullable=False, default=dict, server_default="{}"
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    test_results: Mapped[list["TestResult"]] = relationship(
        back_populates="case", cascade="all, delete-orphan", passive_deletes=True
    )


class TestResult(Base):
    """One N-trial regression-case run. `details` holds the per-trial
    breakdown (`[{trial, passed, error, duration_ms}, ...]`); `verdict`
    mirrors `agentreplay.regression.gate.Verdict` as a plain string.
    """

    __tablename__ = "test_results"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("regression_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_version: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    trials: Mapped[int] = mapped_column(Integer, nullable=False)
    passes: Mapped[int] = mapped_column(Integer, nullable=False)
    pass_rate: Mapped[float] = mapped_column(Float, nullable=False)
    verdict: Mapped[str] = mapped_column(String, nullable=False)
    details: Mapped[list] = mapped_column(JSONVariant, nullable=False, default=list)
    judged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    case: Mapped["RegressionCase"] = relationship(back_populates="test_results")


class LoginEvent(Base):
    """One viewer Google sign-in (`web/auth.ts`'s `events.signIn`).

    Written by the Next.js viewer, not the SDK -- unrelated to `runs`/
    `spans`. Exists because the viewer's Auth.js config uses JWT-only
    sessions (no database adapter), so without this there is no durable
    record anywhere of who has signed in.
    """

    __tablename__ = "login_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    image: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
