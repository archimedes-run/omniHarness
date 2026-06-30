"""ORM model for per-user Composio connected-account records.

Each row maps a (user_id, toolkit) pair to a Composio connected account.
Values are never secrets — only the Composio-side connection id, the
normalized status, and an optional display string (email / account name).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from omniharness.persistence.base import Base


class ComposioConnectionRow(Base):
    __tablename__ = "composio_connections"
    __table_args__ = (UniqueConstraint("user_id", "toolkit", name="uq_composio_connection"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Stable DB user UUID (entity_id on the Composio side).
    user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    # Toolkit slug, stored uppercase: "GMAIL" | "GOOGLECALENDAR" | ...
    toolkit: Mapped[str] = mapped_column(String(64), nullable=False)
    # Composio's connectedAccountId — null until the OAuth callback resolves it.
    composio_connection_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # "pending" | "active" | "failed" | "revoked"
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    # Email / display name from Composio metadata (filled on active).
    account_display: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
