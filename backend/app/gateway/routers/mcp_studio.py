"""MCP Studio router — read-only listing of user-owned MCP servers (Phase 1)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from app.gateway.authz import require_permission
from app.gateway.deps import get_config, get_mcp_server_repo

router = APIRouter(prefix="/api/mcp-studio", tags=["mcp-studio"])


def _check_flag(request: Request) -> None:
    """Return 503 when mcp_builder feature flag is disabled."""
    config = get_config(request)
    if not getattr(getattr(config, "mcp_builder", None), "enabled", False):
        raise HTTPException(status_code=503, detail="MCP builder is not enabled")


class McpServerResponse(BaseModel):
    id: str
    name: str
    language: str | None
    description: str | None
    status: str
    detected_secrets: list[str]
    created_at: str
    updated_at: str


class McpServerListResponse(BaseModel):
    servers: list[McpServerResponse]
    total: int


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
    servers = await repo.list_servers(search=search, status=status, limit=limit, offset=offset)
    return McpServerListResponse(
        servers=[McpServerResponse(**s) for s in servers],
        total=len(servers),
    )


@router.get("/servers/{server_id}", response_model=McpServerResponse)
@require_permission("threads", "read")
async def get_mcp_server(server_id: str, request: Request) -> McpServerResponse:
    _check_flag(request)
    repo = get_mcp_server_repo(request)
    server = await repo.get(server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return McpServerResponse(**server)
