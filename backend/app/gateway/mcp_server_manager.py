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
import re
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

# Extracts hostnames from https?:// URL string literals in generated source.
# Used to auto-populate egress_hosts when the build flow didn't set them explicitly.
_HTTPS_HOST_RE = re.compile(
    r"""https?://([a-zA-Z0-9](?:[a-zA-Z0-9\-]*[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9\-]*[a-zA-Z0-9])?)+)""",
)

# Patterns that indicate a 401/403 or authentication failure in tool-call output.
# A tool that returns an auth error is still callable — the key is just not valid.
_AUTH_ERROR_RE = re.compile(
    r"\b(401|403|unauthorized|forbidden|invalid[\s_\-]?(key|token|api|credential)|"
    r"authentication[\s_\-]?(fail|required|error)|api[\s_\-]?key|access[\s_\-]?denied)\b",
    re.IGNORECASE,
)


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
        # Per-server in-flight test locks: server_id → asyncio.Lock
        # Ensures only one test_server call runs at a time per server; concurrent
        # callers wait for the in-flight test to finish and return its result.
        self._test_locks: dict[str, asyncio.Lock] = {}

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
        """Return the current build record.

        In-memory record takes priority (hot path during a live test run).
        On cache miss the persisted build result is loaded from the DB so
        tools_discovered and test_results survive backend restarts.
        """
        server = await self._load_and_verify(server_id, user_id)
        async with self._lock:
            if server_id in self._records:
                return self._records[server_id]

        # Cache miss — load persisted result from DB.
        row = await self._repo.get(server_id)
        if row and (row.get("tools_discovered") or row.get("status") not in (None, "not_running")):
            phase = row.get("status") or "idle"
            # Map DB status back to MCPBuildRecord phase names.
            if phase not in ("idle", "building", "testing", "verified", "failed", "ready", "stopped"):
                phase = "idle"
            record = MCPBuildRecord(
                server_id=server_id,
                phase=phase,
                owner_id=user_id,
                required_key_names=server.get("detected_secrets") or [],
                tools_discovered=row.get("tools_discovered") or [],
                test_results=row.get("test_results") or [],
                last_verified_at=row.get("last_verified_at"),
            )
        else:
            record = MCPBuildRecord(server_id=server_id, phase="idle", owner_id=user_id)

        async with self._lock:
            self._records.setdefault(server_id, record)
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

    @staticmethod
    def _is_auth_error(msg: str) -> bool:
        """Return True if msg looks like a 401/403 / authentication failure.

        A tool that raises an auth-style error is still callable — the placeholder
        key is just not valid. This counts as ok=True in test-call results.
        """
        return bool(_AUTH_ERROR_RE.search(msg))

    @staticmethod
    def _extract_egress_hosts(source: str) -> list[str]:
        """Extract unique API hostnames from https?:// URL literals in source.

        Used as a fallback when the build flow didn't explicitly populate
        egress_hosts. Gives the LLM scanner the allowlist it needs to approve a
        normal API connector without flagging standard Bearer-auth as exfiltration.
        """
        return sorted(set(_HTTPS_HOST_RE.findall(source)))

    async def _run_server_sandbox_test(
        self,
        *,
        server_id: str,
        user_id: str,
        source_code: str,
    ) -> tuple[list[dict], list[dict]]:
        """Two-phase sandbox test: discovery (no secrets) then test-calls (placeholders).

        Phase 1 — Discovery (no secrets injected):
          Start the server with a clean environment, connect the MCP client, and
          call list_tools. Tool registration must not require any secret — secrets
          are read inside tool handlers at call time, not at startup. If the server
          crashes at startup with no secrets, that is a generation defect.

        Phase 2 — Test-calls (placeholder secrets only):
          Restart with placeholder env vars, call each discovered tool with empty
          args. A 401/403 or auth-style exception means the tool is callable and
          the key is merely not valid → ok: True. Only a crash, timeout, or
          unrelated error counts as ok: False. Phase 2 never blocks 'verified'.

        Real secrets are NEVER injected here.
        Returns (tools_discovered, test_results) — neither contains real secret values.
        """
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        site_packages = str(Path(sys.executable).parent.parent / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages")
        base_env: dict[str, str] = {
            "PYTHONPATH": site_packages,
            "HOME": str(Path.home()),
            "PATH": "/usr/bin:/bin",
        }

        tools_discovered: list[dict] = []
        test_results: list[dict] = []

        with tempfile.TemporaryDirectory(prefix="omni_mcp_test_") as tmpdir:
            server_file = Path(tmpdir) / "server.py"
            server_file.write_text(source_code)

            # ── Phase 1: Discovery — no secrets, validates clean startup ─────
            discovery_params = StdioServerParameters(
                command=sys.executable,
                args=[str(server_file)],
                env=base_env,
            )
            try:
                async with asyncio.timeout(30):
                    async with stdio_client(discovery_params) as (read, write):
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
            except TimeoutError:
                raise RuntimeError("MCP server discovery timed out (30s)")
            # Other startup/connection exceptions propagate to caller

            if not tools_discovered:
                return [], []

            # ── Phase 2: Test-calls — placeholder secrets, auth errors are ok ─
            key_names = await self._vault.list_key_names(server_id=server_id, owner_id=user_id)
            placeholder_env: dict[str, str] = {k: f"placeholder_for_{k}" for k in key_names}

            test_params = StdioServerParameters(
                command=sys.executable,
                args=[str(server_file)],
                env={**base_env, **placeholder_env},
            )
            try:
                async with asyncio.timeout(30):
                    async with stdio_client(test_params) as (read, write):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            for t in tools_discovered:
                                try:
                                    result = await asyncio.wait_for(
                                        session.call_tool(t["name"], {}),
                                        timeout=10,
                                    )
                                    output = ""
                                    if result.content:
                                        item = result.content[0]
                                        output = str(getattr(item, "text", None) or item)[:200]
                                    test_results.append({"tool": t["name"], "ok": True, "output": output})
                                except Exception as exc:
                                    exc_msg = str(exc)[:200]
                                    ok = self._is_auth_error(exc_msg)
                                    entry: dict = {"tool": t["name"], "ok": ok}
                                    if ok:
                                        entry["output"] = exc_msg
                                    else:
                                        entry["error"] = exc_msg
                                    test_results.append(entry)
            except Exception as exc:
                # Test-call phase failure never blocks 'verified' — tools were already discovered.
                logger.warning("MCP test-call phase failed for %s: %s", server_id, exc)

        return tools_discovered, test_results

    async def submit_source_and_test(self, *, server_id: str, user_id: str, source_code: str) -> MCPBuildRecord:
        """Save source_code then run the full test pipeline.

        Ownership gate is at the top — identical to every other mutating method.
        """
        await self._load_and_verify(server_id, user_id)
        await self._repo.update_source_code(server_id, source_code, user_id=user_id)
        return await self.test_server(server_id=server_id, user_id=user_id)

    async def test_server(self, *, server_id: str, user_id: str) -> MCPBuildRecord:
        """Run the full test pipeline: static scan → LLM scan → sandbox execution.

        Ownership is verified at the top. Agent-generated code never runs in the
        gateway process — it is launched as a subprocess via _run_server_sandbox_test.

        Missing secrets are no longer a blocker. Secrets are read at tool-call time;
        the server starts and registers its tools regardless of whether keys are stored.
        required_key_names is still detected and returned for informational display.

        Concurrent /test calls for the same server are serialised: the second caller
        waits for the first to finish, then returns the cached record instead of
        launching a duplicate sandbox process.
        """
        # Ownership gate before acquiring the per-server lock so a bad caller fails fast.
        await self._load_and_verify(server_id, user_id)

        async with self._lock:
            if server_id not in self._test_locks:
                self._test_locks[server_id] = asyncio.Lock()
        per_server_lock = self._test_locks[server_id]

        if per_server_lock.locked():
            # Another test is already in flight — wait for it, then return cached result.
            async with per_server_lock:
                pass
            async with self._lock:
                cached = self._records.get(server_id)
            if cached is not None:
                return cached

        async with per_server_lock:
            server = await self._load_and_verify(server_id, user_id)

            source = server.get("source_code") or ""
            egress_hosts = server.get("egress_hosts") or []

            # Stage 1: static scan (immediate, no LLM) — hard-blocks dangerous patterns.
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

            # Stage 2: detect required env-var key names (informational — never a blocker).
            # Secrets are read inside tool handlers at call time, not at startup. A server
            # that crashes at startup without its keys has a generation defect, not a missing
            # secret — discovery (Phase 1 of the sandbox test) catches that separately.
            required_key_names = self._vault.scan_for_required_keys(source) if source else []

            # Auto-populate egress_hosts from URL literals when the build flow didn't set
            # them explicitly. Without this, the LLM scanner has no declared allowlist and
            # treats standard Bearer-auth to the server's own API as potential exfiltration.
            if source and not egress_hosts:
                egress_hosts = self._extract_egress_hosts(source)
                if egress_hosts:
                    logger.debug("Auto-extracted egress hosts for %s: %s", server_id, egress_hosts)

            # Stage 3: LLM scan for intent-level threats. egress_hosts are passed so the
            # reviewer can distinguish a normal API connector (sending its key to its own
            # declared endpoint) from exfiltration to undeclared hosts.
            if source:
                scan_result = await scan_python_code(source, location=f"mcp:{server_id}", egress_hosts=egress_hosts)
                if scan_result.decision == "block":
                    await self._repo.update_status(server_id, "failed", user_id=user_id)
                    # Persist detected secrets even on scan failure so the UI can show
                    # which keys are needed before the user fixes and re-tests.
                    if required_key_names:
                        await self._repo.update_detected_secrets(server_id, required_key_names, user_id=user_id)
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
            build_egress_rules(egress_hosts)

            # Stage 5: two-phase sandbox test (discovery: no secrets; test-calls: placeholder).
            # "verified" = scan gates passed AND server started cleanly AND tools discovered.
            # Test-call auth errors (401/403) never block 'verified'.
            # Real secrets are never injected here.
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

            await self._repo.update_build_result(
                server_id,
                phase=phase,
                tools_discovered=tools_discovered,
                test_results=test_results,
                last_verified_at=verified_at,
                user_id=user_id,
            )
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
