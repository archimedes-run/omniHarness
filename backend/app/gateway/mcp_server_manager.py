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

4. Agent-generated code NEVER runs in the gateway process. ``_run_server_sandbox_test``
   launches it as a subprocess with a clean, constrained environment (only the
   required secrets from the vault; no gateway env vars leak in).
"""

from __future__ import annotations

import asyncio
import logging
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from app.gateway.mcp_egress import build_egress_rules
from app.gateway.mcp_secrets import McpSecretsVault
from omniharness.persistence.mcp_server.sql import McpServerRepository
from omniharness.skills.code_scanner import scan_python_code, scan_python_code_static

logger = logging.getLogger(__name__)


@dataclass
class MCPBuildRecord:
    """Runtime record for a single MCP server's current build/test phase.

    Contains phase, key NAMES (never values), and test results only.
    No ciphertext, no plaintext secrets, no env-var values appear here.
    tools_discovered and test_results contain names/descriptions/boolean outcomes only.
    """

    server_id: str
    phase: Literal["idle", "building", "testing", "verified", "ready", "failed", "stopped"]
    owner_id: str
    required_key_names: list[str] = field(default_factory=list)
    tools_discovered: list[dict] = field(default_factory=list)
    test_results: list[dict] = field(default_factory=list)
    error: str | None = None
    last_verified_at: str | None = None


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

    @staticmethod
    def _scrub_output(text: str, secret_values: frozenset[str]) -> str:
        """Replace exact secret value substrings in text with [REDACTED].

        Defense-in-depth: real secrets are never injected into the subprocess env
        (placeholder values are used), but this closes any unexpected leak path.
        Called after collecting test_results; the frozenset is immediately discarded.
        """
        for val in secret_values:
            if val and val in text:
                text = text.replace(val, "[REDACTED]")
        return text

    async def _run_server_sandbox_test(
        self,
        *,
        server_id: str,
        user_id: str,
        source_code: str,
    ) -> tuple[list[dict], list[dict]]:
        """Start server as subprocess, connect MCP client, discover and test tools.

        Security invariants:
        - Subprocess receives PLACEHOLDER values, not real vault secrets.
          Real-secret injection is deferred to Phase 4 where the container
          enforces the egress_hosts allowlist. A bare subprocess cannot be
          network-restricted, so injecting real keys here would allow
          exfiltration to arbitrary hosts bypassing the egress gate.
        - No gateway env vars leak in (clean env only).
        - Agent-generated code NEVER runs in the gateway process.

        Returns (tools_discovered, test_results) — neither contains real secret values.
        """
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        # Placeholder values only — real secrets stay in the vault until Phase 4.
        key_names = await self._vault.list_key_names(server_id=server_id, owner_id=user_id)
        placeholder_env: dict[str, str] = {k: f"placeholder_for_{k}" for k in key_names}

        tools_discovered: list[dict] = []
        test_results: list[dict] = []

        with tempfile.TemporaryDirectory(prefix="omni_mcp_test_") as tmpdir:
            server_file = Path(tmpdir) / "server.py"
            server_file.write_text(source_code)

            # Clean env: placeholder secrets + minimal system paths, no gateway env
            clean_env: dict[str, str] = {
                "PYTHONPATH": str(Path(sys.executable).parent.parent / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"),
                "HOME": str(Path.home()),
                "PATH": "/usr/bin:/bin",
                **placeholder_env,
            }

            server_params = StdioServerParameters(
                command=sys.executable,
                args=[str(server_file)],
                env=clean_env,
            )

            try:
                async with asyncio.timeout(30):
                    async with stdio_client(server_params) as (read, write):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            tools_resp = await session.list_tools()

                            for t in tools_resp.tools:
                                tools_discovered.append(
                                    {
                                        "name": t.name,
                                        "description": (t.description or "")[:300],
                                    }
                                )

                            for t in tools_resp.tools:
                                try:
                                    result = await asyncio.wait_for(
                                        session.call_tool(t.name, {}),
                                        timeout=10,
                                    )
                                    output = ""
                                    if result.content:
                                        output = str(result.content[0].text if hasattr(result.content[0], "text") else result.content[0])[:200]
                                    test_results.append({"tool": t.name, "ok": True, "output": output})
                                except Exception as exc:
                                    test_results.append({"tool": t.name, "ok": False, "error": str(exc)[:200]})

            except TimeoutError:
                raise RuntimeError("MCP server sandbox test timed out (30s)")

        return tools_discovered, test_results

    async def submit_source_and_test(self, *, server_id: str, user_id: str, source_code: str) -> MCPBuildRecord:
        """Save source_code then run the full test pipeline.

        Ownership gate is at the top — identical to every other mutating method.
        """
        await self._load_and_verify(server_id, user_id)
        await self._repo.update_source_code(server_id, source_code, user_id=user_id)
        return await self.test_server(server_id=server_id, user_id=user_id)

    async def test_server(self, *, server_id: str, user_id: str) -> MCPBuildRecord:
        """Run the full test pipeline: static scan → secrets check → LLM scan → sandbox execution.

        Ownership is verified at the top. Agent-generated code never runs in the
        gateway process — it is launched as a subprocess with only the required
        secrets injected from the vault.
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

        # Stage 4: validate egress rules structure
        egress_hosts = server.get("egress_hosts") or []
        build_egress_rules(egress_hosts)

        # Stage 5: run server in subprocess with placeholder secrets, discover tools.
        # phase="verified" when tools are discovered (server started, MCP protocol OK).
        # phase="testing" when sandbox failed to start or no tools found (not approvable).
        # Real secrets are never injected here — Phase 4 handles that in a container.
        tools_discovered: list[dict] = []
        test_results: list[dict] = []

        if source:
            try:
                tools_discovered, test_results = await self._run_server_sandbox_test(
                    server_id=server_id,
                    user_id=user_id,
                    source_code=source,
                )
            except Exception as exc:
                logger.warning("MCP sandbox test failed for %s: %s", server_id, exc)
                test_results.append({"tool": "__sandbox__", "ok": False, "error": str(exc)[:400]})

        # Defense-in-depth scrub: decrypt real values once, replace any exact matches
        # in test_results output/error fields, then immediately discard the values.
        # Real secrets were never injected (placeholder env), but this closes any
        # unexpected path that could surface a real value through tool output.
        if required_key_names and test_results:
            try:
                real_secrets = await self._vault._decrypt_for_sandbox(server_id=server_id, owner_id=user_id)
                secret_vals = frozenset(v for v in real_secrets.values() if v)
                del real_secrets  # discard plaintext values immediately
                for tr in test_results:
                    for field_name in ("output", "error"):
                        if field_name in tr and tr[field_name]:
                            tr[field_name] = self._scrub_output(str(tr[field_name]), secret_vals)
            except Exception:
                pass  # scrub failure is non-fatal; placeholder env means real values aren't present

        # "verified" = scan gates passed AND server connected AND at least one tool found.
        # "testing"  = scan gates passed but server didn't connect or no tools found.
        # Only "verified" servers can be approved.
        phase = "verified" if tools_discovered else "testing"
        verified_at = datetime.now(UTC).isoformat()

        await self._repo.update_status(server_id, phase, user_id=user_id)
        await self._repo.update_detected_secrets(server_id, required_key_names, user_id=user_id)

        record = MCPBuildRecord(
            server_id=server_id,
            phase=phase,
            owner_id=user_id,
            required_key_names=required_key_names,
            tools_discovered=tools_discovered,
            test_results=test_results,
            last_verified_at=verified_at,
        )
        async with self._lock:
            self._records[server_id] = record
        return record

    async def approve(self, *, server_id: str, user_id: str) -> MCPBuildRecord:
        """Mark a server as approved.

        Requires phase=="verified": the server must have completed the sandbox
        test and discovered at least one tool. Servers in "testing" (sandbox
        failed or no tools found) or any other phase cannot be approved.
        """
        await self._load_and_verify(server_id, user_id)
        async with self._lock:
            current = self._records.get(server_id)
        current_phase = current.phase if current is not None else "unknown"
        if current_phase != "verified":
            raise PermissionError(f"MCP server {server_id!r} cannot be approved from phase {current_phase!r}. Run POST /test first; the server must reach 'verified' (sandbox connected + tools discovered) before it can be approved.")
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
