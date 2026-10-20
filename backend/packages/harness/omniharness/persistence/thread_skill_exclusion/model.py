"""ORM model for per-thread skill exclusion.

One row per thread. ``excluded`` is a JSON array of skill names removed from
this conversation. No row means nothing is removed.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from omniharness.persistence.base import Base


class ThreadSkillExclusionRow(Base):
    __tablename__ = "thread_skill_exclusion"

    thread_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    # Owner of the thread: a row written by one user is invisible to another.
    user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    # JSON array of skill names, e.g. ["deep-research"].
    excluded: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), nullable=False)
