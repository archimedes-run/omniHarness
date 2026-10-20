"""POST /api/tool-sources/retry — load every MCP server again (Feature 006).

MCP Suite > Connected: a failing source has a Retry. It empties the MCP tool
cache and loads it again, now, then answers with the states that load produced:
a server still down comes back unreachable with its new error, never as fixed.

Apart from the read surface (`tool_sources.py`, which only reads): this writes
no store and no file, only the process's in-memory tool cache.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.gateway.authz import require_permission
from app.gateway.routers.tool_sources import describe_for_request
from app.gateway.tool_sources import ToolSourcesView

router = APIRouter(prefix="/api", tags=["tool-sources"])


@router.post("/tool-sources/retry", response_model=ToolSourcesView)
@require_permission("threads", "write")
async def retry_tool_sources(request: Request) -> ToolSourcesView:
    from omniharness.mcp import cache

    cache.reset_mcp_tools_cache()
    await cache.initialize_mcp_tools()
    return await describe_for_request(request, None)
