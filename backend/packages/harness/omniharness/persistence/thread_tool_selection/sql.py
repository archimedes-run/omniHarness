"""SQLAlchemy-backed repository for per-thread tool selection."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omniharness.persistence.thread_tool_selection.model import ThreadToolSelectionRow

# Namespaced source ids that must ALWAYS be present regardless of client input.
#: THE canonical pinned set. Namespaced ids, always present in every thread's
#: selection regardless of what a client sends.
#:
#: Single source of truth on purpose: this used to be duplicated as
#: PINNED_LOCAL_SERVERS in omniharness/tools/tools.py, and the two drifted when
#: session-watcher was pinned in one and not the other. Nothing broke — the
#: runtime filter used its copy and worked — but the tools picker displayed a
#: `pinned` list that was false, which is worse than a break because it teaches
#: the next reader something untrue.
PINNED_SOURCES: tuple[str, ...] = ("local:filesystem", "local:postgres", "local:session-watcher")


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
