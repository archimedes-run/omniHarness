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
    from omniharness.mcp import cache

    # Load once if nothing has yet, so "never loaded" does not stand in for a
    # state. The same initialisation an agent's first turn performs.
    if not cache._cache_initialized:
        await cache.initialize_mcp_tools()
    return await describe_for_request(request, thread_id)


async def describe_for_request(request: Request, thread_id: str | None) -> ToolSourcesView:
    """The view for this request's user, from the MCP load already made."""
    from omniharness.config.extensions_config import get_extensions_config
    from omniharness.mcp import load_report
    from omniharness.tools.connector_tools import CONNECTOR_TOOLKITS

    auth = get_auth_context(request)
    user_id = str(auth.user.id) if auth is not None and auth.user is not None else None

    authorised: set[str] | None = None
    if getattr(request.app.state, "composio_client", None) is not None:
        authorised = set()
        repo = getattr(request.app.state, "composio_connection_repo", None)
        if repo is not None and auth is not None and auth.user is not None:
            for row in await repo.list_by_user(user_id=str(auth.user.id)):
                if row.get("status") == "active":
                    authorised.add(str(row.get("toolkit", "")).upper())

    selected: set[str] | None = None
    if thread_id:
        selection = getattr(request.app.state, "thread_tool_selection_repo", None)
        selected = set(await selection.get_sources(thread_id=thread_id)) if selection is not None else set()

    # Feature 006: what the tool-call chokepoint observed. Unreadable is not
    # "never worked": it is left out, and each source reads as not yet seen.
    health = None
    health_repo = getattr(request.app.state, "tool_source_health_repo", None)
    if health_repo is not None:
        try:
            health = await health_repo.for_user(user_id=user_id)
        except Exception:
            logger.warning("tool-source health could not be read", exc_info=True)

    return describe_tool_sources(
        servers=get_extensions_config().mcp_servers,
        last_loads=load_report.last_loads(),
        connector_toolkits=list(CONNECTOR_TOOLKITS),
        authorised=authorised,
        selected=selected,
        thread_id=thread_id,
        health=health,
    )
