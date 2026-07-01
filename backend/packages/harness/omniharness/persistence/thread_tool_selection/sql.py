"""SQLAlchemy-backed repository for per-thread tool selection."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omniharness.persistence.thread_tool_selection.model import ThreadToolSelectionRow

# Namespaced source ids that must ALWAYS be present regardless of client input.
PINNED_SOURCES: tuple[str, ...] = ("local:filesystem", "local:postgres")


def _enforce_pinned(sources: list[str]) -> list[str]:
    """Return *sources* with the pinned defaults guaranteed present, de-duped, order-stable."""
    seen: set[str] = set()
    result: list[str] = []
    for sid in list(PINNED_SOURCES) + list(sources):
        if isinstance(sid, str) and sid and sid not in seen:
            seen.add(sid)
            result.append(sid)
    return result


class ThreadToolSelectionRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def get_sources(self, *, thread_id: str) -> list[str]:
        """Return the thread's selected namespaced source ids (pinned always included).

        A thread with no stored row still gets the pinned defaults.
        """
        async with self._sf() as session:
            row = await session.get(ThreadToolSelectionRow, thread_id)
            stored = list(row.sources) if row and isinstance(row.sources, list) else []
            return _enforce_pinned(stored)

    async def set_sources(self, *, thread_id: str, user_id: str, sources: list[str]) -> list[str]:
        """Persist the thread's selection. Pinned defaults are enforced server-side.

        The client is NEVER trusted to include the pinned sources.
        """
        final = _enforce_pinned(sources)
        async with self._sf() as session:
            row = await session.get(ThreadToolSelectionRow, thread_id)
            if row is None:
                row = ThreadToolSelectionRow(thread_id=thread_id, user_id=user_id, sources=final)
                session.add(row)
            else:
                row.sources = final
                row.user_id = user_id
            await session.commit()
        return final
