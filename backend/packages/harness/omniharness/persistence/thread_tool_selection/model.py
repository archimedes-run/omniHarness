"""ORM model for per-thread tool selection.

One row per thread. ``sources`` is a JSON array of NAMESPACED source ids
(``local:<server>`` / ``connector:<SLUG>``) — never raw tool names.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from omniharness.persistence.base import Base


class ThreadToolSelectionRow(Base):
    __tablename__ = "thread_tool_selection"

    thread_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    # Owner of the thread (per-user scoping / audit).
    user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    # JSON array of namespaced source ids, e.g. ["local:github", "connector:GMAIL"].
    sources: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), nullable=False)
