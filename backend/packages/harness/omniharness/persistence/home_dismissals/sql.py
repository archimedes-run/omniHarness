"""SQLAlchemy-backed repository for Home dismissals."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omniharness.persistence.home_dismissals.model import HomeDismissalRow

#: What can be dismissed.
DISMISSAL_KINDS: tuple[str, ...] = ("alert", "name-prompt")
#: Longest key kept, in characters.
KEY_MAX = 256
#: Alerts leave Home after 24 h; their dismissals are kept a while longer, then
#: pruned so the table does not grow without bound.
ALERT_RETENTION = timedelta(days=30)


class HomeDismissalRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def keys(self, *, user_id: str, kind: str) -> set[str]:
        """Every key of this kind the user dismissed."""
        async with self._sf() as session:
            rows = await session.scalars(select(HomeDismissalRow.key).where(HomeDismissalRow.user_id == user_id, HomeDismissalRow.kind == kind))
            return set(rows)

    async def dismiss(self, *, user_id: str, kind: str, keys: list[str]) -> None:
        """Record dismissals. Idempotent: a key already dismissed stays as it was."""
        if kind not in DISMISSAL_KINDS:
            raise ValueError(f"kind must be one of {', '.join(DISMISSAL_KINDS)}")
        wanted = {k for k in keys if k}
        if any(len(k) > KEY_MAX for k in wanted):
            raise ValueError(f"a key is longer than {KEY_MAX} characters")
        async with self._sf() as session:
            existing = set(await session.scalars(select(HomeDismissalRow.key).where(HomeDismissalRow.user_id == user_id, HomeDismissalRow.kind == kind, HomeDismissalRow.key.in_(wanted)))) if wanted else set()
            for key in sorted(wanted - existing):
                session.add(HomeDismissalRow(user_id=user_id, kind=kind, key=key))
            if kind == "alert":
                cutoff = datetime.now(UTC) - ALERT_RETENTION
                await session.execute(delete(HomeDismissalRow).where(HomeDismissalRow.user_id == user_id, HomeDismissalRow.kind == "alert", HomeDismissalRow.created_at < cutoff))
            await session.commit()
