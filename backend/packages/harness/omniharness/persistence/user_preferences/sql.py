"""SQLAlchemy-backed repository for per-user preferences."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omniharness.persistence.user_preferences.model import UserPreferenceRow

#: The appearances a user can choose. "system" follows the OS.
APPEARANCES: tuple[str, ...] = ("system", "light", "dark")


class UserPreferenceRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def get_appearance(self, *, user_id: str) -> str | None:
        """The user's chosen appearance, or None when they have never chosen."""
        async with self._sf() as session:
            row = await session.get(UserPreferenceRow, user_id)
            return row.appearance if row else None

    async def set_appearance(self, *, user_id: str, appearance: str) -> str:
        if appearance not in APPEARANCES:
            raise ValueError(f"appearance must be one of {', '.join(APPEARANCES)}")
        async with self._sf() as session:
            row = await session.get(UserPreferenceRow, user_id)
            if row is None:
                session.add(UserPreferenceRow(user_id=user_id, appearance=appearance))
            else:
                row.appearance = appearance
            await session.commit()
        return appearance
