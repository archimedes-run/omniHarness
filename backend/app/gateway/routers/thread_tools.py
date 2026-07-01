"""Per-conversation tool selection + catalog API.

Endpoints:
- GET  /api/tools/catalog                    — everything the user could enable
- GET  /api/threads/{thread_id}/tools        — this thread's selection + count/cap
- PUT  /api/threads/{thread_id}/tools        — set this thread's selection
- GET  /api/threads/{thread_id}/tools/count  — live N/cap for the current selection

Sources are namespaced ids: ``local:<server>`` and ``connector:<SLUG>``. Pinned
defaults (local:filesystem, local:postgres) are enforced server-side and never
trusted from the client.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission
from app.gateway.deps import get_composio_connection_repo, get_thread_tool_selection_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["thread-tools"])


def _get_user_id(request: Request) -> str:
    auth = getattr(request.state, "auth", None)
    if auth and auth.user:
        return str(auth.user.id)
    raise HTTPException(status_code=401, detail="Authentication required")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class CatalogItem(BaseModel):
    tool_id: str = Field(..., description="Namespaced source id: local:<server> or connector:<SLUG>")
    name: str
    description: str = ""
    source: str = Field(..., description="local | connector")
    origin: str = Field(default="builtin", description="For local sources: 'builtin' or 'user' (agent-built)")
    toolkit: str | None = None
    icon: str | None = None
    category: str
    connected: bool = True
    pinned: bool = False


class CatalogResponse(BaseModel):
    items: list[CatalogItem]
    categories: list[str]


class SelectionResponse(BaseModel):
    thread_id: str
    sources: list[str]
    pinned: list[str]


class SelectionUpdateRequest(BaseModel):
    sources: list[str] = Field(default_factory=list)


class CountResponse(BaseModel):
    count: int
    cap: int
    over_cap: bool


# ---------------------------------------------------------------------------
# GET /tools/catalog
# ---------------------------------------------------------------------------


@router.get("/tools/catalog", response_model=CatalogResponse)
@require_permission("threads", "read")
async def get_tools_catalog(request: Request) -> CatalogResponse:
    from omniharness.config.extensions_config import ExtensionsConfig
    from omniharness.tools.connector_tools import CONNECTOR_TOOLKITS
    from omniharness.tools.tools import PINNED_LOCAL_SERVERS

    user_id = _get_user_id(request)
    items: list[CatalogItem] = []

    # Slugified names of the user's agent-built ("Create MCP") servers — these
    # register into extensions_config under a slugified name (see
    # MCPServerManager._register), so we match on the same slug to mark origin.
    import re

    user_server_slugs: set[str] = set()
    try:
        mcp_repo = getattr(request.app.state, "mcp_server_repo", None)
        if mcp_repo is not None:
            for row in await mcp_repo.list_servers(user_id=user_id):
                slug = re.sub(r"[^a-z0-9\-]", "-", (row.get("name") or "").lower()).strip("-")
                if slug:
                    user_server_slugs.add(slug)
    except Exception:
        user_server_slugs = set()

    # Local MCP servers from the config (pinned first, connectors excluded).
    try:
        ext = ExtensionsConfig.from_file()
        enabled = ext.get_enabled_mcp_servers()
    except Exception:
        enabled = {}
    for name, cfg in enabled.items():
        if name.lower().startswith(("connector-", "composio-")):
            continue  # connectors are surfaced from the live catalog below
        items.append(
            CatalogItem(
                tool_id=f"local:{name}",
                name=name,
                description=getattr(cfg, "description", "") or "",
                source="local",
                origin="user" if name in user_server_slugs else "builtin",
                category="Local",
                connected=True,
                pinned=name in PINNED_LOCAL_SERVERS,
            )
        )

    # Connector toolkits — connected flag from the user's ACTIVE connections.
    connected_slugs: set[str] = set()
    try:
        repo = get_composio_connection_repo(request)
        for row in await repo.list_by_user(user_id=user_id):
            if row.get("status") == "active":
                connected_slugs.add(str(row.get("toolkit", "")).upper())
    except Exception:
        connected_slugs = set()

    for tk in CONNECTOR_TOOLKITS:
        items.append(
            CatalogItem(
                tool_id=f"connector:{tk['slug']}",
                name=tk["name"],
                description="",
                source="connector",
                toolkit=tk["slug"],
                icon=tk.get("icon"),
                category=tk["category"],
                connected=tk["slug"] in connected_slugs,
                pinned=False,
            )
        )

    categories: list[str] = []
    for it in items:
        if it.category not in categories:
            categories.append(it.category)
    return CatalogResponse(items=items, categories=categories)


# ---------------------------------------------------------------------------
# GET/PUT /threads/{thread_id}/tools
# ---------------------------------------------------------------------------


@router.get("/threads/{thread_id}/tools", response_model=SelectionResponse)
@require_permission("threads", "read")
async def get_thread_tools(thread_id: str, request: Request) -> SelectionResponse:
    from omniharness.persistence.thread_tool_selection.sql import PINNED_SOURCES

    _get_user_id(request)
    repo = get_thread_tool_selection_repo(request)
    sources = await repo.get_sources(thread_id=thread_id)
    return SelectionResponse(thread_id=thread_id, sources=sources, pinned=list(PINNED_SOURCES))


@router.put("/threads/{thread_id}/tools", response_model=SelectionResponse)
@require_permission("threads", "write")
async def put_thread_tools(thread_id: str, body: SelectionUpdateRequest, request: Request) -> SelectionResponse:
    from omniharness.persistence.thread_tool_selection.sql import PINNED_SOURCES

    user_id = _get_user_id(request)
    repo = get_thread_tool_selection_repo(request)
    # Pinned defaults are enforced inside the repo regardless of client input.
    saved = await repo.set_sources(thread_id=thread_id, user_id=user_id, sources=body.sources)
    return SelectionResponse(thread_id=thread_id, sources=saved, pinned=list(PINNED_SOURCES))


# ---------------------------------------------------------------------------
# GET /threads/{thread_id}/tools/count  (A4 contract for the picker)
# ---------------------------------------------------------------------------


@router.get("/threads/{thread_id}/tools/count", response_model=CountResponse)
@require_permission("threads", "read")
async def get_thread_tools_count(thread_id: str, request: Request) -> CountResponse:
    from omniharness.config import get_app_config
    from omniharness.tools.tools import ToolCapExceededError, get_available_tools, resolve_model_tool_cap

    user_id = _get_user_id(request)
    repo = get_thread_tool_selection_repo(request)
    sources = set(await repo.get_sources(thread_id=thread_id))

    app_config = get_app_config()
    model_config = app_config.models[0] if app_config.models else None
    cap = resolve_model_tool_cap(model_config)

    # Assemble WITHOUT enforcing the cap so we can report the real count even
    # when it is over — the UI shows "N / cap" and blocks enabling more.
    try:
        tools = get_available_tools(selected_sources=sources, user_id=user_id, app_config=app_config)
        count = len(tools)
    except ToolCapExceededError as exc:  # pragma: no cover - max_tools not passed here
        count = exc.count
    return CountResponse(count=count, cap=cap, over_cap=count > cap)
