"""SQLAlchemy-backed repository for per-user Composio connections."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omniharness.persistence.composio_connections.model import ComposioConnectionRow


class ComposioConnectionRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _row_to_dict(row: ComposioConnectionRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "user_id": row.user_id,
            "toolkit": row.toolkit,
            "composio_connection_id": row.composio_connection_id,
            "status": row.status,
            "account_display": row.account_display,
            "created_at": row.created_at.isoformat() if isinstance(row.created_at, datetime) else row.created_at,
            "updated_at": row.updated_at.isoformat() if isinstance(row.updated_at, datetime) else row.updated_at,
        }

    async def upsert(
        self,
        *,
        user_id: str,
        toolkit: str,
        composio_connection_id: str | None = None,
        status: str,
        account_display: str | None = None,
    ) -> dict[str, Any]:
        """Insert or update the (user_id, toolkit) connection row.

        On an existing row, only non-``None`` fields overwrite previous values
        except ``status``, which is always applied.
        """
        async with self._sf() as session:
            stmt = select(ComposioConnectionRow).where(
                ComposioConnectionRow.user_id == user_id,
                ComposioConnectionRow.toolkit == toolkit,
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                row = ComposioConnectionRow(
                    id=uuid.uuid4().hex,
                    user_id=user_id,
                    toolkit=toolkit,
                    composio_connection_id=composio_connection_id,
                    status=status,
                    account_display=account_display,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
                session.add(row)
            else:
                row.status = status
                if composio_connection_id is not None:
                    row.composio_connection_id = composio_connection_id
                if account_display is not None:
                    row.account_display = account_display
                row.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def get_by_user_toolkit(self, *, user_id: str, toolkit: str) -> dict[str, Any] | None:
        async with self._sf() as session:
            stmt = select(ComposioConnectionRow).where(
                ComposioConnectionRow.user_id == user_id,
                ComposioConnectionRow.toolkit == toolkit,
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
        return self._row_to_dict(row) if row is not None else None

    async def list_by_user(self, *, user_id: str) -> list[dict[str, Any]]:
        async with self._sf() as session:
            stmt = select(ComposioConnectionRow).where(ComposioConnectionRow.user_id == user_id).order_by(ComposioConnectionRow.created_at.desc())
            rows = list((await session.execute(stmt)).scalars())
        return [self._row_to_dict(r) for r in rows]

    async def mark_active(self, *, user_id: str, toolkit: str, account_display: str | None) -> dict[str, Any] | None:
        async with self._sf() as session:
            stmt = select(ComposioConnectionRow).where(
                ComposioConnectionRow.user_id == user_id,
                ComposioConnectionRow.toolkit == toolkit,
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            row.status = "active"
            if account_display is not None:
                row.account_display = account_display
            row.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def mark_revoked(self, *, user_id: str, toolkit: str) -> dict[str, Any] | None:
        async with self._sf() as session:
            stmt = select(ComposioConnectionRow).where(
                ComposioConnectionRow.user_id == user_id,
                ComposioConnectionRow.toolkit == toolkit,
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            row.status = "revoked"
            row.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)
