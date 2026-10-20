"""0014: Feature 005 — the Project Ledger tables.

Projects, goals, tasks, notes, links and the change log (data-model.md). The
gateway also creates them at startup through Base.metadata.create_all, like
every other table; this revision is for deployments that run Alembic.

down_revision = None: standalone branch, like 0010–0013.
Run with: alembic upgrade 0014
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = None
branch_labels = None
depends_on = None


def _stamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    ]


def upgrade() -> None:
    op.create_table(
        "ledger_projects",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(64)),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("why", sa.Text()),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("context", sa.Text()),
        sa.Column("next_task", sa.Integer(), nullable=False, server_default="1"),
        *_stamps(),
    )
    op.create_index("ix_ledger_projects_owner", "ledger_projects", ["owner_id"])
    op.create_table(
        "ledger_goals",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("ledger_projects.id"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("definition_of_done", sa.Text(), nullable=False),
        sa.Column("target_date", sa.Date()),
        *_stamps(),
    )
    op.create_index("ix_ledger_goals_project", "ledger_goals", ["project_id"])
    op.create_table(
        "ledger_tasks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("ledger_projects.id"), nullable=False),
        sa.Column("short_id", sa.String(16), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="todo"),
        sa.Column("owner", sa.JSON()),
        sa.Column("due_date", sa.Date()),
        sa.Column("goal_id", sa.String(64), sa.ForeignKey("ledger_goals.id")),
        sa.Column("parent_task_id", sa.String(64), sa.ForeignKey("ledger_tasks.id")),
        sa.Column("declared_files", sa.JSON()),
        sa.Column("done_at", sa.DateTime(timezone=True)),
        *_stamps(),
        sa.UniqueConstraint("project_id", "short_id", name="uq_ledger_task_short_id"),
    )
    op.create_index("ix_ledger_tasks_project", "ledger_tasks", ["project_id"])
    op.create_table(
        "ledger_notes",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("ledger_projects.id"), nullable=False),
        sa.Column("decided", sa.Text(), nullable=False),
        sa.Column("why", sa.Text()),
        sa.Column("thread_id", sa.String(64)),
        *_stamps(),
    )
    op.create_table(
        "ledger_links",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("from_kind", sa.String(16), nullable=False),
        sa.Column("from_id", sa.String(64), nullable=False),
        sa.Column("to_kind", sa.String(16), nullable=False),
        sa.Column("to_ref", sa.String(512), nullable=False),
        sa.Column("label", sa.String(300)),
        sa.Column("todo_ref", sa.String(300)),
        *_stamps(),
        sa.UniqueConstraint("from_kind", "from_id", "to_kind", "to_ref", name="uq_ledger_link"),
    )
    op.create_index("ix_ledger_links_to", "ledger_links", ["to_kind", "to_ref"])
    op.create_table(
        "ledger_changes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("at", sa.DateTime(timezone=True)),
        sa.Column("owner_id", sa.String(64)),
        sa.Column("entity", sa.String(16), nullable=False),
        sa.Column("entity_id", sa.String(64), nullable=False),
        sa.Column("actor", sa.String(24), nullable=False),
        sa.Column("pending_action_id", sa.String(64)),
        sa.Column("before", sa.JSON()),
        sa.Column("after", sa.JSON()),
    )


def downgrade() -> None:
    for table in ("ledger_changes", "ledger_links", "ledger_notes", "ledger_tasks", "ledger_goals", "ledger_projects"):
        op.drop_table(table)
