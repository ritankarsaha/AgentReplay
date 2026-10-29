"""incident details and share links, plus a content-addressed blob store

Revision ID: 0008_incident_details
Revises: 0007_control_plane_tables
Create Date: 2026-10-30

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_incident_details"
down_revision: Union[str, None] = "0007_control_plane_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "incidents",
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.add_column("incidents", sa.Column("share_token", sa.String(), nullable=True))
    op.create_index("ix_incidents_share_token", "incidents", ["share_token"], unique=True)

    op.create_table(
        "blobs",
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("mime", sa.String(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("project_id", "sha256"),
    )
    op.execute("ALTER TABLE blobs ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE blobs DISABLE ROW LEVEL SECURITY")
    op.drop_table("blobs")
    op.drop_index("ix_incidents_share_token", table_name="incidents")
    op.drop_column("incidents", "share_token")
    op.drop_column("incidents", "details")
