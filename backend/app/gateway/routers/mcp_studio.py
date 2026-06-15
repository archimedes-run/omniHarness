"""MCP Studio router — full Phase 3a API contract.

Endpoints
---------
GET  /api/mcp-studio/servers                        list user-owned servers
POST /api/mcp-studio/servers                        create server + kick off agent run
GET  /api/mcp-studio/servers/{id}                   server detail (includes phase, approved)
GET  /api/mcp-studio/servers/{id}/build             build status snapshot
PUT  /api/mcp-studio/servers/{id}/secrets           write secrets (write-only)
POST /api/mcp-studio/servers/{id}/test              trigger test pipeline
POST /api/mcp-studio/servers/{id}/approve           mark server approved
POST /api/mcp-studio/servers/{id}/register          register approved server for agent use
POST /api/mcp-studio/servers/{id}/stop              stop running server

Security invariants
-------------------
* All secrets endpoints accept but never return secret values.
* owner_id passed to the vault / manager is always the verified requesting user,
  never server.owner_id read back from the row.
* test / approve / register / stop each call _load_and_verify as their first action.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission
from app.gateway.deps import (
    get_config,
    get_mcp_secrets_vault,
    get_mcp_server_manager,
    get_mcp_server_repo,
    get_run_context,
    get_run_manager,
    get_stream_bridge,
)
from app.gateway.services import (
    build_run_config,
    normalize_input,
    normalize_stream_modes,
    resolve_agent_factory,
)
from omniharness.runtime import run_agent

router = APIRouter(prefix="/api/mcp-studio", tags=["mcp-studio"])

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
    created_at: str
    updated_at: str


class McpServerListResponse(BaseModel):
    servers: list[McpServerResponse]
    total: int


class McpServerCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=1024)
    template_type: str | None = Field(default=None, description="api_wrapper | database_connector | custom_tool")
    language: str | None = Field(default="python")
    egress_hosts: list[str] = Field(default_factory=list)


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
        created_at=server["created_at"],
        updated_at=server["updated_at"],
    )


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
    manager = getattr(request.app.state, "mcp_server_manager", None)
    servers = await repo.list_servers(search=search, status=status, limit=limit, offset=offset)
    items = []
    for s in servers:
        phase = "idle"
        if manager is not None:
            record = manager._records.get(s["id"])
            if record is not None:
                phase = record.phase
        items.append(_server_to_response(s, phase))
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

    server = await repo.create(
        name=body.name,
        owner_id=user_id,
        language=body.language or "python",
        description=body.description,
        egress_hosts=body.egress_hosts,
    )
    server_id = server["id"]
    thread_id = uuid.uuid4().hex

    # Build the initial message that kicks off the mcp-server-builder skill
    template_hint = body.template_type or "custom_tool"
    prompt_parts = [
        "Use the mcp-server-builder skill to build an MCP server.",
        f"Server ID: {server_id}",
        f"Name: {body.name}",
    ]
    if body.description:
        prompt_parts.append(f"Description: {body.description}")
    prompt_parts.append(f"Template type: {template_hint}")
    if body.egress_hosts:
        prompt_parts.append(f"Allowed egress hosts: {', '.join(body.egress_hosts)}")
    prompt_parts.append("\nWrite the complete server.py source code, then call mcp_build with the server_id and source_code.")
    initial_message = "\n".join(prompt_parts)

    graph_input = normalize_input({"messages": [{"role": "user", "content": initial_message}]})
    config = build_run_config(
        thread_id,
        None,
        {"mcp_server_id": server_id, "mcp_server_name": body.name},
    )
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

    return McpServerCreateResponse(server_id=server_id, thread_id=thread_id)


# ---------------------------------------------------------------------------
# GET /servers/{id}
# ---------------------------------------------------------------------------


@router.get("/servers/{server_id}", response_model=McpServerResponse)
@require_permission("threads", "read")
async def get_mcp_server(server_id: str, request: Request) -> McpServerResponse:
    _check_flag(request)
    repo = get_mcp_server_repo(request)
    server = await repo.get(server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    manager = getattr(request.app.state, "mcp_server_manager", None)
    phase = "idle"
    if manager is not None:
        r = manager._records.get(server_id)
        if r is not None:
            phase = r.phase
    return _server_to_response(server, phase)


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
    server = await repo.get(server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="MCP server not found")

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
    server = await repo.get(server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="MCP server not found")

    vault = get_mcp_secrets_vault(request)
    items = await vault.list_key_info(server_id=server_id, owner_id=user_id)
    return McpSecretsInfoResponse(keys=[McpSecretsInfoItem(**item) for item in items])


# ---------------------------------------------------------------------------
# GET /servers/{id}/secrets/reveal
# ---------------------------------------------------------------------------


@router.get("/servers/{server_id}/secrets/reveal", response_model=McpSecretsRevealResponse)
@require_permission("threads", "write")
async def reveal_mcp_secrets(server_id: str, request: Request) -> McpSecretsRevealResponse:
    """Decrypt and return all secrets for the authenticated owner.

    Requires write permission (same level as storing secrets). The caller is the
    human owner who stored the values; this endpoint lets them verify what is
    stored. Returned values MUST NOT be forwarded to agent or model context.
    """
    _check_flag(request)
    user_id = _get_user_id(request)

    repo = get_mcp_server_repo(request)
    server = await repo.get(server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="MCP server not found")

    vault = get_mcp_secrets_vault(request)
    values = await vault.reveal(server_id=server_id, owner_id=user_id)
    return McpSecretsRevealResponse(values=values)


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
# POST /servers/{id}/approve
# ---------------------------------------------------------------------------


@router.post("/servers/{server_id}/approve", response_model=McpServerResponse)
@require_permission("threads", "write")
async def approve_mcp_server(server_id: str, request: Request) -> McpServerResponse:
    _check_flag(request)
    user_id = _get_user_id(request)
    manager = get_mcp_server_manager(request)

    try:
        await manager.approve(server_id=server_id, user_id=user_id)
    except PermissionError:
        raise HTTPException(status_code=404, detail="MCP server not found")

    repo = get_mcp_server_repo(request)
    server = await repo.get(server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return _server_to_response(server, "idle")


# ---------------------------------------------------------------------------
# POST /servers/{id}/register
# ---------------------------------------------------------------------------


@router.post("/servers/{server_id}/register", response_model=McpServerResponse)
@require_permission("threads", "write")
async def register_mcp_server(server_id: str, request: Request) -> McpServerResponse:
    _check_flag(request)
    user_id = _get_user_id(request)
    manager = get_mcp_server_manager(request)

    try:
        record = await manager.register(server_id=server_id, user_id=user_id)
    except PermissionError as exc:
        raise HTTPException(status_code=404 if "not found" in str(exc) else 403, detail=str(exc)) from exc

    repo = get_mcp_server_repo(request)
    server = await repo.get(server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return _server_to_response(server, record.phase)


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

    repo = get_mcp_server_repo(request)
    server = await repo.get(server_id)
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
        raise HTTPException(status_code=404, detail=str(exc)) from exc
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
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return McpConnectResponse(**result)


# ---------------------------------------------------------------------------
# DELETE /servers/{id}
# ---------------------------------------------------------------------------


@router.delete("/servers/{server_id}", status_code=204)
@require_permission("threads", "write")
async def delete_mcp_server(server_id: str, request: Request) -> None:
    _check_flag(request)
    user_id = _get_user_id(request)
    repo = get_mcp_server_repo(request)

    # Best-effort: stop the server if it is running.
    manager = getattr(request.app.state, "mcp_server_manager", None)
    if manager is not None:
        try:
            await manager.stop(server_id=server_id, user_id=user_id)
        except Exception:
            pass
        # Remove the in-memory record regardless of stop outcome.
        manager._records.pop(server_id, None)

    deleted = await repo.delete(server_id, user_id=user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="MCP server not found")
