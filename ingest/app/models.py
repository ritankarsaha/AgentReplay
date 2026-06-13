from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, String, func
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
    api_key: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
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
    output: Mapped[Optional[dict]] = mapped_column(JSONVariant, nullable=True)
    error: Mapped[Optional[dict]] = mapped_column(JSONVariant, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False)
    fingerprint: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped["Run"] = relationship(back_populates="spans")
