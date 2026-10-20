"""SQLAlchemy-backed repository for per-user preferences."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omniharness.persistence.user_preferences.model import UserPreferenceRow

#: The appearances a user can choose. "system" follows the OS.
APPEARANCES: tuple[str, ...] = ("system", "light", "dark")
#: Longest display name kept, in characters.
DISPLAY_NAME_MAX = 64


def effective_display_name(display_name: str | None, email: str) -> str:
    """The one rule every UI uses: the chosen name, else the email before "@"."""
    if display_name and display_name.strip():
        return display_name.strip()
    return email.split("@", 1)[0]


class UserPreferenceRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def get_appearance(self, *, user_id: str) -> str | None:
        """The user's chosen appearance, or None when they have never chosen."""
        async with self._sf() as session:
            row = await session.get(UserPreferenceRow, user_id)
            return row.appearance if row else None

    async def get_display_name(self, *, user_id: str) -> str | None:
        """The user's chosen display name, or None when unset."""
        async with self._sf() as session:
            row = await session.get(UserPreferenceRow, user_id)
            return row.display_name if row else None

    async def set_display_name(self, *, user_id: str, display_name: str | None) -> str | None:
        """Set, or clear with None / blank, the display name. Returns what is stored."""
        value = (display_name or "").strip() or None
        if value is not None and len(value) > DISPLAY_NAME_MAX:
            raise ValueError(f"display name is longer than {DISPLAY_NAME_MAX} characters")
        async with self._sf() as session:
            row = await session.get(UserPreferenceRow, user_id)
            if row is None:
                session.add(UserPreferenceRow(user_id=user_id, display_name=value))
            else:
                row.display_name = value
            await session.commit()
        return value

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
