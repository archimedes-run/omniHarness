"""Every integration and tool an agent could be given, with its real tier (006-G).

What Agent Studio's Configuration -> Integrations lists. Built from the SAME
functions a run's tools are assembled with, so the catalog never offers a tool
a run would not get, and never hides one it would:

  built in      ``get_available_tools(include_mcp=False)``: config.yaml tools
                and the in-process built-ins, grouped by
                ``agent_access.integration_of`` (core tools are not listed:
                every agent keeps them);
  MCP servers   the MCP cache the agent reads, attributed by server name, with
                built-in collisions refused, every configured server listed
                with its state (live, unreachable, disabled);
  apps          each Composio toolkit: its tools for THIS user, loaded through
                ``assemble_connector_tools`` (the run's own path: per-user
                connection, configured surface applied), when connected.

EACH TOOL'S TIER COMES FROM THE POLICY CLASSIFIER (``app.policy.explain``, the
function dispatch uses, runtime floors included), never from this module:
1 = Reads freely, 2 = Does then tells you, 3 = Asks first, None = no rule
names it (refused at dispatch: never offered, never run).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

#: MCP servers the product ships an entry for (extensions_config.example.json).
#: Every other configured server is the user's own ("custom").
SHIPPED_MCP_SERVERS = frozenset({"filesystem", "github", "postgres", "gmail", "googlecalendar", "session-watcher"})

#: Built-in integrations, by id: their name and what they are for.
BUILTIN_NAMES: dict[str, tuple[str, str]] = {
    "builtin:web": ("Web", "Search the web and open pages"),
    "builtin:file:read": ("Read files", "Read files in the sandbox workspace"),
    "builtin:file:write": ("Write files", "Create and edit files in the sandbox workspace"),
    "builtin:bash": ("Shell", "Run commands in the sandbox"),
    "builtin:ledger": ("Tasks and notes", "Your projects, tasks and decisions"),
    "builtin:workspace": ("Workspace", "Previews, MCP building and skill editing"),
}

#: The tools people reach for first in each app, most common first (the
#: collapsed row shows these; "Show all N" shows the rest). Named by the
#: toolkit's own action slug.
COMMON_CONNECTOR_TOOLS: dict[str, tuple[str, ...]] = {
    "GMAIL": ("FETCH_EMAILS", "FETCH_MESSAGE_BY_THREAD_ID", "LIST_THREADS", "CREATE_EMAIL_DRAFT", "ADD_LABEL_TO_EMAIL", "SEND_EMAIL"),
    "GOOGLECALENDAR": ("FIND_EVENT", "FIND_FREE_SLOTS", "LIST_CALENDARS", "CREATE_EVENT", "UPDATE_EVENT", "QUICK_ADD"),
    "GOOGLEDRIVE": ("FIND_FILE", "DOWNLOAD_FILE", "PARSE_FILE", "CREATE_FILE_FROM_TEXT", "CREATE_FOLDER", "UPLOAD_FILE"),
    "GITHUB": ("LIST_REPOSITORY_ISSUES", "GET_AN_ISSUE", "LIST_PULL_REQUESTS", "GET_A_PULL_REQUEST", "CREATE_AN_ISSUE", "CREATE_AN_ISSUE_COMMENT"),
    "SLACK": ("FETCH_CONVERSATION_HISTORY", "SEARCH_FOR_MESSAGES_WITH_QUERY", "LIST_ALL_SLACK_TEAM_CHANNELS_WITH_PAGINATION", "SENDS_A_MESSAGE_TO_A_SLACK_CHANNEL"),
    "NOTION": ("SEARCH_NOTION_PAGE", "FETCH_DATA", "CREATE_NOTION_PAGE", "ADD_PAGE_CONTENT"),
    "LINEAR": ("LIST_LINEAR_ISSUES", "LIST_LINEAR_PROJECTS", "CREATE_LINEAR_ISSUE", "UPDATE_ISSUE"),
    "OUTLOOK": ("OUTLOOK_LIST_MESSAGES", "OUTLOOK_SEARCH_MESSAGES", "OUTLOOK_CREATE_DRAFT", "OUTLOOK_SEND_EMAIL"),
}
#: How many tools a collapsed row shows when an app names none of the above.
COLLAPSED = 6

Kind = Literal["app", "mcp", "custom", "builtin"]
Status = Literal["connected", "not_connected", "unreachable", "disabled", "not_loaded"]


class CatalogTool(BaseModel):
    name: str = Field(..., description="The name the tool is offered as: what an allowlist stores")
    short: str = Field(..., description="The name without its source prefix, for display")
    label: str
    description: str = ""
    tier: int | None = Field(..., description="1 reads freely, 2 does then tells you, 3 asks first, None: no rule names it (never offered)")
    common: bool = Field(False, description="Shown when the row is collapsed")


class CatalogIntegration(BaseModel):
    id: str
    name: str
    kind: Kind
    status: Status
    detail: str = ""
    tools: list[CatalogTool] = Field(default_factory=list)


class ToolCatalog(BaseModel):
    integrations: list[CatalogIntegration]
    rules_error: str | None = None
    #: Composio is optional; without it no app can be connected here.
    connectors_available: bool = True


def _sentence(text: str, limit: int = 160) -> str:
    text = " ".join((text or "").split())
    end = text.find(". ")
    if 0 < end < limit:
        text = text[: end + 1]
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _label(short: str) -> str:
    words = short.replace("-", " ").replace("_", " ").strip().lower()
    return (words[:1].upper() + words[1:]) or short


def _tier(name: str, ruleset: Any) -> int | None:
    from app.policy.explain import explain

    if ruleset is None:
        return 3  # unreadable rules: everything asks (FR-009)
    decision = explain(name, {}, ruleset)
    return None if decision.refused else int(decision.tier)


def _tool(tool: Any, short: str, ruleset: Any, common: bool = False) -> CatalogTool:
    return CatalogTool(name=tool.name, short=short, label=_label(short), description=_sentence(getattr(tool, "description", "") or ""), tier=_tier(tool.name, ruleset), common=common)


def _rules(config: Any) -> tuple[Any, str | None]:
    try:
        from app.policy.registration import shared_loader

        loader = shared_loader(config.policy)
        return loader.load(notify=False), loader.last_error
    except Exception as exc:  # noqa: BLE001 — said, and everything reads as asking first
        logger.warning("tool catalog: policy rules unreadable: %s", exc)
        return None, f"{type(exc).__name__}: {exc}"


def _builtins(config: Any, ruleset: Any) -> list[CatalogIntegration]:
    from omniharness.tools.agent_access import integration_of
    from omniharness.tools.tools import get_available_tools

    tools = get_available_tools(include_mcp=False, app_config=config)
    groups = {cfg.name: cfg.group for cfg in config.tools if getattr(cfg, "group", None)}
    by_integration: dict[str, list[Any]] = {}
    for tool in tools:
        try:
            integration = integration_of(tool, config_groups=groups)
        except LookupError:
            continue
        if integration is None or not integration.startswith("builtin:"):
            continue
        by_integration.setdefault(integration, []).append(tool)
    order = [g.name for g in config.tool_groups]
    out = []
    for integration, members in sorted(by_integration.items(), key=lambda kv: (order.index(kv[0][8:]) if kv[0][8:] in order else len(order), kv[0])):
        name, detail = BUILTIN_NAMES.get(integration, (_label(integration[8:]), ""))
        out.append(CatalogIntegration(id=integration, name=name, kind="builtin", status="connected", detail=detail, tools=[_tool(t, t.name, ruleset, common=True) for t in members]))
    return out


async def _mcp(config: Any, ruleset: Any) -> list[CatalogIntegration]:
    from omniharness.config.extensions_config import get_extensions_config
    from omniharness.mcp import cache, load_report
    from omniharness.tools.tools import _tool_source, refuse_builtin_collisions

    servers = {name: entry for name, entry in get_extensions_config().mcp_servers.items() if not name.lower().startswith(("connector-", "composio-"))}
    if not servers:
        return []
    if not cache._cache_initialized:
        await cache.initialize_mcp_tools()
    names = list(servers.keys())
    tools = refuse_builtin_collisions(cache.get_cached_mcp_tools() or [], "MCP", config)
    by_server: dict[str, list[Any]] = {}
    for tool in tools:
        server = _tool_source(tool.name, names)
        if server:
            by_server.setdefault(server, []).append(tool)
    loads = load_report.last_loads()
    out = []
    for name in sorted(names):
        entry = servers[name]
        load = loads.get(name)
        if not entry.enabled:
            status, detail = "disabled", "Switched off in Settings"
        elif load is not None and not load.loaded:
            status, detail = "unreachable", "Not answering right now"
        elif name in by_server:
            status, detail = "connected", entry.description or ""
        else:
            status, detail = "not_loaded", entry.description or ""
        members = by_server.get(name, [])
        prefix = f"{name}_"
        out.append(
            CatalogIntegration(
                id=f"local:{name}",
                name=name,
                kind="mcp" if name in SHIPPED_MCP_SERVERS else "custom",
                status=status,
                detail=detail,
                tools=[_tool(t, t.name[len(prefix) :] if t.name.startswith(prefix) else t.name, ruleset, common=True) for t in members],
            )
        )
    return out


#: (user, toolkit) -> (at, tools): connector tool lists are slow to load (a
#: process per toolkit); the catalog keeps each for a few minutes.
_CONNECTOR_CACHE: dict[tuple[str, str], tuple[float, list[CatalogTool]]] = {}
_CONNECTOR_TTL = 300.0


def _connector_tools(config: Any, user_id: str, slug: str, ruleset: Any) -> list[CatalogTool]:
    from omniharness.tools.tools import assemble_connector_tools

    key = (user_id, slug)
    hit = _CONNECTOR_CACHE.get(key)
    if hit and time.monotonic() - hit[0] < _CONNECTOR_TTL:
        return hit[1]
    prefix = f"connector-{slug.lower()}_"
    common = COMMON_CONNECTOR_TOOLS.get(slug, ())
    rows = []
    for tool in assemble_connector_tools(config, user_id, [slug]):
        short = tool.name[len(prefix) :] if tool.name.startswith(prefix) else tool.name
        action = short[len(slug) + 1 :] if short.upper().startswith(f"{slug}_") else short
        rows.append((common.index(action) if action in common else len(common), action, _tool(tool, short, ruleset, common=action in common), tool))
    rows.sort(key=lambda r: (r[0], r[1]))
    out = [r[2] for r in rows]
    if out and not any(t.common for t in out):
        for t in out[:COLLAPSED]:
            t.common = True
    for t in out:
        t.label = _label(t.short[len(slug) + 1 :] if t.short.upper().startswith(f"{slug}_") else t.short)
    _CONNECTOR_CACHE[key] = (time.monotonic(), out)
    return out


async def _apps(request: Any, config: Any, user_id: str | None, ruleset: Any) -> tuple[list[CatalogIntegration], bool]:
    import asyncio

    from omniharness.tools.connector_tools import CONNECTOR_TOOLKITS

    available = getattr(request.app.state, "composio_client", None) is not None
    active: set[str] = set()
    repo = getattr(request.app.state, "composio_connection_repo", None)
    if repo is not None and user_id:
        try:
            for row in await repo.list_by_user(user_id=user_id):
                if row.get("status") == "active":
                    active.add(str(row.get("toolkit", "")).upper())
        except Exception:  # noqa: BLE001 — shown as not connected, never as connected
            logger.warning("tool catalog: connections unreadable", exc_info=True)
    out = []
    for toolkit in CONNECTOR_TOOLKITS:
        slug = toolkit["slug"]
        item = CatalogIntegration(id=f"connector:{slug}", name=toolkit["name"], kind="app", status="not_connected", detail=toolkit.get("category", ""))
        if slug in active and user_id:
            item.status = "connected"
            try:
                item.tools = await asyncio.to_thread(_connector_tools, config, user_id, slug, ruleset)
            except Exception as exc:  # noqa: BLE001 — a toolkit that cannot list is said
                logger.warning("tool catalog: %s tools unreadable: %s", slug, exc)
                item.status, item.detail = "unreachable", "Could not list its tools right now"
        out.append(item)
    return out, available


async def build_tool_catalog(request: Any, config: Any, user_id: str | None) -> ToolCatalog:
    ruleset, rules_error = _rules(config)
    apps, available = await _apps(request, config, user_id, ruleset)
    mcp = await _mcp(config, ruleset)
    builtins = _builtins(config, ruleset)
    return ToolCatalog(integrations=[*apps, *mcp, *builtins], rules_error=rules_error, connectors_available=available)


async def integration_choices(request: Any, config: Any, user_id: str | None) -> list[tuple[str, str]]:
    """(id, name) of the integrations an agent could be given now, cheaply (no
    tool lists, no connector process): what a one-sentence draft picks from."""
    from omniharness.config.extensions_config import get_extensions_config
    from omniharness.tools.connector_tools import CONNECTOR_TOOLKITS

    out: list[tuple[str, str]] = []
    repo = getattr(request.app.state, "composio_connection_repo", None)
    active: set[str] = set()
    if repo is not None and user_id:
        try:
            active = {str(r.get("toolkit", "")).upper() for r in await repo.list_by_user(user_id=user_id) if r.get("status") == "active"}
        except Exception:  # noqa: BLE001 — a draft without apps, not a failed draft
            active = set()
    out += [(f"connector:{t['slug']}", t["name"]) for t in CONNECTOR_TOOLKITS if t["slug"] in active]
    out += [(f"local:{name}", name) for name, entry in get_extensions_config().mcp_servers.items() if entry.enabled and not name.lower().startswith(("connector-", "composio-"))]
    groups = [g.name for g in config.tool_groups]
    out += [(f"builtin:{g}", BUILTIN_NAMES.get(f"builtin:{g}", (_label(g), ""))[0]) for g in groups]
    out.append(("builtin:ledger", BUILTIN_NAMES["builtin:ledger"][0]))
    return out
