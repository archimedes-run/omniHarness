"""ORM model for individual step execution within a workflow run."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from omniharness.persistence.base import Base


class WorkflowStepRunRow(Base):
    __tablename__ = "workflow_step_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_run_id: Mapped[str] = mapped_column(String(64), ForeignKey("workflow_runs.id"), nullable=False)
    step_key: Mapped[str] = mapped_column(String(128), nullable=False)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    # Allowed: queued | running | succeeded | failed | skipped | canceled
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    __table_args__ = (Index("ix_workflow_step_runs_workflow_run_id", "workflow_run_id"),)
