"""SQLAlchemy-backed repository for user-owned MCP server records."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
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
        return {
            "id": row.id,
            "owner_id": row.owner_id,
            "name": row.name,
            "language": row.language,
            "description": row.description,
            "status": row.status,
            "detected_secrets": row.detected_secrets or [],
            "approved": bool(row.approved),
            "egress_hosts": row.egress_hosts or [],
            "source_code": row.source_code,
            "tools_discovered": row.tools_discovered or [],
            "test_results": row.test_results or [],
            "last_verified_at": row.last_verified_at,
            "created_at": row.created_at.isoformat() if isinstance(row.created_at, datetime) else row.created_at,
            "updated_at": row.updated_at.isoformat() if isinstance(row.updated_at, datetime) else row.updated_at,
        }

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

    async def create(
        self,
        *,
        name: str,
        owner_id: str,
        language: str | None = None,
        description: str | None = None,
        egress_hosts: list[str] | None = None,
        source_code: str | None = None,
    ) -> dict[str, Any]:
        """Insert a new MCP server record owned by *owner_id*."""
        row = McpServerRow(
            id=uuid.uuid4().hex,
            owner_id=owner_id,
            name=name,
            language=language,
            description=description,
            status="not_running",
            detected_secrets=[],
            approved=False,
            egress_hosts=egress_hosts or [],
            source_code=source_code,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return self._row_to_dict(row)

    async def update_status(self, server_id: str, status: str, *, user_id: str) -> bool:
        """Update the status field for a server the caller owns.

        Returns True if the row was found and updated, False if not found or
        the caller does not own it.
        """
        async with self._sf() as session:
            row = await session.get(McpServerRow, server_id)
            if row is None or row.owner_id != user_id:
                return False
            row.status = status
            row.updated_at = datetime.now(UTC)
            await session.commit()
        return True

    async def update_source_code(self, server_id: str, source_code: str, *, user_id: str) -> bool:
        """Persist the agent-generated source code for a server the caller owns."""
        async with self._sf() as session:
            row = await session.get(McpServerRow, server_id)
            if row is None or row.owner_id != user_id:
                return False
            row.source_code = source_code
            row.updated_at = datetime.now(UTC)
            await session.commit()
        return True

    async def update_detected_secrets(self, server_id: str, key_names: list[str], *, user_id: str) -> bool:
        """Persist the detected env-var key names (names only, never values)."""
        async with self._sf() as session:
            row = await session.get(McpServerRow, server_id)
            if row is None or row.owner_id != user_id:
                return False
            row.detected_secrets = key_names
            row.updated_at = datetime.now(UTC)
            await session.commit()
        return True

    async def update_build_result(
        self,
        server_id: str,
        *,
        phase: str,
        tools_discovered: list,
        test_results: list,
        last_verified_at: str | None,
        user_id: str,
    ) -> bool:
        """Persist sandbox test results so they survive backend restarts."""
        async with self._sf() as session:
            row = await session.get(McpServerRow, server_id)
            if row is None or row.owner_id != user_id:
                return False
            row.status = phase
            row.tools_discovered = tools_discovered
            row.test_results = test_results
            row.last_verified_at = last_verified_at
            row.updated_at = datetime.now(UTC)
            await session.commit()
        return True

    async def set_approved(self, server_id: str, approved: bool, *, user_id: str) -> bool:
        """Set the approval flag for a server the caller owns.

        Returns True if updated, False if not found / not owner.
        """
        async with self._sf() as session:
            row = await session.get(McpServerRow, server_id)
            if row is None or row.owner_id != user_id:
                return False
            row.approved = approved
            row.updated_at = datetime.now(UTC)
            await session.commit()
        return True

    async def delete(self, server_id: str, *, user_id: str) -> bool:
        """Hard-delete a server record owned by *user_id*.

        Returns True if the row was found and deleted, False otherwise.
        """
        async with self._sf() as session:
            row = await session.get(McpServerRow, server_id)
            if row is None or row.owner_id != user_id:
                return False
            await session.delete(row)
            await session.commit()
        return True
