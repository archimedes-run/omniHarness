"""SQLAlchemy-backed repository for per-thread skill exclusion."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omniharness.persistence.thread_skill_exclusion.model import ThreadSkillExclusionRow


class ThreadOwnedElsewhere(Exception):
    """The thread's exclusion row belongs to another user."""


def _clean(names: list[str]) -> list[str]:
    """De-duped, order-stable, non-empty strings only."""
    seen: set[str] = set()
    result: list[str] = []
    for name in names:
        if isinstance(name, str) and name.strip() and name not in seen:
            seen.add(name)
            result.append(name)
    return result


class ThreadSkillExclusionRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def get_excluded(self, *, thread_id: str, user_id: str | None) -> list[str]:
        """The skills removed from this thread; empty when none or not this user's."""
        async with self._sf() as session:
            row = await session.get(ThreadSkillExclusionRow, thread_id)
            if row is None or (user_id is not None and row.user_id != user_id):
                return []
            return _clean(list(row.excluded) if isinstance(row.excluded, list) else [])

    async def set_excluded(self, *, thread_id: str, user_id: str, excluded: list[str]) -> list[str]:
        """Persist the thread's exclusion. Refuses to overwrite another user's row."""
        final = _clean(excluded)
        async with self._sf() as session:
            row = await session.get(ThreadSkillExclusionRow, thread_id)
            if row is None:
                session.add(ThreadSkillExclusionRow(thread_id=thread_id, user_id=user_id, excluded=final))
            elif row.user_id != user_id:
                raise ThreadOwnedElsewhere(thread_id)
            else:
                row.excluded = final
            await session.commit()
        return final
