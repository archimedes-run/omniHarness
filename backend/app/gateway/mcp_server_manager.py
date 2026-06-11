"""MCPServerManager — app-layer manager for the MCP server lifecycle.

Mirrors the PreviewSessionManager pattern: an in-memory manager registered
in the FastAPI lifespan that delegates persistence to ``McpServerRepository``
and secrets to ``McpSecretsVault``.

Security invariants (enforced at the top of every mutating method)
------------------------------------------------------------------
1. ``_load_and_verify(server_id, user_id)`` is called FIRST. It fetches the
   server scoped to ``user_id`` and raises ``PermissionError`` if the record
   does not exist for that owner. This means a caller who knows someone else's
   ``server_id`` gets the same 404-equivalent as if the row did not exist.

2. The vault always receives ``owner_id=user_id`` (the verified requesting
   user passed explicitly by the caller), NEVER ``server["owner_id"]`` read
   back from the DB row. These values are equivalent after _load_and_verify,
   but using the caller-supplied value closes the injection surface.

3. Manager methods accept an explicit ``user_id: str`` — they NEVER read
   ``_current_user`` from a ContextVar. Managers may run in background tasks
   where the ContextVar is not set.

4. No agent code is executed in Phase 2. ``test_server`` runs the scanner and
   secrets check only; the actual sandbox launch is deferred to Phase 4.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Literal

from app.gateway.mcp_egress import build_egress_rules
from app.gateway.mcp_secrets import McpSecretsVault
from omniharness.persistence.mcp_server.sql import McpServerRepository
from omniharness.skills.code_scanner import scan_python_code, scan_python_code_static

logger = logging.getLogger(__name__)


@dataclass
class MCPBuildRecord:
    """Runtime record for a single MCP server's current build/test phase.

    Contains phase, key NAMES (never values), and error only.
    No ciphertext, no plaintext secrets, no env-var values appear here.
    """

    server_id: str
    phase: Literal["idle", "building", "testing", "ready", "failed", "stopped"]
    owner_id: str
    required_key_names: list[str] = field(default_factory=list)
    error: str | None = None


class MCPServerManager:
    """Lifecycle manager for agent-built MCP servers.

    Created once in the app lifespan and stored on ``app.state``.
    """

    def __init__(self, repo: McpServerRepository, vault: McpSecretsVault) -> None:
        self._repo = repo
        self._vault = vault
        # In-memory phase tracking: server_id → MCPBuildRecord
        self._records: dict[str, MCPBuildRecord] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        logger.info("MCPServerManager started")

    async def close(self) -> None:
        logger.info("MCPServerManager stopped")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _load_and_verify(self, server_id: str, user_id: str) -> dict:
        """Load the server record scoped to *user_id*.

        Raises ``PermissionError`` if the record does not exist or the caller
        does not own it. This is the single ownership gate — every mutating
        manager method calls this first, before any other logic.
        """
        server = await self._repo.get(server_id, user_id=user_id)
        if server is None:
            raise PermissionError(f"MCP server {server_id!r} not found for user {user_id!r}")
        return server

    # ------------------------------------------------------------------
    # Public methods — all require explicit user_id
    # ------------------------------------------------------------------

    async def get_status(self, *, server_id: str, user_id: str) -> MCPBuildRecord:
        """Return the current build record, creating an idle one if absent."""
        await self._load_and_verify(server_id, user_id)
        async with self._lock:
            if server_id not in self._records:
                self._records[server_id] = MCPBuildRecord(server_id=server_id, phase="idle", owner_id=user_id)
            return self._records[server_id]

    async def test_server(self, *, server_id: str, user_id: str) -> MCPBuildRecord:
        """Run scanner + secrets check + egress validation.

        Phase 2: no container execution. The sandbox launch is gated in
        Phase 4 after the approval workflow is complete.
        """
        server = await self._load_and_verify(server_id, user_id)

        source = server.get("source_code") or ""

        # Stage 1: static scan (immediate, no LLM) — blocks obvious threats
        if source:
            static_result = scan_python_code_static(source)
            if static_result is not None:
                await self._repo.update_status(server_id, "failed", user_id=user_id)
                record = MCPBuildRecord(
                    server_id=server_id,
                    phase="failed",
                    owner_id=user_id,
                    error=static_result.reason,
                )
                async with self._lock:
                    self._records[server_id] = record
                return record

        # Stage 2: extract required env-var names (static, pure) and check secrets
        required_key_names = self._vault.scan_for_required_keys(source) if source else []
        stored_names = await self._vault.list_key_names(server_id=server_id, owner_id=user_id)
        missing = [k for k in required_key_names if k not in stored_names]
        if missing:
            await self._repo.update_status(server_id, "failed", user_id=user_id)
            record = MCPBuildRecord(
                server_id=server_id,
                phase="failed",
                owner_id=user_id,
                required_key_names=required_key_names,
                error=f"Missing required secrets: {missing}",
            )
            async with self._lock:
                self._records[server_id] = record
            return record

        # Stage 3: LLM scan for borderline cases (only if all secrets present)
        if source:
            scan_result = await scan_python_code(source, location=f"mcp:{server_id}")
            if scan_result.decision == "block":
                await self._repo.update_status(server_id, "failed", user_id=user_id)
                record = MCPBuildRecord(
                    server_id=server_id,
                    phase="failed",
                    owner_id=user_id,
                    required_key_names=required_key_names,
                    error=scan_result.reason,
                )
                async with self._lock:
                    self._records[server_id] = record
                return record

        # Stage 4: validate egress rules structure (no execution)
        egress_hosts = server.get("egress_hosts") or []
        build_egress_rules(egress_hosts)  # validates structure; result used in Phase 4

        phase = "testing"
        error = None

        await self._repo.update_status(server_id, phase, user_id=user_id)
        record = MCPBuildRecord(
            server_id=server_id,
            phase=phase,
            owner_id=user_id,
            required_key_names=required_key_names,
            error=error,
        )
        async with self._lock:
            self._records[server_id] = record
        return record

    async def approve(self, *, server_id: str, user_id: str) -> MCPBuildRecord:
        """Mark a server as approved. Requires ownership check."""
        await self._load_and_verify(server_id, user_id)
        await self._repo.set_approved(server_id, True, user_id=user_id)
        record = MCPBuildRecord(server_id=server_id, phase="idle", owner_id=user_id)
        async with self._lock:
            self._records[server_id] = record
        return record

    async def register(self, *, server_id: str, user_id: str) -> MCPBuildRecord:
        """Register an approved server for agent use.

        Raises ``PermissionError`` if not approved — unapproved servers must
        not be accessible to the agent.
        """
        server = await self._load_and_verify(server_id, user_id)
        if not server.get("approved"):
            raise PermissionError(f"MCP server {server_id!r} has not been approved for registration")

        await self._repo.update_status(server_id, "deployed", user_id=user_id)
        record = MCPBuildRecord(server_id=server_id, phase="ready", owner_id=user_id)
        async with self._lock:
            self._records[server_id] = record
        return record

    async def stop(self, *, server_id: str, user_id: str) -> MCPBuildRecord:
        """Stop a running server."""
        await self._load_and_verify(server_id, user_id)
        await self._repo.update_status(server_id, "stopped", user_id=user_id)
        record = MCPBuildRecord(server_id=server_id, phase="stopped", owner_id=user_id)
        async with self._lock:
            self._records[server_id] = record
        return record
