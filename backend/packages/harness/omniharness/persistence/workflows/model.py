"""ORM model for workflow metadata."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from omniharness.persistence.base import Base


class WorkflowRow(Base):
    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    # "draft" | "active" | "paused" | "archived" | "failed"

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    # ── Phase 1 additive columns ────────────────────────────────────────────
    instruction_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)

    # "manual" | "scheduled" | "event" | "api"
    # Phase 4 will add a trigger registry; kept as plain string until then.
    trigger_type: Mapped[str | None] = mapped_column(String(32), nullable=True, default="manual")

    # "draft_only" | "approval_required" | "execute_low_risk"
    # Phase 6 may migrate this to a FK on an approvals table.
    approval_policy: Mapped[str | None] = mapped_column(String(32), nullable=True, default="draft_only")

    # "user" | "agent" | "import" | "template"
    created_by: Mapped[str | None] = mapped_column(String(16), nullable=True, default="user")

    # Soft FK to workflow_versions.id; set after v1 is created.
    # Migrate to a real FK in Phase 3 once the table is stable.
    current_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Plain string identifiers for required capabilities.
    # NO FK — capabilities are Phase 7.
    required_capability_ids: Mapped[list] = mapped_column(JSON, nullable=True, default=list)

    __table_args__ = (Index("ix_workflows_owner_id", "owner_id"),)
