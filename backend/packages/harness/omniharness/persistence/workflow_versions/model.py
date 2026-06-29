"""ORM model for workflow version snapshots."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from omniharness.persistence.base import Base


class WorkflowVersionRow(Base):
    __tablename__ = "workflow_versions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(64), ForeignKey("workflows.id"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    instruction_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Slice 4a: validated structured spec generated from instruction_prompt.
    spec_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[str] = mapped_column(String(32), default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    __table_args__ = (Index("ix_workflow_versions_workflow_id", "workflow_id"),)
