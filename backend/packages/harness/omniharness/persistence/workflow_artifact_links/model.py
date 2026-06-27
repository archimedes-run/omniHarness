"""ORM model linking workflow runs to output artifacts."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from omniharness.persistence.base import Base


class WorkflowArtifactLinkRow(Base):
    __tablename__ = "workflow_artifact_links"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_run_id: Mapped[str] = mapped_column(String(64), ForeignKey("workflow_runs.id"), nullable=False)
    artifact_path: Mapped[str] = mapped_column(String(512), nullable=False)
    artifact_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # e.g. "file", "url", "snippet" — extensible; no FK
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    __table_args__ = (Index("ix_workflow_artifact_links_run_id", "workflow_run_id"),)
