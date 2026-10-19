"""GET /api/tool-sources — every tool source's state (FR-040, FR-041, SC-024).

Thin: gathers configuration, the harness's load report and Composio state, and
hands them to `app.gateway.tool_sources.describe_tool_sources`. Read-only.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query, Request

from app.gateway.authz import get_auth_context, require_permission
from app.gateway.tool_sources import ToolSourcesView, describe_tool_sources

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["tool-sources"])


@router.get("/tool-sources", response_model=ToolSourcesView)
@require_permission("threads", "read")
async def tool_sources(request: Request, thread_id: str | None = Query(default=None)) -> ToolSourcesView:
    from omniharness.config.extensions_config import get_extensions_config
    from omniharness.mcp import cache, load_report
    from omniharness.tools.connector_tools import CONNECTOR_TOOLKITS

    # Load once if nothing has yet, so "never loaded" does not stand in for a
    # state. The same initialisation an agent's first turn performs.
    if not cache._cache_initialized:
        await cache.initialize_mcp_tools()

    authorised: set[str] | None = None
    if getattr(request.app.state, "composio_client", None) is not None:
        authorised = set()
        repo = getattr(request.app.state, "composio_connection_repo", None)
        auth = get_auth_context(request)
        if repo is not None and auth is not None and auth.user is not None:
            for row in await repo.list_by_user(user_id=str(auth.user.id)):
                if row.get("status") == "active":
                    authorised.add(str(row.get("toolkit", "")).upper())

    selected: set[str] | None = None
    if thread_id:
        selection = getattr(request.app.state, "thread_tool_selection_repo", None)
        selected = set(await selection.get_sources(thread_id=thread_id)) if selection is not None else set()

    return describe_tool_sources(
        servers=get_extensions_config().mcp_servers,
        last_loads=load_report.last_loads(),
        connector_toolkits=list(CONNECTOR_TOOLKITS),
        authorised=authorised,
        selected=selected,
        thread_id=thread_id,
    )
