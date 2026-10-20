"""ORM model for Home dismissals."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from omniharness.persistence.base import Base


class HomeDismissalRow(Base):
    __tablename__ = "home_dismissals"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # "alert" (a While-you-were-away alert) | "name-prompt" (asked once).
    kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    # For an alert, "<rule_id>:<event_id>"; for the name prompt, "name-prompt".
    key: Mapped[str] = mapped_column(String(256), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
