"""0012: Phase 1 Slice 1 — workflow data model.

Adds 6 columns to existing `workflows` table and creates 4 new tables:
  workflow_versions, workflow_runs, workflow_step_runs, workflow_artifact_links.

down_revision = None: standalone branch (see project migration conventions).
Run with: alembic upgrade 0012
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Additive columns on workflows ────────────────────────────────────
    with op.batch_alter_table("workflows") as batch_op:
        batch_op.add_column(sa.Column("instruction_prompt", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("trigger_type", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("approval_policy", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("created_by", sa.String(16), nullable=True))
        batch_op.add_column(sa.Column("current_version_id", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("required_capability_ids", sa.JSON(), nullable=True))

    # ── 2. New tables ────────────────────────────────────────────────────────
    op.create_table(
        "workflow_versions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("workflow_id", sa.String(64), sa.ForeignKey("workflows.id"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("instruction_prompt", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(32), nullable=False, server_default="user"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_workflow_versions_workflow_id", "workflow_versions", ["workflow_id"])

    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("workflow_id", sa.String(64), sa.ForeignKey("workflows.id"), nullable=False),
        sa.Column("trigger_type", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("trigger_payload", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("thread_id", sa.String(64), nullable=True),
        sa.Column("run_id", sa.String(64), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("initiated_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_workflow_runs_idempotency_key"),
    )
    op.create_index("ix_workflow_runs_workflow_id", "workflow_runs", ["workflow_id"])

    op.create_table(
        "workflow_step_runs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("workflow_run_id", sa.String(64), sa.ForeignKey("workflow_runs.id"), nullable=False),
        sa.Column("step_key", sa.String(128), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_workflow_step_runs_workflow_run_id", "workflow_step_runs", ["workflow_run_id"])

    op.create_table(
        "workflow_artifact_links",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("workflow_run_id", sa.String(64), sa.ForeignKey("workflow_runs.id"), nullable=False),
        sa.Column("artifact_path", sa.String(512), nullable=False),
        sa.Column("artifact_type", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_workflow_artifact_links_run_id", "workflow_artifact_links", ["workflow_run_id"])


def downgrade() -> None:
    op.drop_table("workflow_artifact_links")
    op.drop_table("workflow_step_runs")
    op.drop_table("workflow_runs")
    op.drop_table("workflow_versions")

    with op.batch_alter_table("workflows") as batch_op:
        batch_op.drop_column("required_capability_ids")
        batch_op.drop_column("current_version_id")
        batch_op.drop_column("created_by")
        batch_op.drop_column("approval_policy")
        batch_op.drop_column("trigger_type")
        batch_op.drop_column("instruction_prompt")
