"""Add workflows table.

Revision ID: 0010
Revises: None
Create Date: 2026-06-27

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0010"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflows",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("owner_id", sa.String(64), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_workflows_owner_id", "workflows", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_workflows_owner_id", table_name="workflows")
    op.drop_table("workflows")
