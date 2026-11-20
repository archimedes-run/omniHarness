"""SQLAlchemy-backed repository for user-owned MCP server records."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omniharness.persistence.mcp_server.approval import code_sha256, matches_code
from omniharness.persistence.mcp_server.model import McpServerRow
from omniharness.persistence.timestamps import utc_iso
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
            # Derived, never stored: approved only while the approval's hash is
            # the hash of the code stored now.
            "approved": matches_code(row.approved_code_sha256, row.source_code),
            "code_sha256": code_sha256(row.source_code),
            "approved_code_sha256": row.approved_code_sha256,
            "approved_by": row.approved_by,
            "approved_at": row.approved_at,
            "deployed_code_sha256": row.deployed_code_sha256,
            "build_thread_id": row.build_thread_id,
            "egress_hosts": row.egress_hosts or [],
            "source_code": row.source_code,
            "tools_discovered": row.tools_discovered or [],
            "test_results": row.test_results or [],
            "last_verified_at": row.last_verified_at,
            "container_id": row.container_id,
            "container_port": row.container_port,
            "created_at": utc_iso(row.created_at) if isinstance(row.created_at, datetime) else row.created_at,
            "updated_at": utc_iso(row.updated_at) if isinstance(row.updated_at, datetime) else row.updated_at,
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
        build_thread_id: str | None = None,
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
            build_thread_id=build_thread_id,
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
        """Persist the agent-generated source code for a server the caller owns.

        Different code ends the approval in the same write: an approval is for
        one exact source. (It would read as unapproved anyway: ``approved`` is
        derived from the hashes.)"""
        async with self._sf() as session:
            row = await session.get(McpServerRow, server_id)
            if row is None or row.owner_id != user_id:
                return False
            if code_sha256(source_code) != code_sha256(row.source_code):
                row.approved = False
                row.approved_code_sha256 = None
                row.approved_by = None
                row.approved_at = None
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

    async def record_approval(self, server_id: str, *, code_sha256_approved: str, approved_by: str, user_id: str) -> bool:
        """Record an approval of the code whose hash is ``code_sha256_approved``.

        Written only when that hash is the hash of the code stored now, read
        and written in one session, so code changed meanwhile is never
        approved. Returns False when not found, not the owner's, or the code
        differs. Approving the same code again keeps the first record.
        """
        async with self._sf() as session:
            row = await session.get(McpServerRow, server_id)
            if row is None or row.owner_id != user_id:
                return False
            if not matches_code(code_sha256_approved, row.source_code):
                return False
            if row.approved_code_sha256 != code_sha256_approved:
                row.approved_code_sha256 = code_sha256_approved
                row.approved_by = approved_by
                row.approved_at = datetime.now(UTC).isoformat()
                row.approved = True
                row.updated_at = datetime.now(UTC)
                await session.commit()
        return True

    async def update_container_info(
        self,
        server_id: str,
        *,
        container_id: str | None,
        container_port: int | None,
        status: str,
        user_id: str,
        deployed_code_sha256: str | None = None,
    ) -> bool:
        """Persist Docker container ID + host port after deployment, with the
        hash of the code the container was built from (cleared with it)."""
        async with self._sf() as session:
            row = await session.get(McpServerRow, server_id)
            if row is None or row.owner_id != user_id:
                return False
            row.container_id = container_id
            row.container_port = container_port
            row.deployed_code_sha256 = deployed_code_sha256 if container_id else None
            row.status = status
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
