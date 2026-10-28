"""control plane tables: agents, scope manifests, tokens, trust, incidents, filings, model runs

Revision ID: 0007_control_plane_tables
Revises: 0006_hash_api_keys_and_project_owner
Create Date: 2026-10-28

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_control_plane_tables"
down_revision: Union[str, None] = "0006_hash_api_keys_and_project_owner"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = [
    "agents",
    "scope_manifests",
    "access_tokens",
    "trust_scores",
    "incidents",
    "filings",
    "model_runs",
]


def _ts(name: str, nullable: bool = False, default: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.func.now() if default else None,
        nullable=nullable,
    )


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("owner_id", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("public_key", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        _ts("created_at", default=True),
    )
    op.create_index("ix_agents_project_id", "agents", ["project_id"])

    op.create_table(
        "scope_manifests",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("agent_id", sa.String(), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("manifest", postgresql.JSONB(), nullable=False),
        sa.Column("signature", sa.String(), nullable=False),
        _ts("issued_at"),
        _ts("expires_at", nullable=True),
        _ts("revoked_at", nullable=True),
    )
    op.create_index("ix_scope_manifests_agent_id", "scope_manifests", ["agent_id"])

    op.create_table(
        "access_tokens",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("agent_id", sa.String(), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("connector", sa.String(), nullable=False),
        sa.Column("scopes", postgresql.JSONB(), nullable=False, server_default="[]"),
        _ts("issued_at", default=True),
        _ts("expires_at", nullable=True),
        _ts("revoked_at", nullable=True),
    )
    op.create_index("ix_access_tokens_agent_id", "access_tokens", ["agent_id"])

    op.create_table(
        "trust_scores",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("agent_id", sa.String(), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("band", sa.String(), nullable=False),
        sa.Column("components", postgresql.JSONB(), nullable=False, server_default="{}"),
        _ts("computed_at", default=True),
        sa.Column("trigger_run_id", sa.String(), nullable=True),
    )
    op.create_index("ix_trust_scores_agent_id", "trust_scores", ["agent_id"])
    op.create_index("ix_trust_scores_computed_at", "trust_scores", ["computed_at"])

    op.create_table(
        "incidents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", sa.String(), sa.ForeignKey("agents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False, server_default="high"),
        sa.Column("culprit_span_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        _ts("created_at", default=True),
    )
    op.create_index("ix_incidents_project_id", "incidents", ["project_id"])
    op.create_index("ix_incidents_run_id", "incidents", ["run_id"])
    op.create_index("ix_incidents_agent_id", "incidents", ["agent_id"])

    op.create_table(
        "filings",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("incident_id", sa.String(), sa.ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("packet", postgresql.JSONB(), nullable=False),
        sa.Column("trace_hash", sa.String(), nullable=False),
        sa.Column("simulated", sa.Boolean(), nullable=False, server_default=sa.true()),
        _ts("created_at", default=True),
    )
    op.create_index("ix_filings_incident_id", "filings", ["incident_id"])

    op.create_table(
        "model_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("source_run_id", sa.String(), nullable=False),
        sa.Column("span_id", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("output", postgresql.JSONB(), nullable=True),
        sa.Column("verdict", sa.String(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        _ts("created_at", default=True),
    )
    op.create_index("ix_model_runs_project_id", "model_runs", ["project_id"])
    op.create_index("ix_model_runs_source_run_id", "model_runs", ["source_run_id"])

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.drop_table(table)
