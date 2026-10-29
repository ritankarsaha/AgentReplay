"""incident details: classification, causation tags, and data findings

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


def downgrade() -> None:
    op.drop_column("incidents", "details")
