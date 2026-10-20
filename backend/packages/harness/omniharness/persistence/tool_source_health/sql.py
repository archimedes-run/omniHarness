"""SQLAlchemy-backed repository for tool-source health."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omniharness.persistence.tool_source_health.model import ToolSourceHealthRow

#: Owner of a local server's record: local servers are shared by every user.
LOCAL_OWNER = ""
_MAX_ERROR = 300


@dataclass(frozen=True)
class SourceHealth:
    last_success_at: datetime | None
    last_failure_at: datetime | None
    last_error: str | None


def _first_line(text: str) -> str:
    line = (text.strip().splitlines() or [""])[0]
    return line if len(line) <= _MAX_ERROR else line[: _MAX_ERROR - 1] + "…"


class ToolSourceHealthRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def _row(self, session: AsyncSession, owner_id: str, source_id: str) -> ToolSourceHealthRow:
        row = await session.get(ToolSourceHealthRow, (owner_id, source_id))
        if row is None:
            row = ToolSourceHealthRow(owner_id=owner_id, source_id=source_id)
            session.add(row)
        return row

    async def record_success(self, *, owner_id: str, source_id: str, at: datetime | None = None) -> None:
        async with self._sf() as session:
            row = await self._row(session, owner_id, source_id)
            row.last_success_at = at or datetime.now(UTC)
            await session.commit()

    async def record_failure(self, *, owner_id: str, source_id: str, error: str, at: datetime | None = None) -> None:
        async with self._sf() as session:
            row = await self._row(session, owner_id, source_id)
            row.last_failure_at = at or datetime.now(UTC)
            row.last_error = _first_line(error)
            await session.commit()

    async def for_user(self, *, user_id: str | None) -> dict[str, SourceHealth]:
        """Every local source's record, plus this user's connector records."""
        owners = [LOCAL_OWNER] if not user_id else [LOCAL_OWNER, user_id]
        async with self._sf() as session:
            rows = (await session.execute(select(ToolSourceHealthRow).where(or_(*(ToolSourceHealthRow.owner_id == o for o in owners))))).scalars().all()
        return {r.source_id: SourceHealth(r.last_success_at, r.last_failure_at, r.last_error) for r in rows}
