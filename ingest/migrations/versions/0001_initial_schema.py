"""initial schema: projects, runs, spans

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-06-12

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("api_key", sa.String(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_projects_api_key", "projects", ["api_key"], unique=True)

    op.create_table(
        "runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("agent_version", sa.String(), nullable=True),
        sa.Column("framework", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="ok"),
        sa.Column("failure_class", sa.String(), nullable=True),
        sa.Column("root_span_id", sa.String(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_runs_project_id", "runs", ["project_id"])
    op.create_index("ix_runs_started_at", "runs", ["started_at"])

    op.create_table(
        "spans",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "run_id", sa.String(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("parent_id", sa.String(), nullable=True),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("input", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("output", postgresql.JSONB(), nullable=True),
        sa.Column("error", postgresql.JSONB(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("fingerprint", sa.String(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_spans_run_id", "spans", ["run_id"])
    op.create_index("ix_spans_parent_id", "spans", ["parent_id"])
    op.create_index("ix_spans_fingerprint", "spans", ["fingerprint"])


def downgrade() -> None:
    op.drop_index("ix_spans_fingerprint", table_name="spans")
    op.drop_index("ix_spans_parent_id", table_name="spans")
    op.drop_index("ix_spans_run_id", table_name="spans")
    op.drop_table("spans")

    op.drop_index("ix_runs_started_at", table_name="runs")
    op.drop_index("ix_runs_project_id", table_name="runs")
    op.drop_table("runs")

    op.drop_index("ix_projects_api_key", table_name="projects")
    op.drop_table("projects")
