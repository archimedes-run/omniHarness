"""Add source discriminator column to run_events.

Revision ID: 0011
Revises: None
Create Date: 2026-06-27

Adds a single nullable column ``source`` to ``run_events``.  Existing rows
retain NULL, which is interpreted as "run" (back-compat for all pre-existing
chat/agent/trace events).  Allowed values are defined in
``omniharness.platform.events.EventSource``.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("run_events") as batch_op:
        batch_op.add_column(sa.Column("source", sa.String(32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("run_events") as batch_op:
        batch_op.drop_column("source")
