"""ORM model for workflow run execution records."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from omniharness.persistence.base import Base


class WorkflowRunRow(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(64), ForeignKey("workflows.id"), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(32), default="manual")
    # "manual" | "scheduled" | "event" | "api"
    trigger_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    # Allowed: queued | running | waiting_approval | succeeded | failed | canceled | expired
    # waiting_approval is reserved for Phase 6 — define it but add NO transition logic yet.
    # Legal transitions enforced in WorkflowRunRepository.transition_status().
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # thread_id and run_id are set by the executor in Slice 2; NULL until then.
    thread_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    initiated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_workflow_runs_idempotency_key"),
        Index("ix_workflow_runs_workflow_id", "workflow_id"),
    )
