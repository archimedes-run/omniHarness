"""0013: Phase 1 Slice 4a — add spec_json to workflow_versions.

Stores the validated WorkflowSpec generated from instruction_prompt.
Nullable; populated by POST /api/workflows/{id}/generate.

down_revision = None: standalone branch.
Run with: alembic upgrade 0013
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("workflow_versions") as batch_op:
        batch_op.add_column(sa.Column("spec_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workflow_versions") as batch_op:
        batch_op.drop_column("spec_json")
