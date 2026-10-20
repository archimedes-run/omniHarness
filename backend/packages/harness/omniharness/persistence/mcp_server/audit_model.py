"""Append-only audit of what the MCP builder retired or turned off (#59)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from omniharness.persistence.base import Base


class McpBuildAuditRow(Base):
    __tablename__ = "mcp_build_audit"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    #: "system:startup-reconcile" etc.
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    #: "retired" | "orphaned-secrets" | "turned-off" | "retirement-2026-10"
    event: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    server_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    #: Names only, never values or hints.
    details: Mapped[dict] = mapped_column(JSON, default=dict)
