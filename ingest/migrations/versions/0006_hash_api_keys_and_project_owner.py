"""hash project API keys; add project owner for self-serve

Revision ID: 0006_hash_api_keys_and_project_owner
Revises: 0005_add_regression_cases
Create Date: 2026-10-27

Replaces the plaintext `projects.api_key` with `api_key_hash` (sha256 hex,
backfilled in-place so existing keys keep working), adds a display
`api_key_prefix` and the viewer-user `owner_email`. The plaintext column is
dropped, so this is NOT reversible with data intact: downgrade restores the
column shape but existing rows can't get their keys back.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_hash_api_keys_and_project_owner"
down_revision: Union[str, None] = "0005_add_regression_cases"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("api_key_hash", sa.String(), nullable=True))
    op.add_column("projects", sa.Column("api_key_prefix", sa.String(), nullable=True))
    op.add_column("projects", sa.Column("owner_email", sa.String(), nullable=True))
    op.execute(
        "UPDATE projects SET api_key_hash = encode(sha256(convert_to(api_key, 'UTF8')), 'hex'), "
        "api_key_prefix = left(api_key, 11)"
    )
    op.alter_column("projects", "api_key_hash", nullable=False)
    op.create_index("ix_projects_api_key_hash", "projects", ["api_key_hash"], unique=True)
    op.create_index("ix_projects_owner_email", "projects", ["owner_email"])
    op.drop_index("ix_projects_api_key", table_name="projects")
    op.drop_column("projects", "api_key")


def downgrade() -> None:
    op.add_column("projects", sa.Column("api_key", sa.String(), nullable=True))
    op.execute("UPDATE projects SET api_key = api_key_prefix || '-unrecoverable-' || id")
    op.alter_column("projects", "api_key", nullable=False)
    op.create_index("ix_projects_api_key", "projects", ["api_key"], unique=True)
    op.drop_index("ix_projects_owner_email", table_name="projects")
    op.drop_index("ix_projects_api_key_hash", table_name="projects")
    op.drop_column("projects", "owner_email")
    op.drop_column("projects", "api_key_prefix")
    op.drop_column("projects", "api_key_hash")
