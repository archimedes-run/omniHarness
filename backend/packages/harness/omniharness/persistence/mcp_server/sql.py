"""SQLAlchemy-backed repository for user-owned MCP server records."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omniharness.persistence.mcp_server.model import McpServerRow
from omniharness.runtime.user_context import AUTO, _AutoSentinel, resolve_user_id


class McpServerRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _row_to_dict(row: McpServerRow) -> dict[str, Any]:
        d = {
            "id": row.id,
            "name": row.name,
            "language": row.language,
            "description": row.description,
            "status": row.status,
            "detected_secrets": row.detected_secrets or [],
            "created_at": row.created_at.isoformat() if isinstance(row.created_at, datetime) else row.created_at,
            "updated_at": row.updated_at.isoformat() if isinstance(row.updated_at, datetime) else row.updated_at,
        }
        return d

    async def list_servers(
        self,
        *,
        search: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> list[dict[str, Any]]:
        """Return MCP servers owned by the current user."""
        resolved_user_id = resolve_user_id(user_id, method_name="McpServerRepository.list_servers")
        stmt = select(McpServerRow).order_by(McpServerRow.updated_at.desc())
        if resolved_user_id is not None:
            stmt = stmt.where(McpServerRow.owner_id == resolved_user_id)
        if status:
            stmt = stmt.where(McpServerRow.status == status)
        stmt = stmt.limit(limit).offset(offset)

        async with self._sf() as session:
            result = await session.execute(stmt)
            rows = list(result.scalars())

        if search:
            q = search.lower()
            rows = [r for r in rows if q in (r.name or "").lower() or q in (r.description or "").lower()]

        return [self._row_to_dict(r) for r in rows]

    async def get(
        self,
        server_id: str,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict[str, Any] | None:
        """Return a single server, enforcing owner isolation."""
        resolved_user_id = resolve_user_id(user_id, method_name="McpServerRepository.get")
        async with self._sf() as session:
            row = await session.get(McpServerRow, server_id)
        if row is None:
            return None
        if resolved_user_id is not None and row.owner_id != resolved_user_id:
            return None
        return self._row_to_dict(row)
