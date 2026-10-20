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

4. Agent-generated code NEVER runs in the gateway, not even as a subprocess
   (#59). ``_run_server_sandbox_test`` runs it in a container: no network,
   read-only root, non-root, all capabilities dropped, memory/pids/CPU limits,
   no host mounts, and placeholder keys only, handed over as a 0400 file on a
   tmpfs (never in its environment).
"""

from __future__ import annotations

import asyncio
import dataclasses
import ipaddress
import json
import logging
import os
import re
import secrets
import socket
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from app.gateway.mcp_build_flow import placeholder, scrub
from app.gateway.mcp_container_files import deliver, render_secrets, secret_name_problem
from app.gateway.mcp_docker import CliDockerRunner, DockerRunner
from app.gateway.mcp_egress import build_egress_rules
from app.gateway.mcp_egress_config import UPSTREAM_DNS, allowlist_hosts, proxy_password_line, render_dnsmasq, render_squid
from app.gateway.mcp_names import name_collision, slugify, tool_name_collision, wire_key
from app.gateway.mcp_runtime_image import RuntimeImages
from app.gateway.mcp_secrets import McpSecretsVault
from app.gateway.mcp_view_tokens import ViewTokens
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
# A tool that needed the network: in the sandbox there is none (#59), so this
# is expected, not a defect. Still callable.
_OFFLINE_RE = re.compile(
    r"(ConnectError|ConnectTimeout|Temporary failure in name resolution|Name or service not known|"
    r"nodename nor servname|Network is unreachable|No address associated|getaddrinfo failed|Errno -[23])",
    re.IGNORECASE,
)

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
    ``"offline"`` — it needed the network; the sandbox has none (callable)
    ``"error"`` — other error
    """
    if not text:
        return "pass"
    if _OFFLINE_RE.search(text):
        return "offline"
    if _AUTH_ERROR_RE.search(text):
        return "auth"
    if _MISSING_ARGS_RE.search(text):
        return "args"
    # Any non-empty error-like text that doesn't fit the above patterns
    lower = text.lower()
    if "error" in lower or "exception" in lower or "failed" in lower or "traceback" in lower:
        return "error"
    return "pass"


_DEPLOY_PORT_BASE = 18100
#: The non-root user every built server runs as (no passwd entry needed).
_SANDBOX_UID = 10001
#: The squid user of the egress image (alpine's squid package).
_SQUID_UID = 31
#: The vault name of a server's endpoint token. The "__" prefix is reserved:
#: never a user's key, never handed to the server.
INBOUND_TOKEN_KEY = "__INBOUND_TOKEN"

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


def _read_config(path: Path | None) -> dict:
    """The extensions config as raw JSON (every field kept), or {} if absent."""
    if path is None or not Path(path).exists():
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


class McpTeardownError(RuntimeError):
    """Stopping or deleting a server left something behind; the caller must not report success."""


class McpContainerRemovalError(McpTeardownError):
    """The server's container could not be stopped and removed."""


class McpDeployInProgressError(RuntimeError):
    """A deploy is running; stopping now would race the container it starts."""


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

    def __init__(
        self,
        repo: McpServerRepository,
        vault: McpSecretsVault,
        runner: DockerRunner | None = None,
        images: RuntimeImages | None = None,
        reconcile_on_start: bool = True,
    ) -> None:
        self._reconcile_on_start = reconcile_on_start
        self.reconcile_messages: list[str] = []
        self._repo = repo
        self._vault = vault
        self._runner: DockerRunner = runner or CliDockerRunner()
        if images is None:
            from omniharness.config.paths import get_paths

            images = RuntimeImages(self._runner, state_dir=get_paths().base_dir / "mcp_runtime")
        self._images = images
        #: Approval-screen views, so "the code was viewed" is observed (#59).
        self.view_tokens = ViewTokens()
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
        # The sidecar's DNS: Docker's embedded resolver, rebinding protection on.
        # Tests point the upstream at a fake resolver; nothing else sets these.
        self._egress_upstream_dns = UPSTREAM_DNS
        self._egress_stop_dns_rebind = True
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
        if self._reconcile_on_start:
            # #59 plan §9: in the background (Docker calls are slow), reported
            # through the audit table and on the Build board, never silent.
            self._reconcile_task = asyncio.create_task(self.reconcile(), name="mcp-reconcile")

    async def reconcile(self) -> list[str]:
        """The one-time retirement, then turn off built servers whose running
        code is not the approved version (app.gateway.mcp_reconcile)."""
        from app.gateway.mcp_reconcile import Reconciler
        from omniharness.config.extensions_config import ExtensionsConfig

        rec = Reconciler(session_factory=self._repo._sf, runner=self._runner, prefix=self._images.prefix, config_path=ExtensionsConfig.resolve_config_path(), manager=self)
        try:
            messages = await rec.retire() + await rec.reconcile()
        except Exception:
            logger.exception("the startup reconcile of built MCP servers failed")
            return []
        for m in messages:
            logger.warning("MCP builder: %s", m)
        self.reconcile_messages = messages
        return messages

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

        tools_discovered: list[dict] = []
        test_results: list[dict] = []

        image_id = await self._images.code_image_id(source_code, code_sha256(source_code) or "")

        # ── Phase 1: Discovery — no keys at all, validates clean startup ──
        try:
            async with asyncio.timeout(30):
                async with self._sandbox(server_id, image_id, StdioServerParameters, stdio_client, files={}) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        tools_resp = await session.list_tools()
                        for t in tools_resp.tools:
                            tools_discovered.append({"name": t.name, "description": (t.description or "")[:300]})
        except TimeoutError:
            raise RuntimeError("MCP server discovery timed out (30s)")
        # Other startup/connection exceptions propagate to caller

        if not tools_discovered:
            return [], []

        # ── Phase 2: Test-calls — PLACEHOLDER keys (Feature 006) ─────
        # The sandbox is away from your data: tests never get the real
        # credentials. Each key the code reads is set to its placeholder, so
        # a tool that needs it answers with an auth error ("auth" badge,
        # still callable) instead of making a real call; there is no network
        # either ("offline" badge). Tools that require arguments get
        # validation errors with empty {} ("args" badge).
        names = set(self._vault.scan_for_required_keys(source_code))
        try:
            names |= {k["key_name"] for k in await self._vault.list_key_info(server_id=server_id, owner_id=user_id)}
        except Exception:
            pass  # names only; the code's own reads are already covered
        # Reserved names (HOME, PATH, proxy settings...) are not keys to hand over.
        placeholders = {name: placeholder(name) for name in names if secret_name_problem(name) is None}
        files = {"secrets": render_secrets(placeholders)} if placeholders else {}

        try:
            async with asyncio.timeout(30):
                async with self._sandbox(server_id, image_id, StdioServerParameters, stdio_client, files=files) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        for t in tools_discovered:
                            try:
                                result = await asyncio.wait_for(session.call_tool(t["name"], {}), timeout=10)
                                output = ""
                                if result.content:
                                    item = result.content[0]
                                    output = str(getattr(item, "text", None) or item)[:200]
                                # Classify result even on the success path — the tool may have
                                # returned an error payload (auth failure, missing args) rather
                                # than raising a Python exception.
                                output_type = _classify_output(output)
                                entry: dict = {"tool": t["name"], "ok": True, "output_type": output_type}
                                if output:
                                    entry["output"] = output
                                test_results.append(entry)
                            except Exception as exc:
                                exc_msg = str(exc)[:200]
                                output_type = _classify_output(exc_msg)
                                callable_anyway = output_type in ("auth", "offline")
                                entry = {"tool": t["name"], "ok": callable_anyway, "output_type": output_type}
                                entry["output" if callable_anyway else "error"] = exc_msg
                                test_results.append(entry)
        except Exception as exc:
            # Test-call phase failure never blocks 'verified' — tools were already discovered.
            logger.warning("MCP test-call phase failed for %s: %s", server_id, exc)

        return tools_discovered, test_results

    def _sandbox_args(self, name: str, server_id: str, image_id: str) -> list[str]:
        """``docker run`` for the sandbox test (#59): the exact flags."""
        return [
            "run", "--rm", "-i",
            "--name", name,
            "--label", f"omni.mcp.server={server_id}",
            "--label", "omni.mcp.role=test",
            *[a for k, v in self._images.labels for a in ("--label", f"{k}={v}")],
            "--network", "none",
            "--read-only",
            "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=16m",
            "--tmpfs", f"/run/omni:rw,noexec,nosuid,nodev,size=64k,mode=0700,uid={_SANDBOX_UID},gid={_SANDBOX_UID}",
            "--user", f"{_SANDBOX_UID}:{_SANDBOX_UID}",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--memory", "256m", "--memory-swap", "256m",
            "--pids-limit", "64",
            "--cpus", "0.5",
            "--ulimit", "nofile=256:256",
            "--stop-timeout", "2",
            "-e", "HOME=/tmp", "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "MCP_TRANSPORT=stdio",
            image_id,
            "python", "-I", "-B", "/opt/omni/launch.py",
        ]  # fmt: skip

    def _sandbox(self, server_id: str, image_id: str, params_cls, client, *, files: dict[str, bytes]):
        """An MCP stdio session with the code running in its sandbox container.
        The files (placeholders only) are handed over once the container is up."""
        manager = self
        name = f"{self._images.prefix}test-{server_id[:12]}-{secrets.token_hex(3)}"
        # The environment here is the docker CLI's (it needs HOME for its
        # context, and any DOCKER_* settings), never the container's: the
        # container gets only the -e flags in _sandbox_args.
        from mcp.client.stdio import get_default_environment

        cli_env = {**get_default_environment(), **{k: v for k, v in os.environ.items() if k.startswith("DOCKER_")}}
        params = params_cls(command="docker", args=self._sandbox_args(name, server_id, image_id), env=cli_env)

        class _Session:
            async def __aenter__(self):
                self._cm = client(params)
                streams = await self._cm.__aenter__()
                await manager._wait_running(name)
                await deliver(manager._runner, name, str(_SANDBOX_UID), files)
                return streams

            async def __aexit__(self, *exc):
                try:
                    return await self._cm.__aexit__(*exc)
                finally:
                    await manager._runner.run(["docker", "rm", "-f", name], timeout=15.0)

        return _Session()

    async def _wait_running(self, name: str, timeout: float = 20.0) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            rc, out, _ = await self._runner.run(["docker", "container", "inspect", "-f", "{{.State.Running}}", name], timeout=10.0)
            if rc == 0 and out.strip() == "true":
                return
            if asyncio.get_running_loop().time() > deadline:
                raise RuntimeError("the sandbox container did not start")
            await asyncio.sleep(0.1)

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
        problem = await self.name_problem(server, [t for t in tools if t])
        if problem:
            raise PermissionError(f"name collision: {problem}")
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

    async def name_problem(self, server: dict, tools: list[str]) -> str | None:
        """Why this server's name or tool names can't be registered, or None (#59).

        Its slug must not equal any configured MCP server (canonically, with or
        without ``built__``) or another built server; its prefixed tool names
        must not equal or read as another server's.
        """
        from omniharness.config.extensions_config import ExtensionsConfig

        server_id = server["id"]
        slug = slugify(server["name"])
        key = wire_key(slug)
        path = ExtensionsConfig.resolve_config_path()
        raw = _read_config(path) if path is not None else {}
        configured = raw.get("mcpServers") or {}
        others = {k: v for k, v in configured.items() if not (k == key and isinstance(v, dict) and v.get("server_id") == server_id)}
        if key in others:
            return f"{key!r} is already configured for another server"
        built_rows = [r for r in await self._repo.list_servers(user_id=None, limit=500) if r["id"] != server_id]
        clash = name_collision(slug, others.keys(), [slugify(r["name"]) for r in built_rows])
        if clash:
            return f"{('built/' + slug)!r} collides with {clash!r}"
        other_tools = [f"{wire_key(slugify(r['name']))}_{t.get('name')}" for r in built_rows for t in (r.get("tools_discovered") or []) if t.get("name")]
        return tool_name_collision(key, tools, others.keys(), other_tools)

    async def stop(self, *, server_id: str, user_id: str) -> MCPBuildRecord:
        """Stop a server: remove its containers (server and egress sidecar) and
        networks, and drop its agent config entry.

        Before, this only changed the status, and the container kept running
        (``--restart unless-stopped``) with the owner's secrets in its env.
        Raises ``McpContainerRemovalError`` when something could not be
        removed; the status is then left as it was, so nothing claims success.
        """
        server = await self._load_and_verify(server_id, user_id)
        async with self._lock:
            existing = self._records.get(server_id)
        if existing is not None and existing.phase == "deploying":
            raise McpDeployInProgressError("A deploy is in progress. Wait for it to finish, then stop the server.")
        await self._remove_topology(server_id, strict=True, recorded=bool(server.get("container_id")))
        self._drop_config_entries(server_id)
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
                    s.bind(("127.0.0.1", port))
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

        try:
            # ── Step 1: Preparing ──────────────────────────────────────────
            if code_sha256(source) != expected_sha256:
                await self._refuse_changed(server_id, user_id, "preparing")
                return
            await self._advance_step(server_id, "preparing", "building", detail="Code matches the approved hash")

            # ── Step 2: Building ───────────────────────────────────────────
            # The image for exactly this code (its label is the hash), and the
            # Squid sidecar image. Containers run image IDs, never tags.
            image_id = await self._images.code_image_id(source, expected_sha256)
            egress_id = await self._images.egress_image_id()
            await self._advance_step(server_id, "building", "launching", detail="Image built for the approved code")

            # ── Step 3: Launching ──────────────────────────────────────────
            async with self._source_lock(server_id):
                # The final check: the code stored now is the code this
                # approval is for. A change made while the image built is
                # caught here, before anything runs with real secrets.
                row = await self._repo.get(server_id, user_id=user_id)
                if row is None or code_sha256(row.get("source_code")) != expected_sha256:
                    await self._refuse_changed(server_id, user_id, "launching")
                    return
                real = await self._secrets_for_deploy(row, user_id, expected_sha256)
                host_port = await self._start_topology(server_id, row, image_id, egress_id, real)
            del real
            await self._advance_step(server_id, "launching", "registering", detail="Running behind its egress allowlist")

            # A pending approval becomes the approval only now that it runs.
            row = await self._repo.get(server_id, user_id=user_id)
            if row is not None and (row.get("pending_approval") or {}).get("code_sha256") == expected_sha256:
                if not await self._repo.commit_approval(server_id, expected_sha256=expected_sha256, user_id=user_id):
                    await self._remove_topology(server_id)
                    await self._fail_deploy(server_id, user_id, "registering", "the code changed while turning on; review it again")
                    return

            # ── Step 4: Registering ────────────────────────────────────────
            container_id = self._names(server_id)["server"]
            await self._repo.update_container_info(server_id, container_id=container_id, container_port=host_port, status="deployed", user_id=user_id)
            async with self._lock:
                rec = self._records.get(server_id)
                if rec is not None:
                    final_steps = [{**s, "status": "done"} if s["key"] == "registering" else s for s in rec.deploy_steps]
                    self._records[server_id] = dataclasses.replace(rec, phase="deployed", container_id=container_id, container_port=host_port, deploy_steps=final_steps)
            logger.info("MCP server %s deployed behind its egress allowlist", server_id[:12])
            if connect_after:
                # "Approve and turn on": the agents get its tools now.
                await self.connect(server_id=server_id, user_id=user_id)

        except Exception as exc:
            logger.error("Docker deploy failed for %s: %s", server_id[:12], exc)
            try:
                await self._remove_topology(server_id)
            except Exception:
                logger.exception("cleanup after a failed deploy of %s", server_id[:12])
            await self._fail_deploy(server_id, user_id, "launching", f"deploy error: {str(exc)[:400]}")

    # ------------------------------------------------------------------
    # The deployed topology (#59): an --internal network per server, the
    # server on it alone at .3, and a Squid sidecar at .2 that is its only way
    # out (allowlist, private-destination refusal, SNI check, proxy login) and
    # the only way in (the endpoint token). Secrets reach both as 0400 files.
    # ------------------------------------------------------------------

    def _names(self, server_id: str) -> dict[str, str]:
        p, i = self._images.prefix, server_id[:12]
        return {"server": f"{p}{i}", "egress": f"{p}egress-{i}", "net": f"{p}net-{i}", "pub": f"{p}pub-{i}"}

    async def _secrets_for_deploy(self, row: dict, user_id: str, sha: str) -> dict[str, str]:
        """The real secrets, only for the approved code (#59, Q3): the hash
        must be the approved version's, or the pending approval's for the
        code stored now. New, unapproved code never gets them."""
        approved = row.get("approved_code_sha256") == sha and (row.get("approval") or {}).get("code_sha256") == sha
        pending = (row.get("pending_approval") or {}).get("code_sha256") == sha and code_sha256(row.get("source_code")) == sha
        if not (approved or pending):
            raise PermissionError("real secrets are only for approved code")
        values = await self._vault._decrypt_for_sandbox(server_id=row["id"], owner_id=user_id)
        return {k: v for k, v in values.items() if not k.startswith("__")}

    async def _gateway_network(self) -> str | None:
        """The network the gateway's own container is on (Docker mode), or
        None for a gateway on the bare host."""
        override = os.environ.get("OMNI_HARNESS_MCP_GATEWAY_NETWORK")
        if override:
            return override
        if not Path("/.dockerenv").exists():
            return None
        rc, out, _ = await self._runner.run(["docker", "inspect", "-f", "{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}", socket.gethostname()], timeout=15.0)
        nets = out.split() if rc == 0 else []
        return nets[0] if nets else None

    async def _free_subnet(self) -> ipaddress.IPv4Network:
        rc, out, _ = await self._runner.run(["docker", "network", "inspect", "--format", "{{range .IPAM.Config}}{{.Subnet}} {{end}}", *await self._network_ids()], timeout=30.0)
        used = []
        for cidr in out.split() if rc == 0 else []:
            try:
                used.append(ipaddress.ip_network(cidr, strict=False))
            except ValueError:
                continue
        for candidate in ipaddress.ip_network("172.30.0.0/16").subnets(new_prefix=28):
            if not any(candidate.overlaps(u) for u in used):
                return candidate
        raise RuntimeError("no free /28 left in 172.30.0.0/16 for a built server's network")

    async def _network_ids(self) -> list[str]:
        rc, out, _ = await self._runner.run(["docker", "network", "ls", "-q"], timeout=15.0)
        return out.split() if rc == 0 else []

    async def _subnet_of(self, network: str) -> str:
        rc, out, err = await self._runner.run(["docker", "network", "inspect", "--format", "{{range .IPAM.Config}}{{.Subnet}} {{end}}", network], timeout=15.0)
        for cidr in out.split() if rc == 0 else []:
            if ":" not in cidr:
                return cidr
        raise RuntimeError(f"can't read the subnet of {network}: {err.strip()[:200]}")

    async def _docker(self, args: list[str], what: str, timeout: float = 60.0) -> str:
        rc, out, err = await self._runner.run(["docker", *args], timeout=timeout)
        if rc != 0:
            raise RuntimeError(f"{what} failed: {err.strip()[:300]}")
        return out

    def _labels(self, server_id: str, role: str) -> list[str]:
        out = ["--label", f"omni.mcp.server={server_id}", "--label", f"omni.mcp.role={role}"]
        for k, v in self._images.labels:
            out += ["--label", f"{k}={v}"]
        return out

    async def _start_topology(self, server_id: str, row: dict, image_id: str, egress_id: str, real: dict[str, str]) -> int:
        """Start the server and its sidecar; returns the published 127.0.0.1
        port (bare-host gateway) or 0 (gateway on the same Docker network)."""
        n = self._names(server_id)
        await self._remove_topology(server_id)
        subnet = await self._free_subnet()
        hosts = list(subnet.hosts())
        sidecar_ip, server_ip = str(hosts[1]), str(hosts[2])  # .2 and .3
        rules = build_egress_rules(list(row.get("egress_hosts") or []))
        allow = allowlist_hosts(sorted({a["host"] for a in rules["allow"]}))
        token = secrets.token_hex(24)
        password = secrets.token_hex(16)
        await self._vault.store(server_id=server_id, owner_id=row["owner_id"], key_name=INBOUND_TOKEN_KEY, plaintext_value=token)

        await self._docker(["network", "create", "--internal", "--subnet", str(subnet), *self._labels(server_id, "net"), n["net"]], "creating the internal network")
        outer = await self._gateway_network()
        port = 0
        if outer is None:
            await self._docker(["network", "create", *self._labels(server_id, "pub"), n["pub"]], "creating the endpoint network")
            outer = n["pub"]
            port = self._find_free_port()

        # 1. The server: internal network only, no port, no mounts, no secrets in its config.
        await self._docker(
            [
                "run", "-d", "--name", n["server"], *self._labels(server_id, "server"),
                "--label", f"omni.code_sha256={code_sha256(row.get('source_code'))}",
                "--network", n["net"], "--ip", server_ip, "--dns", "127.0.0.1",
                "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=16m",
                "--tmpfs", f"/run/omni:rw,noexec,nosuid,nodev,size=64k,mode=0700,uid={_SANDBOX_UID},gid={_SANDBOX_UID}",
                "--user", f"{_SANDBOX_UID}:{_SANDBOX_UID}", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--memory", "256m", "--memory-swap", "256m", "--pids-limit", "64", "--cpus", "0.5", "--ulimit", "nofile=512:512",
                "--restart", "unless-stopped",
                "-e", "HOME=/tmp", "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "MCP_TRANSPORT=sse", "-e", "MCP_PORT=8080",
                image_id, "python", "-I", "-B", "/opt/omni/launch.py",
            ],
            "starting the server",
        )  # fmt: skip

        # 2. The sidecar: created on the outer network, connected to the internal one at .2, then started.
        create = [
            "create", "--name", n["egress"], *self._labels(server_id, "egress"),
            "--network", outer,
            "--read-only", "--tmpfs", f"/tmp:rw,nosuid,nodev,size=16m,uid={_SQUID_UID},gid={_SQUID_UID}",
            "--tmpfs", f"/run/omni:rw,noexec,nosuid,nodev,size=64k,mode=0700,uid={_SQUID_UID},gid={_SQUID_UID}",
            "--user", f"{_SQUID_UID}:{_SQUID_UID}", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--sysctl", "net.ipv4.ip_unprivileged_port_start=53",
            "--memory", "128m", "--memory-swap", "128m", "--pids-limit", "64", "--cpus", "0.5", "--ulimit", "nofile=4096:4096",
            "--restart", "unless-stopped",
            "-e", f"OUTER_SUBNET={await self._subnet_of(outer)}",
        ]  # fmt: skip
        if port:
            create += ["-p", f"127.0.0.1:{port}:8080"]
        await self._docker([*create, egress_id], "creating the egress sidecar")
        await self._docker(["network", "connect", "--ip", sidecar_ip, n["net"], n["egress"]], "connecting the sidecar")
        await self._docker(["start", n["egress"]], "starting the sidecar")

        # 3. Files, values on stdin only: the sidecar's configs, then the server's keys.
        squid = render_squid(hosts=allow, internal_ip=sidecar_ip, upstream_ip=server_ip, token=token)
        dnsmasq = render_dnsmasq(upstream=self._egress_upstream_dns, stop_dns_rebind=self._egress_stop_dns_rebind)
        await deliver(self._runner, n["egress"], str(_SQUID_UID), {"squid.conf": squid.encode(), "dnsmasq.conf": dnsmasq.encode(), "passwd": proxy_password_line("mcp", password)})
        proxy = f"http://mcp:{password}@{sidecar_ip}:3128"
        await deliver(self._runner, n["server"], str(_SANDBOX_UID), {"secrets": render_secrets(real, gateway={"HTTPS_PROXY": proxy, "HTTP_PROXY": proxy})})
        await self._wait_endpoint(server_id, port, token)
        return port

    def endpoint_url(self, server_id: str, port: int) -> str:
        """Where the gateway reaches a deployed server: the sidecar's endpoint."""
        if port:
            return f"http://127.0.0.1:{port}/sse"
        return f"http://{self._names(server_id)['egress']}:8080/sse"

    async def _wait_endpoint(self, server_id: str, port: int, token: str, timeout: float = 45.0) -> None:
        import httpx

        url = self.endpoint_url(server_id, port)
        deadline = asyncio.get_running_loop().time() + timeout
        last = "no answer"
        while asyncio.get_running_loop().time() < deadline:
            try:
                async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
                    async with client.stream("GET", url, headers={"Authorization": f"Bearer {token}"}) as resp:
                        if resp.status_code == 200:
                            return
                        last = f"HTTP {resp.status_code}"
            except Exception as exc:
                last = type(exc).__name__
            await asyncio.sleep(0.5)
        raise RuntimeError(f"the server did not answer through its sidecar ({last})")

    async def _remove_topology(self, server_id: str, *, strict: bool = False, recorded: bool = False) -> None:
        """Remove the server, its sidecar and both networks. Something already
        gone counts as removed. With *strict*, any other failure raises
        ``McpContainerRemovalError`` in docker's own words."""
        n = self._names(server_id)
        steps = [(["docker", "rm", "-f", c], c) for c in (n["server"], n["egress"])]
        steps += [(["docker", "network", "rm", net], net) for net in (n["net"], n["pub"])]
        for args, what in steps:
            try:
                rc, _, err = await self._runner.run(args, timeout=60.0)
            except FileNotFoundError:
                # No docker CLI here. If a container was recorded, it may still be
                # running somewhere we cannot reach: say so.
                if strict and recorded:
                    raise McpContainerRemovalError(f"docker is not available, so {what} could not be removed")
                return
            except TimeoutError:
                if strict:
                    raise McpContainerRemovalError(f"removing {what} timed out")
                continue
            gone = "no such" in err.lower() or "not found" in err.lower()
            if strict and rc != 0 and not gone:
                raise McpContainerRemovalError(f"removing {what} failed: {err.strip()[:300]}")

    async def inbound_token(self, server_id: str) -> str | None:
        """The endpoint token for a built server, for the MCP loader only."""
        row = await self._repo.get(server_id, user_id=None)
        if row is None:
            return None
        try:
            values = await self._vault._decrypt_for_sandbox(server_id=server_id, owner_id=row["owner_id"])
        except Exception:
            return None
        return values.get(INBOUND_TOKEN_KEY)

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

    async def disconnect(self, *, server_id: str, user_id: str) -> bool:
        """Remove this server's entry from extensions_config.json (only one it owns)."""
        await self._load_and_verify(server_id, user_id)
        return self._drop_config_entries(server_id)

    def _drop_config_entries(self, server_id: str) -> bool:
        """Drop the entries carrying this server's id; every other key is kept
        as written. Raises ``McpTeardownError`` if the file can't be edited."""
        from omniharness.config.extensions_config import ExtensionsConfig, atomic_write_json, reload_extensions_config

        try:
            path = ExtensionsConfig.resolve_config_path()
            if path is None or not Path(path).exists():
                return False
            raw = _read_config(path)
            servers = raw.get("mcpServers") or {}
            mine = [k for k, v in servers.items() if isinstance(v, dict) and v.get("server_id") == server_id]
            if not mine:
                return False
            for k in mine:
                servers.pop(k)
            atomic_write_json(path, raw)
            reload_extensions_config()
        except (OSError, ValueError) as exc:
            raise McpTeardownError(f"could not remove the extensions_config.json entry: {exc}") from exc
        logger.info("MCP server %s: removed its extensions_config entry", server_id[:12])
        return True

    async def connect(self, *, server_id: str, user_id: str) -> dict[str, str]:
        """Register the deployed container's SSE URL into extensions_config.json.

        Reads the container port from the in-memory record (or DB), constructs
        the SSE URL, and upserts the server entry in extensions_config.json.
        The config file's mtime change triggers automatic hot-reload in the agent.

        Returns {"sse_url": ..., "server_name": ...}.
        """
        from omniharness.config.extensions_config import ExtensionsConfig, atomic_write_json, reload_extensions_config

        db_server = await self._load_and_verify(server_id, user_id)
        if not db_server.get("approved"):
            raise PermissionError(f"MCP server {server_id!r} has not been approved")
        async with self._lock:
            record = self._records.get(server_id)

        container_port = record.container_port if record and record.container_port is not None else db_server.get("container_port")
        if container_port is None or not db_server.get("container_id"):
            raise ValueError("Server is not deployed — run deploy first")

        # #59: the server is reached only through its sidecar's endpoint, which
        # needs the per-server token (added by the MCP loader, never written
        # here): 127.0.0.1:<port> for a bare-host gateway, or the sidecar's
        # name on the gateway's own Docker network (no published port).
        internal_url = self.endpoint_url(server_id, int(container_port))
        display_url = internal_url
        slug = slugify(db_server["name"])
        server_name = wire_key(slug)
        approval = db_server.get("approval") or {}
        tools = sorted((approval.get("tool_tiers") or {}).keys()) or [t.get("name") for t in db_server.get("tools_discovered") or [] if t.get("name")]
        problem = await self.name_problem(db_server, tools)
        if problem:
            raise PermissionError(f"name collision: {problem}")

        config_path = ExtensionsConfig.resolve_config_path()
        if config_path is None:
            config_path = Path.cwd().parent / "extensions_config.json"
        raw = _read_config(config_path)
        servers = raw.setdefault("mcpServers", {})
        # #59: the reserved built/ namespace; this server's entry carries its
        # id and the approval it runs under (hash + the tiers the user set).
        # The file is changed in place, so every other entry is kept as is.
        servers[server_name] = {
            "enabled": True,
            "type": "sse",
            "url": internal_url,  # gateway-accessible URL
            "description": db_server.get("description") or f"MCP server: {db_server['name']}",
            "server_id": server_id,
            # The endpoint token is added at load time from the vault, never stored here.
            "auth": "built-server-token",
            "built": {
                "display_name": f"built/{slug}",
                "code_sha256": approval.get("code_sha256"),
                "tool_tiers": dict(approval.get("tool_tiers") or {}),
            },
        }
        raw.setdefault("skills", {})
        atomic_write_json(config_path, raw)

        reload_extensions_config()
        logger.info("MCP server %r connected at %s (extensions_config updated)", server_name, internal_url)
        return {"sse_url": display_url, "server_name": server_name}
