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
   launches it as a subprocess with a clean, constrained environment (only the owner's
   decrypted secrets + PYTHONPATH/HOME/PATH; no gateway env vars leak in).
"""

from __future__ import annotations

import asyncio
import dataclasses
import io
import json
import logging
import re
import socket
import sys
import tarfile
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from app.gateway.mcp_build_flow import placeholder, scrub
from app.gateway.mcp_docker import CliDockerRunner, DockerRunner
from app.gateway.mcp_egress import build_egress_rules
from app.gateway.mcp_secrets import McpSecretsVault
from omniharness.persistence.mcp_server.approval import code_sha256
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

# Patterns indicating the tool requires arguments we didn't supply in the automated test.
# These are expected for tools that mandate owner/repo/id-style inputs.
_MISSING_ARGS_RE = re.compile(
    r"(Field required|validation error|missing.*required|required.*missing|"
    r"InputValidationError|argument.*required|required.*argument)",
    re.IGNORECASE,
)


def _classify_output(text: str) -> str:
    """Return a label for the output/error text of a test-call result.

    ``"pass"``  — no recognisable error pattern (tool actually returned a useful result)
    ``"auth"``  — 401/403/auth failure (callable; placeholder credentials used in tests)
    ``"args"``  — missing required arguments (callable; no default args supplied in tests)
    ``"error"`` — other error
    """
    if not text:
        return "pass"
    if _AUTH_ERROR_RE.search(text):
        return "auth"
    if _MISSING_ARGS_RE.search(text):
        return "args"
    # Any non-empty error-like text that doesn't fit the above patterns
    lower = text.lower()
    if "error" in lower or "exception" in lower or "failed" in lower or "traceback" in lower:
        return "error"
    return "pass"


# Matches the entire __main__ block from "if __name__" to end-of-file.
# Generated server.py files always end with this block, so replacing to EOF is safe.
_MAIN_BLOCK_RE = re.compile(
    r'^if\s+__name__\s*==\s*[\'"]__main__[\'"].*',
    re.MULTILINE | re.DOTALL,
)
# Canonical dual-transport __main__ block written into every Docker image.
# FastMCP.run() does NOT accept host=/port= kwargs — those must be set on
# mcp.settings before run(). transport_security is cleared so Docker port-
# mapping from the host is not blocked by localhost rebinding protection.
_DOCKER_MAIN_NEW = (
    'if __name__ == "__main__":\n'
    '    _transport = os.environ.get("MCP_TRANSPORT", "stdio")\n'
    '    if _transport == "sse":\n'
    '        mcp.settings.host = "0.0.0.0"\n'
    '        mcp.settings.port = int(os.environ.get("MCP_PORT", "8080"))\n'
    "        mcp.settings.transport_security = None\n"
    '        mcp.run(transport="sse")\n'
    "    else:\n"
    "        mcp.run()\n"
)
# MCP_TRANSPORT selects stdio (sandbox) vs sse (Docker). MCP_PORT sets the
# container's listen port, which is mapped to a dynamic host port by docker run.
_DOCKERFILE_TEMPLATE = """\
FROM python:3.12-slim
WORKDIR /app
COPY server.py .
RUN pip install --no-cache-dir mcp httpx
ENV MCP_TRANSPORT=sse
ENV MCP_PORT=8080
EXPOSE 8080
CMD ["python", "server.py"]
"""
_DEPLOY_PORT_BASE = 18100

# Ordered deploy steps emitted as live timeline data to the frontend.
_DEPLOY_STEP_DEFS: list[tuple[str, str]] = [
    ("preparing", "Preparing source"),
    ("building", "Building Docker image"),
    ("launching", "Starting container"),
    ("registering", "Registering deployment"),
]


def _init_deploy_steps() -> list[dict]:
    """Return the initial step list with the first step 'running', rest 'pending'."""
    steps = []
    for i, (key, label) in enumerate(_DEPLOY_STEP_DEFS):
        steps.append({"key": key, "label": label, "status": "running" if i == 0 else "pending", "detail": None})
    return steps


def _tar_context(files: dict[str, str]) -> bytes:
    """A docker build context as an in-memory tar (no files on disk)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, text in files.items():
            data = text.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _patch_main_for_sse(source: str) -> str:
    """Replace the __main__ block with the canonical dual-transport form.

    Always rewrites — handles bare mcp.run(), old bad host=/port= kwargs,
    and already-patched-but-incorrect blocks in one pass.
    """
    return _MAIN_BLOCK_RE.sub(_DOCKER_MAIN_NEW.rstrip(), source)


class McpTeardownError(RuntimeError):
    """Stopping or deleting a server left something behind; the caller must not report success."""


class McpContainerRemovalError(McpTeardownError):
    """The server's container could not be stopped and removed."""


class McpDeployInProgressError(RuntimeError):
    """A deploy is running; stopping now would race the container it starts."""


def _container_name(server_id: str) -> str:
    return f"omni-mcp-{server_id[:12]}"


def _config_entry_name(server_name: str) -> str:
    """The extensions_config.json key ``connect`` writes for a server."""
    return re.sub(r"[^a-z0-9\-]", "-", server_name.lower()).strip("-")


# The URL ``connect`` writes: a studio container on a local port. An entry with
# the same name but another URL was written by someone else and is left alone.
_STUDIO_SSE_URL_RE = re.compile(r"^http://(localhost|host\.docker\.internal):\d+/sse$")


def _remove_config_entry(server: dict) -> None:
    """Drop the server's entry from extensions_config.json, if ``connect`` wrote one.

    Edits the file as JSON so every other key is kept as written, then reloads
    the cached config so agents stop seeing the server.
    """
    from omniharness.config.extensions_config import ExtensionsConfig, atomic_write_json, reload_extensions_config

    name = _config_entry_name(server["name"])
    try:
        path = ExtensionsConfig.resolve_config_path()
        if path is None or not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
        servers = data.get("mcpServers") or {}
        entry = servers.get(name)
        if not isinstance(entry, dict) or not _STUDIO_SSE_URL_RE.match(str(entry.get("url") or "")):
            return
        del servers[name]
        atomic_write_json(path, data)
        reload_extensions_config()
    except (OSError, ValueError) as exc:
        raise McpTeardownError(f"could not remove {name!r} from extensions_config.json: {exc}") from exc
    logger.info("MCP server %s: removed extensions_config entry %r", server["id"][:12], name)


@dataclass
class MCPBuildRecord:
    """Runtime record for a single MCP server's current build/test phase.

    Contains phase, key NAMES (never values), and test results only.
    No ciphertext, no plaintext secrets, no env-var values appear here.
    tools_discovered and test_results contain names/descriptions/boolean outcomes only.
    """

    server_id: str
    phase: Literal["idle", "building", "testing", "verified", "ready", "failed", "stopped", "deploying", "deployed"]
    owner_id: str
    required_key_names: list[str] = field(default_factory=list)
    tools_discovered: list[dict] = field(default_factory=list)
    test_results: list[dict] = field(default_factory=list)
    error: str | None = None
    last_verified_at: str | None = None
    container_id: str | None = None
    container_port: int | None = None
    # Live step list emitted during "deploying" phase so the frontend can render a timeline.
    # Each dict: {key, label, status: pending|running|done|failed, detail: str|None}
    deploy_steps: list[dict] = field(default_factory=list)


class MCPServerManager:
    """Lifecycle manager for agent-built MCP servers.

    Created once in the app lifespan and stored on ``app.state``.
    """

    def __init__(self, repo: McpServerRepository, vault: McpSecretsVault, runner: DockerRunner | None = None) -> None:
        self._repo = repo
        self._vault = vault
        self._runner: DockerRunner = runner or CliDockerRunner()
        # Per-server lock held while the stored code changes and while a deploy
        # makes its final check before `docker run`: new code can't slip in
        # between "this is the approved code" and starting it (#59, T15).
        self._source_locks: dict[str, asyncio.Lock] = {}
        # In-memory phase tracking: server_id → MCPBuildRecord
        self._records: dict[str, MCPBuildRecord] = {}
        self._lock = asyncio.Lock()
        # Per-server in-flight test locks: server_id → asyncio.Lock
        # Ensures only one test_server call runs at a time per server; concurrent
        # callers wait for the in-flight test to finish and return its result.
        self._test_locks: dict[str, asyncio.Lock] = {}
        # Feature 006 Build: server_id -> the build agent's run, so "drafting"
        # is observed (a run in progress), not assumed. In memory only.
        self._build_runs: dict[str, object] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def note_build_run(self, server_id: str, run: object) -> None:
        """Remember the agent run that is building *server_id*."""
        self._build_runs[server_id] = run

    def build_run(self, server_id: str) -> object | None:
        """The build run this process started for *server_id*, if any."""
        return self._build_runs.get(server_id)

    def _source_lock(self, server_id: str) -> asyncio.Lock:
        lock = self._source_locks.get(server_id)
        if lock is None:
            lock = self._source_locks[server_id] = asyncio.Lock()
        return lock

    def is_testing(self, server_id: str) -> bool:
        """True while a sandbox test of *server_id* is running."""
        lock = self._test_locks.get(server_id)
        return bool(lock and lock.locked())

    async def stored_secrets(self, *, server_id: str, user_id: str) -> dict[str, str]:
        """The values stored for *server_id* (for scrubbing only; never returned)."""
        try:
            return await self._vault._decrypt_for_sandbox(server_id=server_id, owner_id=user_id)
        except Exception:
            return {}

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
                container_id=row.get("container_id"),
                container_port=row.get("container_port"),
            )
        else:
            record = MCPBuildRecord(server_id=server_id, phase="idle", owner_id=user_id)

        async with self._lock:
            self._records.setdefault(server_id, record)
            return self._records[server_id]

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

        Phase 2 — Test-calls (real secrets injected):
          Restart with the owner's actual decrypted credentials, call each discovered
          tool with empty args. Tools with zero required args (whoami, rate_limit,
          health checks) make genuine API calls — green "pass" means the key works.
          Tools with required args (owner, repo) return validation errors → "args" badge.
          Auth failures (401/403) with non-functional keys → "401" badge.
          Only a crash or timeout counts as ok: False. Phase 2 never blocks 'verified'.
          Output is scrubbed for real secret values before being stored.

        Returns (tools_discovered, test_results) — output/error fields are scrubbed.
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

            # ── Phase 2: Test-calls — PLACEHOLDER secrets (Feature 006) ─────
            # The sandbox is away from your data: tests never get the real
            # credentials. Each key the code reads is set to its placeholder, so
            # a tool that needs it answers with an auth error ("auth" badge,
            # still callable) instead of making a real call. The first real
            # run is the one the user approves (deploy). Tools that require
            # arguments get validation errors with empty {} ("args" badge).
            names = set(self._vault.scan_for_required_keys(source_code))
            try:
                names |= {k["key_name"] for k in await self._vault.list_key_info(server_id=server_id, owner_id=user_id)}
            except Exception:
                pass  # names only; the code's own reads are already covered
            placeholder_env = {name: placeholder(name) for name in names}

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
                                    # Classify result even on the success path — the tool may have
                                    # returned an error payload (auth failure, missing args) rather
                                    # than raising a Python exception. We label these so the UI can
                                    # show the right badge instead of a misleading green "pass".
                                    output_type = _classify_output(output)
                                    entry: dict = {"tool": t["name"], "ok": True, "output_type": output_type}
                                    if output:
                                        entry["output"] = output
                                    test_results.append(entry)
                                except Exception as exc:
                                    exc_msg = str(exc)[:200]
                                    is_auth = self._is_auth_error(exc_msg)
                                    output_type = "auth" if is_auth else _classify_output(exc_msg)
                                    entry = {"tool": t["name"], "ok": is_auth, "output_type": output_type}
                                    if is_auth:
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
        async with self._source_lock(server_id):
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

            # The outbound hosts are read from THIS code, and only from it (#59):
            # the same bytes that are hashed for approval. A client never sets
            # them. Persisted, so the approval screen shows what will be enforced.
            egress_hosts = self._extract_egress_hosts(source) if source else []
            await self._repo.update_egress_hosts(server_id, egress_hosts, user_id=user_id)

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

            # Stage 5: two-phase sandbox test (discovery: no secrets; test-calls: real secrets).
            # "verified" = scan gates passed AND server started cleanly AND tools discovered.
            # Test-call auth/args errors never block 'verified' — they're classified by badge.
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

            # Defense in depth: every stored value that appears in test output
            # or errors becomes its placeholder ({{secret:NAME}}) before it is
            # stored, returned to the build agent, or shown. Always, not only
            # when the code was seen to read a key.
            if test_results:
                stored = await self.stored_secrets(server_id=server_id, user_id=user_id)
                for tr in test_results:
                    for field_name in ("output", "error"):
                        if field_name in tr and tr[field_name]:
                            tr[field_name] = scrub(str(tr[field_name]), stored)
                del stored

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

    async def begin_approval(
        self,
        *,
        server_id: str,
        user_id: str,
        code_sha256_seen: str,
        tool_tiers: dict[str, int] | None = None,
    ) -> dict:
        """Record the user's approval of the code they saw, as PENDING.

        Refused (``PermissionError``) unless the sandbox tests passed (phase
        verified) and *code_sha256_seen* is the hash of the code stored now.
        The approval only becomes real when the deploy succeeds
        (``_run_docker_deploy`` commits it); a failed deploy clears it, so
        nothing is left approved that never turned on (#59).
        """
        server = await self._load_and_verify(server_id, user_id)
        current = code_sha256(server.get("source_code"))
        if current is None:
            raise ValueError("No source code — build the server first")
        status = await self.get_status(server_id=server_id, user_id=user_id)
        if status.phase != "verified" and server.get("status") != "verified":
            raise PermissionError(f"MCP server {server_id!r} cannot be approved from phase {status.phase!r}: its sandbox tests must pass first")
        if code_sha256_seen != current:
            raise PermissionError("code changed: the code you approved is not the code stored now")
        tools = {t.get("name") for t in (server.get("tools_discovered") or status.tools_discovered or [])}
        tiers = dict(tool_tiers or {})
        for name, tier in tiers.items():
            if name not in tools or tier not in (1, 2, 3):
                raise ValueError(f"invalid tier for tool {name!r}")
        pending = {
            "code_sha256": current,
            "egress_hosts": list(server.get("egress_hosts") or []),
            "tool_tiers": {name: tiers.get(name, 3) for name in sorted(t for t in tools if t)},
            "approved_by": user_id,
            "approved_at": datetime.now(UTC).isoformat(),
        }
        await self._repo.set_pending_approval(server_id, pending, user_id=user_id)
        return pending

    async def stop(self, *, server_id: str, user_id: str) -> MCPBuildRecord:
        """Stop a server: stop and remove its container, drop its agent config entry.

        Before, this only changed the status, and the container kept running
        (``--restart unless-stopped``) with the owner's secrets in its env.
        Raises ``McpContainerRemovalError`` when the container could not be
        removed; the status is then left as it was, so nothing claims success.
        """
        server = await self._load_and_verify(server_id, user_id)
        async with self._lock:
            existing = self._records.get(server_id)
        if existing is not None and existing.phase == "deploying":
            raise McpDeployInProgressError("A deploy is in progress. Wait for it to finish, then stop the server.")
        await self._remove_container(server_id, server)
        _remove_config_entry(server)
        await self._repo.update_container_info(
            server_id,
            container_id=None,
            container_port=None,
            status="stopped",
            user_id=user_id,
        )
        record = MCPBuildRecord(
            server_id=server_id,
            phase="stopped",
            owner_id=user_id,
            required_key_names=existing.required_key_names if existing else [],
            tools_discovered=existing.tools_discovered if existing else [],
            test_results=existing.test_results if existing else [],
            last_verified_at=existing.last_verified_at if existing else None,
        )
        async with self._lock:
            self._records[server_id] = record
        return record

    async def _remove_container(self, server_id: str, server: dict) -> None:
        """``docker stop`` then ``docker rm`` this server's container.

        A container that does not exist counts as removed. Any other failure
        raises ``McpContainerRemovalError`` with docker's own words.
        """
        name = _container_name(server_id)
        for verb in ("stop", "rm"):
            try:
                rc, _, err = await self._runner.run(["docker", verb, name], timeout=60.0)
            except FileNotFoundError:
                # No docker CLI here. If a container was recorded, it may still be
                # running somewhere we cannot reach: say so. If none ever was,
                # there is nothing to remove.
                if server.get("container_id"):
                    raise McpContainerRemovalError(f"docker is not available, so container {name} could not be removed")
                return
            except TimeoutError:
                raise McpContainerRemovalError(f"docker {verb} {name} timed out")
            if rc != 0 and "no such container" not in err.lower():
                raise McpContainerRemovalError(f"docker {verb} {name} failed: {err.strip()[:300]}")
        logger.info("MCP server %s: container %s stopped and removed", server_id[:12], name)

    # ------------------------------------------------------------------
    # Docker deploy / undeploy / connect
    # ------------------------------------------------------------------

    async def _advance_step(self, server_id: str, done_key: str, next_key: str | None, *, detail: str | None = None) -> list[dict]:
        """Mark `done_key` as done (with optional detail) and `next_key` as running.
        Returns the updated steps list so the caller can keep a local reference."""
        async with self._lock:
            rec = self._records.get(server_id)
            if rec is None:
                return []
            steps = [
                {
                    **s,
                    "status": "done",
                    "detail": detail if s["key"] == done_key else s.get("detail"),
                }
                if s["key"] == done_key
                else ({**s, "status": "running"} if s["key"] == next_key else s)
                for s in rec.deploy_steps
            ]
            self._records[server_id] = dataclasses.replace(rec, deploy_steps=steps)
        return steps

    async def _fail_step(self, server_id: str, failed_key: str, error: str) -> None:
        """Mark `failed_key` as failed and set record to phase=failed."""
        async with self._lock:
            rec = self._records.get(server_id)
            if rec is None:
                return
            # A test run may have replaced the record mid-deploy (new code
            # submitted): the failure is still shown as a deploy step.
            current = rec.deploy_steps or _init_deploy_steps()
            steps = [{**s, "status": "failed", "detail": error} if s["key"] == failed_key else ({**s, "status": "pending"} if s["status"] == "running" else s) for s in current]
            self._records[server_id] = dataclasses.replace(rec, phase="failed", error=error, deploy_steps=steps)

    @staticmethod
    def _find_free_port(start: int = _DEPLOY_PORT_BASE) -> int:
        for port in range(start, start + 100):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(("", port))
                    return port
                except OSError:
                    continue
        raise RuntimeError(f"No free port found in range {start}–{start + 100}")

    async def deploy(self, *, server_id: str, user_id: str, connect_after: bool = False) -> MCPBuildRecord:
        """Validate, mark as deploying, fire Docker work in background, return immediately.

        The endpoint returns a ``{phase: "deploying"}`` record right away so the
        browser is never blocked waiting for ``docker build``. The frontend polls
        ``GET /build`` which reflects the in-memory record; the background task
        transitions the record to ``"deployed"`` or ``"failed"`` when done.

        Raises ``PermissionError`` on ownership failure, ``ValueError`` if no
        source code exists. Secrets are injected as env vars and NOT logged.
        """
        server = await self._load_and_verify(server_id, user_id)
        source = server.get("source_code") or ""
        # Feature 006 #59: deploying gives the code real credentials, so the
        # code stored NOW must be the approved code, or be the code of an
        # approval that is turning on. Nothing else turns a server on.
        current = code_sha256(source)
        pending = server.get("pending_approval") or None
        if current is not None and (server.get("approved") or (pending and pending.get("code_sha256") == current)):
            expected = current
        else:
            raise PermissionError(f"MCP server {server_id!r} has not been approved: approve its first run before turning it on")

        async with self._lock:
            existing = self._records.get(server_id)
        deploying = MCPBuildRecord(
            server_id=server_id,
            phase="deploying",
            owner_id=user_id,
            required_key_names=existing.required_key_names if existing else [],
            tools_discovered=existing.tools_discovered if existing else [],
            test_results=existing.test_results if existing else [],
            last_verified_at=existing.last_verified_at if existing else None,
            deploy_steps=_init_deploy_steps(),
        )
        async with self._lock:
            self._records[server_id] = deploying

        # Fire the slow docker work in the background — caller returns immediately.
        asyncio.create_task(
            self._run_docker_deploy(
                server_id=server_id,
                user_id=user_id,
                source=source,
                expected_sha256=expected,
                existing=existing,
                connect_after=connect_after,
            ),
            name=f"mcp-deploy-{server_id[:12]}",
        )
        return deploying

    async def _run_docker_deploy(
        self,
        *,
        server_id: str,
        user_id: str,
        source: str,
        expected_sha256: str | None = None,
        existing: MCPBuildRecord | None = None,
        connect_after: bool = False,
    ) -> None:
        """Background task: docker build + docker run, update in-memory record when done.

        The approval this deploy carries (pending or existing) is for
        *expected_sha256*. Right before ``docker run``, under the same lock a
        code change takes, the stored code is read again and must still hash
        to it; otherwise nothing is started and the pending approval is
        dropped (#59, T15). A pending approval is committed only after the
        container is up; any failure clears it.
        """
        expected_sha256 = expected_sha256 or code_sha256(source)

        def _make_record(phase: str, **kwargs: object) -> MCPBuildRecord:
            return MCPBuildRecord(
                server_id=server_id,
                phase=phase,  # type: ignore[arg-type]
                owner_id=user_id,
                required_key_names=existing.required_key_names if existing else [],
                tools_discovered=existing.tools_discovered if existing else [],
                test_results=existing.test_results if existing else [],
                last_verified_at=existing.last_verified_at if existing else None,
                **kwargs,  # type: ignore[arg-type]
            )

        image_tag = _container_name(server_id)
        container_name = _container_name(server_id)
        patched = _patch_main_for_sse(source)

        try:
            # ── Step 1: Preparing ──────────────────────────────────────────
            # (already set to "running" by deploy(); just do the work)
            if code_sha256(source) != expected_sha256:
                await self._refuse_changed(server_id, user_id, "preparing")
                return
            context = _tar_context({"server.py": patched, "Dockerfile": _DOCKERFILE_TEMPLATE})
            await self._advance_step(server_id, "preparing", "building", detail="Source patched for SSE transport")

            # ── Step 2: Building ──────────────────────────────────────
            rc, _, err = await self._runner.run(["docker", "build", "-t", image_tag, "-"], stdin=context, timeout=300.0)
            if rc != 0:
                await self._fail_deploy(server_id, user_id, "building", f"docker build failed: {err[:400]}")
                return

            await self._advance_step(server_id, "building", "launching", detail="Image built successfully")

            # ── Step 3: Launching ─────────────────────────────────────────
            host_port = self._find_free_port()

            # Decrypt real secrets — injected as env vars, NOT logged
            real_env: dict[str, str] = {}
            try:
                real_env = await self._vault._decrypt_for_sandbox(server_id=server_id, owner_id=user_id)
            except Exception:
                pass

            run_args: list[str] = [
                "docker",
                "run",
                "-d",
                "--name",
                container_name,
                "-p",
                # Loopback only (security baseline): reached at localhost or, from
                # a containerised gateway on Docker Desktop, host.docker.internal.
                f"127.0.0.1:{host_port}:8080",
                "--restart",
                "unless-stopped",
            ]
            for k, v in real_env.items():
                run_args += ["-e", f"{k}={v}"]
            run_args.append(image_tag)

            async with self._source_lock(server_id):
                # The final check: the code stored now is the code this
                # approval is for. A change made while the image built is
                # caught here, before anything runs with real secrets.
                row = await self._repo.get(server_id, user_id=user_id)
                if row is None or code_sha256(row.get("source_code")) != expected_sha256:
                    await self._refuse_changed(server_id, user_id, "launching")
                    return
                # Remove any previous container (non-fatal), then start this one.
                await self._runner.run(["docker", "rm", "-f", container_name], timeout=15.0)
                rc, out, err = await self._runner.run(run_args, timeout=30.0)
            if rc != 0:
                await self._fail_deploy(server_id, user_id, "launching", f"docker run failed: {err[:400]}")
                return

            container_id = out.strip()[:128]
            await self._advance_step(server_id, "launching", "registering", detail=f"Container started on port {host_port}")

            # A pending approval becomes the approval only now that it runs.
            row = await self._repo.get(server_id, user_id=user_id)
            if row is not None and (row.get("pending_approval") or {}).get("code_sha256") == expected_sha256:
                if not await self._repo.commit_approval(server_id, expected_sha256=expected_sha256, user_id=user_id):
                    await self._runner.run(["docker", "rm", "-f", container_name], timeout=15.0)
                    await self._fail_deploy(server_id, user_id, "registering", "the code changed while turning on; review it again")
                    return

            # ── Step 4: Registering ───────────────────────────────────────
            await self._repo.update_container_info(
                server_id,
                container_id=container_id,
                container_port=host_port,
                status="deployed",
                user_id=user_id,
            )
            # Finalize: mark registering done and flip phase to deployed
            async with self._lock:
                rec = self._records.get(server_id)
                if rec is not None:
                    final_steps = [{**s, "status": "done"} if s["key"] == "registering" else s for s in rec.deploy_steps]
                    self._records[server_id] = dataclasses.replace(
                        rec,
                        phase="deployed",
                        container_id=container_id,
                        container_port=host_port,
                        deploy_steps=final_steps,
                    )
            logger.info("MCP server %s deployed: container=%s port=%s", server_id[:12], container_id[:12], host_port)
            if connect_after:
                # "Approve and turn on": the agents get its tools now.
                await self.connect(server_id=server_id, user_id=user_id)

        except Exception as exc:
            logger.error("Docker deploy failed for %s: %s", server_id[:12], exc)
            await self._fail_deploy(server_id, user_id, "launching", f"deploy error: {str(exc)[:400]}")

    async def _fail_deploy(self, server_id: str, user_id: str, step: str, error: str) -> None:
        """A deploy failed: the step says why, and an approval that was
        turning on is dropped, so nothing stays approved that never ran."""
        await self._fail_step(server_id, step, error)
        try:
            await self._repo.set_pending_approval(server_id, None, user_id=user_id)
        except Exception:
            logger.exception("could not clear the pending approval of %s", server_id[:12])

    async def _refuse_changed(self, server_id: str, user_id: str, step: str) -> None:
        await self._fail_deploy(server_id, user_id, step, "The code changed while turning on; review it again")

    async def undeploy(self, *, server_id: str, user_id: str) -> MCPBuildRecord:
        """Stop and remove the Docker container for this server (same as ``stop``)."""
        return await self.stop(server_id=server_id, user_id=user_id)

    async def connect(self, *, server_id: str, user_id: str) -> dict[str, str]:
        """Register the deployed container's SSE URL into extensions_config.json.

        Reads the container port from the in-memory record (or DB), constructs
        the SSE URL, and upserts the server entry in extensions_config.json.
        The config file's mtime change triggers automatic hot-reload in the agent.

        Returns {"sse_url": ..., "server_name": ...}.
        """
        from omniharness.config.extensions_config import ExtensionsConfig, get_extensions_config, reload_extensions_config

        db_server = await self._load_and_verify(server_id, user_id)
        if not db_server.get("approved"):
            raise PermissionError(f"MCP server {server_id!r} has not been approved")
        async with self._lock:
            record = self._records.get(server_id)

        container_port = (record.container_port if record else None) or db_server.get("container_port")
        if not container_port:
            raise ValueError("Server is not deployed — run deploy first")

        # When the gateway runs inside Docker, `localhost` resolves to the
        # container itself — not the host machine where MCP containers run.
        # `host.docker.internal` is Docker Desktop's magic hostname for the host.
        # On a bare host (make dev), `localhost` is correct.
        _in_docker = Path("/.dockerenv").exists()
        internal_host = "host.docker.internal" if _in_docker else "localhost"
        display_host = "localhost"  # always localhost for the user's browser

        internal_url = f"http://{internal_host}:{container_port}/sse"
        display_url = f"http://{display_host}:{container_port}/sse"
        server_name = _config_entry_name(db_server["name"])

        config_path = ExtensionsConfig.resolve_config_path()
        if config_path is None:
            config_path = Path.cwd().parent / "extensions_config.json"

        current_cfg = get_extensions_config()
        config_data: dict = {
            "mcpServers": {n: s.model_dump() for n, s in current_cfg.mcp_servers.items()},
            "skills": {n: {"enabled": sk.enabled} for n, sk in current_cfg.skills.items()},
        }
        config_data["mcpServers"][server_name] = {
            "enabled": True,
            "type": "sse",
            "url": internal_url,  # gateway-accessible URL
            "description": db_server.get("description") or f"MCP server: {db_server['name']}",
        }
        with open(config_path, "w", encoding="utf-8") as fh:
            json.dump(config_data, fh, indent=2)

        reload_extensions_config()
        logger.info("MCP server %r connected at %s (extensions_config updated)", server_name, internal_url)
        return {"sse_url": display_url, "server_name": server_name}
