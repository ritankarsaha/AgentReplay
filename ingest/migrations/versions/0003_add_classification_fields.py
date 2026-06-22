"""add classification_status and diagnosis to runs (chunk 3.6 classifier)

Revision ID: 0003_add_classification_fields
Revises: 0002_enable_rls
Create Date: 2026-06-20

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_add_classification_fields"
down_revision: Union[str, None] = "0002_enable_rls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column("classification_status", sa.String(), nullable=False, server_default="none"),
    )
    op.add_column("runs", sa.Column("diagnosis", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "diagnosis")
    op.drop_column("runs", "classification_status")
