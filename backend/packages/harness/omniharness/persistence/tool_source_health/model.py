"""ORM model: one row per (owner, source)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from omniharness.persistence.base import Base


class ToolSourceHealthRow(Base):
    __tablename__ = "tool_source_health"

    #: The user a connector call ran for; "" for a local server (shared).
    owner_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    #: Namespaced source id: local:<server> or connector:<SLUG>.
    source_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: The failing call's error, first line, truncated. Redacted before display.
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), nullable=False)
