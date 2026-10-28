"""add regression_cases and test_results tables

Revision ID: 0005_add_regression_cases
Revises: 0004_add_login_events
Create Date: 2026-09-29

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_add_regression_cases"
down_revision: Union[str, None] = "0004_add_login_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "regression_cases",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("source_run_id", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("entrypoint", sa.String(), nullable=False),
        sa.Column("recorded_input", postgresql.JSONB(), nullable=True),
        sa.Column("tool_spans", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("assertion_spec", postgresql.JSONB(), nullable=True),
        sa.Column("priority", sa.String(), nullable=False, server_default="P1"),
        sa.Column("status", sa.String(), nullable=False, server_default="proposed"),
        sa.Column("evidence_level", sa.String(), nullable=False, server_default="native_structured"),
        sa.Column("source_case_key", sa.String(), nullable=True),
        sa.Column("incident_id", sa.String(), nullable=True),
        sa.Column("external_url", sa.String(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_regression_cases_project_id", "regression_cases", ["project_id"])
    op.create_index("ix_regression_cases_source_run_id", "regression_cases", ["source_run_id"])
    op.execute("ALTER TABLE regression_cases ENABLE ROW LEVEL SECURITY")

    op.create_table(
        "test_results",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "case_id",
            sa.String(),
            sa.ForeignKey("regression_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("agent_version", sa.String(), nullable=True),
        sa.Column("trials", sa.Integer(), nullable=False),
        sa.Column("passes", sa.Integer(), nullable=False),
        sa.Column("pass_rate", sa.Float(), nullable=False),
        sa.Column("verdict", sa.String(), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column(
            "judged_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_test_results_case_id", "test_results", ["case_id"])
    op.execute("ALTER TABLE test_results ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE test_results DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_test_results_case_id", table_name="test_results")
    op.drop_table("test_results")

    op.execute("ALTER TABLE regression_cases DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_regression_cases_source_run_id", table_name="regression_cases")
    op.drop_index("ix_regression_cases_project_id", table_name="regression_cases")
    op.drop_table("regression_cases")
