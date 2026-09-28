"""add login_events table (viewer Google sign-in audit log)

Revision ID: 0004_add_login_events
Revises: 0003_add_classification_fields
Create Date: 2026-08-11

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_add_login_events"
down_revision: Union[str, None] = "0003_add_classification_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "login_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("image", sa.String(), nullable=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_login_events_project_id", "login_events", ["project_id"])
    op.create_index("ix_login_events_created_at", "login_events", ["created_at"])
    op.execute("ALTER TABLE login_events ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE login_events DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_login_events_created_at", table_name="login_events")
    op.drop_index("ix_login_events_project_id", table_name="login_events")
    op.drop_table("login_events")
