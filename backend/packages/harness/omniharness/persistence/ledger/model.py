"""ORM models for the Project Ledger (Feature 005, data-model.md).

Projects, goals, tasks, notes and links, plus the who-and-when log of every
change (FR-007). Evidence arrives with slice 4. Every row carries `version`
for stale-write refusal: two tabs editing one task must not overwrite each
other silently.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from omniharness.persistence.base import Base


def _now() -> datetime:
    return datetime.now(UTC)


class _Stamped:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class LedgerProjectRow(_Stamped, Base):
    __tablename__ = "ledger_projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    why: Mapped[str | None] = mapped_column(Text)
    # active | paused | done | archived
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    #: Standing instructions or context for agents working on it.
    context: Mapped[str | None] = mapped_column(Text)
    #: Next task number, for short ids (T-1, T-2, …).
    next_task: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    __table_args__ = (Index("ix_ledger_projects_owner", "owner_id"),)


class LedgerGoalRow(_Stamped, Base):
    __tablename__ = "ledger_goals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("ledger_projects.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    definition_of_done: Mapped[str] = mapped_column(Text, nullable=False)
    target_date: Mapped[date | None] = mapped_column(Date)

    __table_args__ = (Index("ix_ledger_goals_project", "project_id"),)


class LedgerTaskRow(_Stamped, Base):
    __tablename__ = "ledger_tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("ledger_projects.id"), nullable=False)
    #: "T-<n>", unique per project: how commits will name it (FR-041).
    short_id: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    # todo | doing | blocked | done | dropped. Changed only by the user, or on
    # the user's confirmation (FR-013).
    status: Mapped[str] = mapped_column(String(16), default="todo", nullable=False)
    #: {"kind": "user"|"agent"|"session"|"workflow", "ref": "..."} or None.
    owner: Mapped[dict | None] = mapped_column(JSON)
    due_date: Mapped[date | None] = mapped_column(Date)
    goal_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("ledger_goals.id"))
    parent_task_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("ledger_tasks.id"))
    declared_files: Mapped[list] = mapped_column(JSON, default=list)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("project_id", "short_id", name="uq_ledger_task_short_id"),
        Index("ix_ledger_tasks_project", "project_id"),
    )


class LedgerNoteRow(_Stamped, Base):
    __tablename__ = "ledger_notes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("ledger_projects.id"), nullable=False)
    decided: Mapped[str] = mapped_column(Text, nullable=False)
    why: Mapped[str | None] = mapped_column(Text)
    thread_id: Mapped[str | None] = mapped_column(String(64))


class LedgerLinkRow(_Stamped, Base):
    """An explicit link (FR-006). Nothing is linked by title similarity."""

    __tablename__ = "ledger_links"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # project | task
    from_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    from_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # thread | workflow | session | repository | external
    to_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    to_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    #: A human label for the link ("chat: Plan the beta").
    label: Mapped[str | None] = mapped_column(String(300))
    #: Set when the link came from promoting a thread's todo (FR-012).
    todo_ref: Mapped[str | None] = mapped_column(String(300))

    __table_args__ = (
        UniqueConstraint("from_kind", "from_id", "to_kind", "to_ref", name="uq_ledger_link"),
        Index("ix_ledger_links_to", "to_kind", "to_ref"),
    )


class LedgerChangeRow(Base):
    """Who changed what, and when (FR-007). Append-only."""

    __tablename__ = "ledger_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    owner_id: Mapped[str | None] = mapped_column(String(64))
    entity: Mapped[str] = mapped_column(String(16), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # user | assistant_confirmed | assistant_disclosed (Tier 2) | assistant_granted (standing grant)
    actor: Mapped[str] = mapped_column(String(24), nullable=False)
    #: What caused it: the confirmed pending action's id, or for a write the
    #: assistant made without a confirmation (Tier 2 / a standing grant) its
    #: write id "w-…", which Undo reverts by; an undo's own changes carry
    #: "undo:w-…".
    pending_action_id: Mapped[str | None] = mapped_column(String(64))
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
