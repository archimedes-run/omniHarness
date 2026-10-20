"""MCP Studio router — full Phase 3a API contract.

Endpoints
---------
GET  /api/mcp-studio/servers                        list user-owned servers
POST /api/mcp-studio/servers                        create server + kick off agent run
GET  /api/mcp-studio/servers/{id}                   server detail (includes phase, approved)
GET  /api/mcp-studio/servers/{id}/build             build status snapshot
PUT  /api/mcp-studio/servers/{id}/secrets           write secrets (write-only)
POST /api/mcp-studio/servers/{id}/secrets/reveal    one stored value, owner only, password re-entered
POST /api/mcp-studio/servers/{id}/test              trigger test pipeline
POST /api/mcp-studio/servers/{id}/enable            approve the code you saw (by hash) and turn it on
POST /api/mcp-studio/servers/{id}/stop              stop and remove the server's container
DELETE /api/mcp-studio/servers/{id}                 remove container, config entry, secrets, record

Security invariants
-------------------
* Secrets endpoints never return secret values, except POST .../secrets/reveal:
  one key, to the server's owner, after the owner's password is re-entered.
  Every reveal call is logged with the key NAME and outcome, never the value.
* owner_id passed to the vault / manager is always the verified requesting user,
  never server.owner_id read back from the row.
* test / approve / register / stop each call _load_and_verify as their first action.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission
from app.gateway.deps import (
    get_config,
    get_local_provider,
    get_mcp_secrets_vault,
    get_mcp_server_manager,
    get_mcp_server_repo,
    get_run_context,
    get_run_manager,
    get_stream_bridge,
)
from app.gateway.mcp_build_flow import build_prompt, describe_build, extract_secrets, scrub, server_name_from
from app.gateway.mcp_names import slugify
from app.gateway.mcp_server_manager import McpDeployInProgressError, McpTeardownError
from app.gateway.services import (
    build_run_config,
    normalize_input,
    normalize_stream_modes,
    resolve_agent_factory,
)
from omniharness.runtime import run_agent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mcp-studio", tags=["mcp-studio"])
logger = logging.getLogger(__name__)

_THREAD_ID_META_KEY = "mcp_server_id"


def _check_flag(request: Request) -> None:
    config = get_config(request)
    if not getattr(getattr(config, "mcp_builder", None), "enabled", False):
        raise HTTPException(status_code=503, detail="MCP builder is not enabled")


def _get_user_id(request: Request) -> str:
    auth = getattr(request.state, "auth", None)
    if auth and auth.user:
        return str(auth.user.id)
    raise HTTPException(status_code=401, detail="Authentication required")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class BuildStep(BaseModel):
    status: str
    text: str


class McpServerResponse(BaseModel):
    id: str
    name: str
    language: str | None
    description: str | None
    status: str
    phase: str
    approved: bool
    detected_secrets: list[str]
    egress_hosts: list[str]
    source_code: str | None
    files: dict[str, str] | None
    # #59: the hash of the stored code, and the hash of the approved version
    # (None when nothing was ever approved). ``approved`` is derived: the two
    # are equal and the hosts are the approved hosts.
    code_sha256: str | None = None
    approved_code_sha256: str | None = None
    created_at: str
    updated_at: str
    # Feature 006 (MCP Suite > Build): where the build is, in words.
    state: str | None = None
    state_label: str | None = None
    state_reason: str | None = None
    steps: list[BuildStep] = Field(default_factory=list)
    tool_count: int | None = None
    tests_passed: int | None = None
    tests_total: int | None = None
    thread_id: str | None = None


class StartBuildRequest(BaseModel):
    description: str = Field(..., min_length=3, max_length=1024)


class StartBuildResponse(BaseModel):
    server_id: str
    thread_id: str
    name: str
    secret_placeholders: list[str]


class McpServerListResponse(BaseModel):
    servers: list[McpServerResponse]
    total: int


class McpServerCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=1024)
    template_type: str | None = Field(default=None, description="api_wrapper | database_connector | custom_tool")
    language: str | None = Field(default="python")


class McpServerCreateResponse(BaseModel):
    server_id: str
    thread_id: str


class McpBuildStatusResponse(BaseModel):
    server_id: str
    phase: str
    tools_discovered: list[dict[str, Any]]
    detected_secret_names: list[str]
    errors: list[str]
    test_results: list[dict[str, Any]]
    last_verified_at: str | None
    container_id: str | None = None
    container_port: int | None = None
    deploy_steps: list[dict[str, Any]] = []


class McpConnectResponse(BaseModel):
    sse_url: str
    server_name: str


class McpSecretsWriteRequest(BaseModel):
    secrets: dict[str, str] = Field(
        ...,
        description="Map of env-var name → plaintext value. Values are encrypted immediately and never returned.",
    )


class McpSecretsWriteResponse(BaseModel):
    stored: list[str]
    hints: dict[str, str | None] = Field(default_factory=dict, description="Map of key_name → last-5-char hint (None for short values)")


class McpSecretsInfoItem(BaseModel):
    key_name: str
    key_hint: str | None


class McpSecretsInfoResponse(BaseModel):
    keys: list[McpSecretsInfoItem]


class McpSecretsRevealRequest(BaseModel):
    key_name: str = Field(..., min_length=1, max_length=256)
    password: str = Field(..., min_length=1, max_length=1024, description="The caller's own account password, re-entered.")


class McpSecretsRevealResponse(BaseModel):
    values: dict[str, str]


# ---------------------------------------------------------------------------
# Helper: _server_to_response
# ---------------------------------------------------------------------------


def _server_to_response(server: dict, phase: str = "idle") -> McpServerResponse:
    source_code = server.get("source_code")
    files: dict[str, str] | None = None
    if source_code:
        files = server.get("files") or {"server.py": source_code}
    return McpServerResponse(
        id=server["id"],
        name=server["name"],
        language=server.get("language"),
        description=server.get("description"),
        status=server["status"],
        phase=phase,
        approved=bool(server.get("approved", False)),
        detected_secrets=server.get("detected_secrets") or [],
        egress_hosts=server.get("egress_hosts") or [],
        source_code=source_code,
        files=files,
        code_sha256=server.get("code_sha256"),
        approved_code_sha256=server.get("approved_code_sha256"),
        created_at=server["created_at"],
        updated_at=server["updated_at"],
    )


async def _described(request: Request, server: dict, user_id: str | None) -> McpServerResponse:
    """The server, with where its build is in words (Feature 006)."""
    manager = getattr(request.app.state, "mcp_server_manager", None)
    record = None
    if manager is not None and user_id is not None:
        try:
            record = await manager.get_status(server_id=server["id"], user_id=user_id)
        except PermissionError:
            record = None
    run = manager.build_run(server["id"]) if manager is not None else None
    stored: set[str] | None = None
    vault = getattr(request.app.state, "mcp_secrets_vault", None)
    if vault is not None and user_id is not None:
        try:
            stored = {k["key_name"] for k in await vault.list_key_info(server_id=server["id"], owner_id=user_id)}
        except Exception:
            stored = None
    run_status = getattr(getattr(run, "status", None), "value", None)
    secrets = await manager.stored_secrets(server_id=server["id"], user_id=user_id) if manager is not None and user_id is not None else {}
    desc = describe_build(
        server,
        phase=record.phase if record else None,
        error=scrub(record.error, secrets) if record and record.error else None,
        tools=record.tools_discovered if record else [],
        test_results=record.test_results if record else [],
        deploy_steps=record.deploy_steps if record else [],
        testing_now=manager.is_testing(server["id"]) if manager is not None else False,
        run_status=run_status,
        run_error=scrub(run.error, secrets) if run is not None and getattr(run, "error", None) else None,
        stored_secrets=stored,
    )
    response = _server_to_response(server, record.phase if record else "idle")
    return response.model_copy(
        update={
            "state": desc.state,
            "state_label": desc.label,
            "state_reason": desc.reason,
            "steps": [BuildStep(**step) for step in desc.steps],
            "tool_count": desc.tool_count,
            "tests_passed": desc.tests_passed,
            "tests_total": desc.tests_total,
            "thread_id": getattr(run, "thread_id", None),
        }
    )


async def _refuse_name_collision(request: Request, slug: str) -> None:
    """409 before anything is created when *slug* collides with a configured
    MCP server or another built server (#59: built servers live under built/)."""
    manager = getattr(request.app.state, "mcp_server_manager", None)
    if manager is None:
        return
    problem = await manager.name_problem({"id": "", "name": slug}, [])
    if problem:
        raise HTTPException(status_code=409, detail=f"Can't build it under that name: {problem}. Describe it differently, or remove the other server first.")


def _user_or_none(request: Request) -> str | None:
    auth = getattr(request.state, "auth", None)
    return str(auth.user.id) if auth and auth.user else None


async def _start_build_run(request: Request, *, server_id: str, name: str, message: str, user_id: str) -> str:
    """Start the build agent on *message* (already free of secret values)."""
    thread_id = uuid.uuid4().hex
    graph_input = normalize_input({"messages": [{"role": "user", "content": message}]})
    config = build_run_config(thread_id, None, {"mcp_server_id": server_id, "mcp_server_name": name})
    config.setdefault("context", {})["user_id"] = user_id

    bridge = get_stream_bridge(request)
    run_mgr = get_run_manager(request)
    run_ctx = get_run_context(request)

    from omniharness.runtime import ConflictError

    try:
        record = await run_mgr.create_or_reject(
            thread_id,
            None,
            metadata={"mcp_server_id": server_id},
            kwargs={"input": graph_input, "config": config},
            multitask_strategy="reject",
        )
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    try:
        existing = await run_ctx.thread_store.get(thread_id)
        if existing is None:
            await run_ctx.thread_store.create(thread_id, assistant_id=None, metadata={"mcp_server_id": server_id})
    except Exception:
        pass

    manager = getattr(request.app.state, "mcp_server_manager", None)
    if manager is not None:
        manager.note_build_run(server_id, record)

    agent_factory = resolve_agent_factory(None)
    task = asyncio.create_task(
        run_agent(
            bridge,
            run_mgr,
            record,
            ctx=run_ctx,
            agent_factory=agent_factory,
            graph_input=graph_input,
            config=config,
            stream_modes=normalize_stream_modes(None),
            stream_subgraphs=False,
            interrupt_before=None,
            interrupt_after=None,
        )
    )
    record.task = task
    return thread_id


# ---------------------------------------------------------------------------
# POST /builds — describe a tool in words (Feature 006, MCP Suite > Build)
# ---------------------------------------------------------------------------


@router.post("/builds", response_model=StartBuildResponse, status_code=201)
@require_permission("threads", "write")
async def start_build(body: StartBuildRequest, request: Request) -> StartBuildResponse:
    """Create a server from a description and start the build agent on it.

    Any secret in the description is lifted out first: stored in the vault
    under an environment-variable name, and replaced by a placeholder in the
    stored description and in the prompt. The model never sees the value.
    """
    _check_flag(request)
    user_id = _get_user_id(request)
    extracted = extract_secrets(body.description.strip())
    name = slugify(server_name_from(extracted.text))
    await _refuse_name_collision(request, name)
    repo = get_mcp_server_repo(request)
    server = await repo.create(name=name, owner_id=user_id, language="python", description=extracted.text, egress_hosts=[])
    server_id = server["id"]
    if extracted.secrets:
        vault = get_mcp_secrets_vault(request)
        for key_name, value in extracted.secrets.items():
            await vault.store(server_id=server_id, owner_id=user_id, key_name=key_name, plaintext_value=value)
    message = build_prompt(server_id=server_id, name=name, description=extracted.text, secret_names=list(extracted.secrets))
    secret_names = list(extracted.secrets)
    del extracted  # the values are in the vault now, and nowhere else
    thread_id = await _start_build_run(request, server_id=server_id, name=name, message=message, user_id=user_id)
    return StartBuildResponse(server_id=server_id, thread_id=thread_id, name=name, secret_placeholders=secret_names)


@router.get("/events")
@require_permission("threads", "read")
async def list_build_events(request: Request) -> dict:
    """What the startup reconcile and the one-time retirement did (#59):
    retired servers, deleted orphaned secrets (names only), servers turned
    off because their running code was not the approved version."""
    _check_flag(request)
    _get_user_id(request)
    from app.gateway.mcp_reconcile import recent_events

    repo = get_mcp_server_repo(request)
    return {"events": await recent_events(repo._sf)}


# ---------------------------------------------------------------------------
# POST /servers/{id}/enable — "Approve and turn on"
# ---------------------------------------------------------------------------


class ApprovalTool(BaseModel):
    name: str
    description: str
    #: Every built tool starts at Tier 3 ("asks every time") until the user sets it.
    proposed_tier: int = 3


class ApprovalPacket(BaseModel):
    """Everything the approval screen shows, and the token that proves it was shown."""

    server_id: str
    name: str
    code_sha256: str
    source_code: str
    egress_hosts: list[str]
    tools: list[ApprovalTool]
    secret_names: list[str]
    view_token: str
    expires_in_seconds: int
    approved_version_on: bool


@router.get("/servers/{server_id}/approval", response_model=ApprovalPacket)
@require_permission("threads", "write")
async def get_approval_packet(server_id: str, request: Request) -> ApprovalPacket:
    """The code (in full), its hash, the hosts it will be allowed to reach, its
    tools and the secret names it will get, plus a single-use view token.
    ``/enable`` needs that token: the code must have been shown first (#59)."""
    _check_flag(request)
    user_id = _get_user_id(request)
    manager = get_mcp_server_manager(request)
    server = await get_mcp_server_repo(request).get(server_id, user_id=user_id)
    if server is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    source = server.get("source_code")
    sha = server.get("code_sha256")
    if not source or not sha:
        raise HTTPException(status_code=409, detail="There is no code to review yet.")
    record = await manager.get_status(server_id=server_id, user_id=user_id)
    tools = server.get("tools_discovered") or record.tools_discovered or []
    token, ttl = manager.view_tokens.issue(server_id=server_id, user_id=user_id, code_sha256=sha)
    return ApprovalPacket(
        server_id=server_id,
        name=server["name"],
        code_sha256=sha,
        source_code=source,
        egress_hosts=list(server.get("egress_hosts") or []),
        tools=[ApprovalTool(name=t.get("name", "?"), description=(t.get("description") or "")[:300]) for t in tools],
        secret_names=list(server.get("detected_secrets") or []),
        view_token=token,
        expires_in_seconds=int(ttl),
        approved_version_on=bool(server.get("approved_code_sha256") and server.get("container_id") and not server.get("approved")),
    )


class EnableRequest(BaseModel):
    #: The hash of the code the user was shown. Approval is for that code only.
    code_sha256: str = Field(..., min_length=64, max_length=64)
    #: From GET /approval: proves this user was shown this code (single use).
    view_token: str = ""
    #: Tier per tool (1, 2 or 3). A tool not named here starts at Tier 3.
    tool_tiers: dict[str, int] = Field(default_factory=dict)


@router.post("/servers/{server_id}/enable", response_model=McpServerResponse)
@require_permission("threads", "write")
async def enable_mcp_server(server_id: str, body: EnableRequest, request: Request) -> McpServerResponse:
    """The user approves the code they saw, and the server is turned on.

    The approval names the code by its hash: it is refused unless the sandbox
    tests passed and the hash is the stored code's. It is recorded as pending
    and becomes the approval only when the deploy succeeds; a failed deploy
    leaves the server unapproved (#59). Nothing else turns a built server on.
    """
    _check_flag(request)
    user_id = _get_user_id(request)
    manager = get_mcp_server_manager(request)
    if await get_mcp_server_repo(request).get(server_id, user_id=user_id) is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    refused = manager.view_tokens.consume(body.view_token, server_id=server_id, user_id=user_id, code_sha256=body.code_sha256)
    if refused:
        raise HTTPException(status_code=409, detail=refused)
    try:
        await manager.begin_approval(server_id=server_id, user_id=user_id, code_sha256_seen=body.code_sha256, tool_tiers=body.tool_tiers)
    except PermissionError as exc:
        if "not found" in str(exc):
            raise HTTPException(status_code=404, detail="MCP server not found") from exc
        if "code changed" in str(exc):
            raise HTTPException(status_code=409, detail="The code changed since you opened it; review it again.") from exc
        if "name collision" in str(exc):
            raise HTTPException(status_code=409, detail=f"Can't turn it on under that name: {exc}") from exc
        raise HTTPException(status_code=409, detail="It can be approved only after its sandbox tests pass.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        await manager.deploy(server_id=server_id, user_id=user_id, connect_after=True)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail="The code changed since you opened it; review it again.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    server = await get_mcp_server_repo(request).get(server_id, user_id=user_id)
    if server is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return await _described(request, server, user_id)


# ---------------------------------------------------------------------------
# GET /servers
# ---------------------------------------------------------------------------


@router.get("/servers", response_model=McpServerListResponse)
@require_permission("threads", "read")
async def list_mcp_servers(
    request: Request,
    search: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> McpServerListResponse:
    _check_flag(request)
    repo = get_mcp_server_repo(request)
    user_id = _get_user_id(request)
    servers = await repo.list_servers(search=search, status=status, limit=limit, offset=offset, user_id=user_id)
    items = [await _described(request, s, user_id) for s in servers]
    return McpServerListResponse(servers=items, total=len(items))


# ---------------------------------------------------------------------------
# POST /servers — create record + kick off agent run
# ---------------------------------------------------------------------------


@router.post("/servers", response_model=McpServerCreateResponse, status_code=201)
@require_permission("threads", "write")
async def create_mcp_server(
    body: McpServerCreateRequest,
    request: Request,
) -> McpServerCreateResponse:
    _check_flag(request)
    user_id = _get_user_id(request)
    repo = get_mcp_server_repo(request)
    name = slugify(body.name)  # #59: [a-z0-9-] only, the same slug rule everywhere
    await _refuse_name_collision(request, name)

    extracted = extract_secrets(body.description) if body.description else None
    description = extracted.text if extracted else None
    # Outbound hosts are read from the code the agent writes, never taken
    # from the client (#59): they are part of what the user approves.
    server = await repo.create(
        name=name,
        owner_id=user_id,
        language=body.language or "python",
        description=description,
        egress_hosts=[],
    )
    server_id = server["id"]
    if extracted and extracted.secrets:
        vault = get_mcp_secrets_vault(request)
        for key_name, value in extracted.secrets.items():
            await vault.store(server_id=server_id, owner_id=user_id, key_name=key_name, plaintext_value=value)

    # Build the initial message that kicks off the mcp-server-builder skill
    template_hint = body.template_type or "custom_tool"
    prompt_parts = [
        "Use the mcp-server-builder skill to build an MCP server.",
        f"Server ID: {server_id}",
        f"Name: {name}",
    ]
    if description:
        prompt_parts.append(f"Description: {description}")
    prompt_parts.append(f"Template type: {template_hint}")
    if extracted and extracted.secrets:
        prompt_parts.append("Secrets are stored for this server and NOT shown to you; read " + ", ".join(f"os.environ['{n}']" for n in extracted.secrets) + " inside the tool handlers.")
    prompt_parts.append("\nWrite the complete server.py source code, then call mcp_build with the server_id and source_code.")
    initial_message = "\n".join(prompt_parts)
    del extracted

    thread_id = await _start_build_run(request, server_id=server_id, name=name, message=initial_message, user_id=user_id)

    return McpServerCreateResponse(server_id=server_id, thread_id=thread_id)


# ---------------------------------------------------------------------------
# GET /servers/{id}
# ---------------------------------------------------------------------------


@router.get("/servers/{server_id}", response_model=McpServerResponse)
@require_permission("threads", "read")
async def get_mcp_server(server_id: str, request: Request) -> McpServerResponse:
    _check_flag(request)
    repo = get_mcp_server_repo(request)
    server = await repo.get(server_id, user_id=_get_user_id(request))
    if server is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return await _described(request, server, _user_or_none(request))


# ---------------------------------------------------------------------------
# GET /servers/{id}/build
# ---------------------------------------------------------------------------


@router.get("/servers/{server_id}/build", response_model=McpBuildStatusResponse)
@require_permission("threads", "read")
async def get_mcp_build_status(server_id: str, request: Request) -> McpBuildStatusResponse:
    _check_flag(request)
    user_id = _get_user_id(request)
    manager = get_mcp_server_manager(request)

    try:
        record = await manager.get_status(server_id=server_id, user_id=user_id)
    except PermissionError:
        raise HTTPException(status_code=404, detail="MCP server not found")

    return McpBuildStatusResponse(
        server_id=record.server_id,
        phase=record.phase,
        tools_discovered=record.tools_discovered,
        detected_secret_names=record.required_key_names,
        errors=[record.error] if record.error else [],
        test_results=record.test_results,
        last_verified_at=record.last_verified_at,
        container_id=record.container_id,
        container_port=record.container_port,
        deploy_steps=record.deploy_steps,
    )


# ---------------------------------------------------------------------------
# PUT /servers/{id}/secrets
# ---------------------------------------------------------------------------


@router.put("/servers/{server_id}/secrets", response_model=McpSecretsWriteResponse)
@require_permission("threads", "write")
async def write_mcp_secrets(
    server_id: str,
    body: McpSecretsWriteRequest,
    request: Request,
) -> McpSecretsWriteResponse:
    """Write secrets for an MCP server. Values are encrypted immediately and never returned."""
    _check_flag(request)
    user_id = _get_user_id(request)

    # Verify ownership before touching the vault
    repo = get_mcp_server_repo(request)
    server = await repo.get(server_id, user_id=_get_user_id(request))
    if server is None:
        raise HTTPException(status_code=404, detail="MCP server not found")

    # #59: a stored key becomes a line of the server's secrets file. A name
    # that would change how the server or its proxy runs (HTTPS_PROXY, LD_*,
    # MCP_*...) or a value with a line break (a second, injected line) is
    # refused here, and again when it is handed over.
    from app.gateway.mcp_container_files import secret_name_problem, secret_value_problem

    for key_name, plaintext_value in body.secrets.items():
        problem = secret_name_problem(key_name) or secret_value_problem(key_name, plaintext_value)
        if problem:
            raise HTTPException(status_code=400, detail=problem)

    vault = get_mcp_secrets_vault(request)
    stored: list[str] = []
    hints: dict[str, str | None] = {}
    for key_name, plaintext_value in body.secrets.items():
        hint = await vault.store(
            server_id=server_id,
            owner_id=user_id,
            key_name=key_name,
            plaintext_value=plaintext_value,
        )
        stored.append(key_name)
        hints[key_name] = hint

    return McpSecretsWriteResponse(stored=stored, hints=hints)


# ---------------------------------------------------------------------------
# GET /servers/{id}/secrets/info
# ---------------------------------------------------------------------------


@router.get("/servers/{server_id}/secrets/info", response_model=McpSecretsInfoResponse)
@require_permission("threads", "read")
async def get_mcp_secrets_info(server_id: str, request: Request) -> McpSecretsInfoResponse:
    """Return key names and last-5-char hints for all stored secrets.

    Values (ciphertext or plaintext) are never included. Safe to call on page load
    to restore the stored-keys state across sessions.
    """
    _check_flag(request)
    user_id = _get_user_id(request)

    repo = get_mcp_server_repo(request)
    server = await repo.get(server_id, user_id=_get_user_id(request))
    if server is None:
        raise HTTPException(status_code=404, detail="MCP server not found")

    vault = get_mcp_secrets_vault(request)
    items = await vault.list_key_info(server_id=server_id, owner_id=user_id)
    return McpSecretsInfoResponse(keys=[McpSecretsInfoItem(**item) for item in items])


# ---------------------------------------------------------------------------
# POST /servers/{id}/secrets/reveal
# ---------------------------------------------------------------------------

# Wrong-password lockout for reveal, per user: a stolen session cookie must not
# become a password oracle. Same numbers as the login lockout. Per process.
_REVEAL_MAX_FAILURES = 5
_REVEAL_LOCKOUT_SECONDS = 300
_reveal_failures: dict[str, tuple[int, float]] = {}


def _reveal_locked(user_id: str) -> bool:
    count, lock_until = _reveal_failures.get(user_id, (0, 0.0))
    if count < _REVEAL_MAX_FAILURES:
        return False
    if time.time() < lock_until:
        return True
    _reveal_failures.pop(user_id, None)
    return False


def _record_reveal_failure(user_id: str) -> None:
    count = _reveal_failures.get(user_id, (0, 0.0))[0] + 1
    lock_until = time.time() + _REVEAL_LOCKOUT_SECONDS if count >= _REVEAL_MAX_FAILURES else 0.0
    _reveal_failures[user_id] = (count, lock_until)


def _audit_reveal(user_id: str, server_id: str, key_name: str, outcome: str) -> None:
    # The key NAME and the outcome only. The value never reaches a log.
    log = logger.info if outcome == "revealed" else logger.warning
    log("mcp secret reveal: user=%s server=%s key=%s outcome=%s", user_id, server_id, key_name, outcome)


@router.post("/servers/{server_id}/secrets/reveal", response_model=McpSecretsRevealResponse)
@require_permission("threads", "write")
async def reveal_mcp_secret(server_id: str, body: McpSecretsRevealRequest, request: Request) -> McpSecretsRevealResponse:
    """Decrypt one stored secret for the server's owner, after a password re-entry.

    * Owner only: another account gets 404, the same as a missing server, so
      the call does not confirm that the server exists.
    * The caller's password travels in the JSON body (never the URL) and is
      checked with the account's password hasher. Five wrong passwords lock
      reveal for that account for five minutes (429).
    * Accounts with no password (OAuth sign-in) cannot reveal; they can type
      a new value instead.
    * Every call is logged with user, server, key name and outcome.

    Returned values MUST NOT be forwarded to agent or model context.
    """
    _check_flag(request)
    user_id = _get_user_id(request)
    key_name = body.key_name

    if _reveal_locked(user_id):
        _audit_reveal(user_id, server_id, key_name, "locked_out")
        raise HTTPException(status_code=429, detail="Too many wrong passwords. Try again in a few minutes.")

    # Explicit owner scope: a server someone else owns reads as not found.
    server = await get_mcp_server_repo(request).get(server_id, user_id=user_id)
    if server is None:
        _audit_reveal(user_id, server_id, key_name, "not_found")
        raise HTTPException(status_code=404, detail="MCP server not found")

    from app.gateway.auth.password import verify_password_async

    user = await get_local_provider().get_user(user_id)
    if user is None or user.password_hash is None:
        _audit_reveal(user_id, server_id, key_name, "no_password")
        raise HTTPException(
            status_code=400,
            detail="This account signs in without a password, so stored values cannot be revealed. Type a new value to replace it.",
        )
    # 403, not 401: the session is valid, and the UI treats 401 as signed out.
    if not await verify_password_async(body.password, user.password_hash):
        _record_reveal_failure(user_id)
        _audit_reveal(user_id, server_id, key_name, "wrong_password")
        raise HTTPException(status_code=403, detail="Password is incorrect.")
    _reveal_failures.pop(user_id, None)

    value = await get_mcp_secrets_vault(request).reveal(server_id=server_id, owner_id=user_id, key_name=key_name)
    if value is None:
        _audit_reveal(user_id, server_id, key_name, "not_stored")
        raise HTTPException(status_code=404, detail=f"No stored value for {key_name}")
    _audit_reveal(user_id, server_id, key_name, "revealed")
    return McpSecretsRevealResponse(values={key_name: value})


# ---------------------------------------------------------------------------
# POST /servers/{id}/test
# ---------------------------------------------------------------------------


@router.post("/servers/{server_id}/test", response_model=McpBuildStatusResponse)
@require_permission("threads", "write")
async def trigger_mcp_test(server_id: str, request: Request) -> McpBuildStatusResponse:
    _check_flag(request)
    user_id = _get_user_id(request)
    manager = get_mcp_server_manager(request)

    try:
        record = await manager.test_server(server_id=server_id, user_id=user_id)
    except PermissionError:
        raise HTTPException(status_code=404, detail="MCP server not found")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return McpBuildStatusResponse(
        server_id=record.server_id,
        phase=record.phase,
        tools_discovered=record.tools_discovered,
        detected_secret_names=record.required_key_names,
        errors=[record.error] if record.error else [],
        test_results=record.test_results,
        last_verified_at=record.last_verified_at,
        container_id=record.container_id,
        container_port=record.container_port,
        deploy_steps=record.deploy_steps,
    )


# ---------------------------------------------------------------------------
# POST /servers/{id}/stop
# ---------------------------------------------------------------------------


@router.post("/servers/{server_id}/stop", response_model=McpServerResponse)
@require_permission("threads", "write")
async def stop_mcp_server(server_id: str, request: Request) -> McpServerResponse:
    _check_flag(request)
    user_id = _get_user_id(request)
    manager = get_mcp_server_manager(request)

    try:
        record = await manager.stop(server_id=server_id, user_id=user_id)
    except PermissionError:
        raise HTTPException(status_code=404, detail="MCP server not found")
    except McpDeployInProgressError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except McpTeardownError as exc:
        raise HTTPException(status_code=502, detail=f"The server was not stopped: {exc}") from exc

    repo = get_mcp_server_repo(request)
    server = await repo.get(server_id, user_id=_get_user_id(request))
    if server is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return _server_to_response(server, record.phase)


# ---------------------------------------------------------------------------
# POST /servers/{id}/deploy   — Docker build + run
# ---------------------------------------------------------------------------


@router.post("/servers/{server_id}/deploy", response_model=McpBuildStatusResponse)
@require_permission("threads", "write")
async def deploy_mcp_server(server_id: str, request: Request) -> McpBuildStatusResponse:
    """Build a Docker image and start the MCP server as a persistent container.

    Requires Docker to be installed and running on the host. Injects the stored
    secrets as container env vars (they are never logged). Returns the updated
    build status with container_id and container_port on success.
    """
    _check_flag(request)
    user_id = _get_user_id(request)
    manager = get_mcp_server_manager(request)

    try:
        record = await manager.deploy(server_id=server_id, user_id=user_id)
    except PermissionError as exc:
        # Not approved yet is a refusal (403), not an absence.
        raise HTTPException(status_code=403 if "approve" in str(exc) else 404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return McpBuildStatusResponse(
        server_id=record.server_id,
        phase=record.phase,
        tools_discovered=record.tools_discovered,
        detected_secret_names=record.required_key_names,
        errors=[record.error] if record.error else [],
        test_results=record.test_results,
        last_verified_at=record.last_verified_at,
        container_id=record.container_id,
        container_port=record.container_port,
        deploy_steps=record.deploy_steps,
    )


# ---------------------------------------------------------------------------
# POST /servers/{id}/undeploy  — Docker stop + rm
# ---------------------------------------------------------------------------


@router.post("/servers/{server_id}/undeploy", response_model=McpBuildStatusResponse)
@require_permission("threads", "write")
async def undeploy_mcp_server(server_id: str, request: Request) -> McpBuildStatusResponse:
    """Stop and remove the Docker container for this MCP server."""
    _check_flag(request)
    user_id = _get_user_id(request)
    manager = get_mcp_server_manager(request)

    try:
        record = await manager.undeploy(server_id=server_id, user_id=user_id)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except McpDeployInProgressError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except McpTeardownError as exc:
        raise HTTPException(status_code=502, detail=f"The server was not stopped: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return McpBuildStatusResponse(
        server_id=record.server_id,
        phase=record.phase,
        tools_discovered=record.tools_discovered,
        detected_secret_names=record.required_key_names,
        errors=[record.error] if record.error else [],
        test_results=record.test_results,
        last_verified_at=record.last_verified_at,
    )


# ---------------------------------------------------------------------------
# POST /servers/{id}/connect  — write SSE URL into extensions_config.json
# ---------------------------------------------------------------------------


@router.post("/servers/{server_id}/connect", response_model=McpConnectResponse)
@require_permission("threads", "write")
async def connect_mcp_server(server_id: str, request: Request) -> McpConnectResponse:
    """Register the deployed MCP server's SSE URL into extensions_config.json.

    The config file's mtime change triggers hot-reload in the agent runtime so
    the new server's tools become available immediately without a restart.
    """
    _check_flag(request)
    user_id = _get_user_id(request)
    manager = get_mcp_server_manager(request)

    try:
        result = await manager.connect(server_id=server_id, user_id=user_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403 if "approved" in str(exc) else 404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return McpConnectResponse(**result)


# ---------------------------------------------------------------------------
# DELETE /servers/{id}
# ---------------------------------------------------------------------------


@router.delete("/servers/{server_id}", status_code=204)
@require_permission("threads", "delete")
async def delete_mcp_server(server_id: str, request: Request) -> None:
    """Delete a server and everything it left running or stored.

    In order: stop and remove its container, drop its extensions_config entry
    (both via ``manager.stop``), delete its secrets, then its record. If the
    container or config entry cannot be removed, nothing is deleted and the
    call fails, so the server stays listed and the delete can be retried.
    """
    _check_flag(request)
    user_id = _get_user_id(request)
    repo = get_mcp_server_repo(request)
    manager = get_mcp_server_manager(request)

    try:
        await manager.stop(server_id=server_id, user_id=user_id)
    except PermissionError:
        raise HTTPException(status_code=404, detail="MCP server not found")
    except McpDeployInProgressError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except McpTeardownError as exc:
        raise HTTPException(status_code=502, detail=f"The server was not deleted: {exc}") from exc

    # Secrets before the record: if the record delete then fails, the server is
    # still listed (retryable) rather than gone with its secrets orphaned.
    await get_mcp_secrets_vault(request).delete_all_for_server(server_id=server_id, owner_id=user_id)
    deleted = await repo.delete(server_id, user_id=user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="MCP server not found")
    manager._records.pop(server_id, None)
