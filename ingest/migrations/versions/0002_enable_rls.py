"""enable row level security on projects, runs, spans

Revision ID: 0002_enable_rls
Revises: 0001_initial_schema
Create Date: 2026-06-13

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0002_enable_rls"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ["projects", "runs", "spans"]


def upgrade() -> None:

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
