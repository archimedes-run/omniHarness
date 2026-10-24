"""Per-agent integrations and tools (006-G): THE filter.

An agent's config may carry an allowlist (``AgentConfig.tools``): the
integrations it may use and, within them, the individual tools. This module
decides, for one assembled tool, which integration it belongs to, and keeps a
tool only when the allowlist names both. It is applied where every run's tools
are assembled (``get_available_tools``), so the chat, an @-call, a delegation
and a scheduled run all go through it; the Studio UI is never the enforcement.

Integration ids (the same ids the tool catalog shows):

  ``local:<server>``      an MCP server from extensions_config.json, custom or
                          built in (filesystem, postgres, session-watcher, ...)
  ``connector:<TOOLKIT>`` a connected Composio toolkit (Gmail, GitHub, ...)
  ``builtin:<group>``     a config.yaml tool group (web, file:read, bash, ...)
  ``builtin:ledger``      Tasks and notes (the Project Ledger tools)
  ``builtin:workspace``   previews, MCP building and skill editing

The CORE tools are not assignable: every agent keeps them, because they are how
a run talks to the user (present_files, ask_clarification), hands work on
(task, call_agent: each still classified by the policy layer, task is Tier 3)
or sees what it was given (view_image, tool_search over its OWN tools,
write_todos). A tool that belongs to no known integration and is not core is
DROPPED: an allowlist fails closed.

Assigning a tool never changes its tier: the policy middleware classifies every
call by name, whoever assigned it.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from typing import Any

from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)

#: Always on for an agent with an allowlist; never listed in the catalog.
CORE_TOOLS: frozenset[str] = frozenset(
    {
        "present_files",
        "ask_clarification",
        "view_image",
        "task",
        "tool_search",
        "update_agent",
        "setup_agent",
        "call_agent",
        "write_todos",
    }
)

LEDGER_INTEGRATION = "builtin:ledger"
WORKSPACE_INTEGRATION = "builtin:workspace"
#: In-process built-ins that are assignable, by tool name.
BUILTIN_INTEGRATION_OF: Mapping[str, str] = {
    "ledger_read": LEDGER_INTEGRATION,
    "ledger_apply": LEDGER_INTEGRATION,
    "preview": WORKSPACE_INTEGRATION,
    "mcp_build": WORKSPACE_INTEGRATION,
    "skill_manage": WORKSPACE_INTEGRATION,
}


def access_of(raw: Any) -> tuple[frozenset[str], frozenset[str]] | None:
    """(integrations, tools) from an AgentToolAccess, its dict form, or None.

    None means "no allowlist": the agent keeps its pre-006-G tools. Anything
    present but unreadable is an EMPTY allowlist (fails closed)."""
    if raw is None:
        return None
    if hasattr(raw, "integrations") and hasattr(raw, "tools"):
        integrations, tools = raw.integrations, raw.tools
    elif isinstance(raw, Mapping):
        integrations, tools = raw.get("integrations"), raw.get("tools")
    else:
        return frozenset(), frozenset()
    return (
        frozenset(i for i in (integrations or []) if isinstance(i, str)),
        frozenset(t for t in (tools or []) if isinstance(t, str)),
    )


def access_dict(raw: Any) -> dict | None:
    """The allowlist as plain JSON (run metadata, a recorded tool surface)."""
    access = access_of(raw)
    if access is None:
        return None
    return {"integrations": sorted(access[0]), "tools": sorted(access[1])}


def config_tool_groups(config: Any) -> dict[str, str]:
    """config.yaml tool name -> its group, by the name the tool is offered as
    (the config's ``name``; a mismatching object name is warned about at load)."""
    groups: dict[str, str] = {}
    for cfg in getattr(config, "tools", None) or []:
        group = getattr(cfg, "group", None)
        if group:
            groups[cfg.name] = group
    return groups


def integration_of(tool: BaseTool, *, config_groups: Mapping[str, str]) -> str | None:
    """The integration `tool` belongs to; None for a core tool.

    Raises LookupError for a tool that is neither core nor attributable, so the
    caller drops it (an allowlist fails closed)."""
    from omniharness.tools.source_tags import source_of

    name = tool.name
    if name in CORE_TOOLS:
        return None
    tagged = source_of(tool)
    if tagged is not None:
        return tagged[0]
    if name in BUILTIN_INTEGRATION_OF:
        return BUILTIN_INTEGRATION_OF[name]
    group = config_groups.get(name)
    if group:
        return f"builtin:{group}"
    raise LookupError(name)


def apply_tool_access(tools: Iterable[BaseTool], access: Any, *, config: Any, config_groups: Mapping[str, str] | None = None) -> list[BaseTool]:
    """Keep the core tools, and each other tool only when its integration AND
    its name are on the allowlist. ``access`` None: unchanged (no allowlist).

    ``config_groups``: config.yaml tool name -> group, by the name each loaded
    tool is offered as; defaults to the config's own names."""
    parsed = access_of(access)
    tools = list(tools)
    if parsed is None:
        return tools
    integrations, names = parsed
    groups = {**config_tool_groups(config), **(config_groups or {})}
    kept: list[BaseTool] = []
    for tool in tools:
        try:
            integration = integration_of(tool, config_groups=groups)
        except LookupError:
            logger.info("agent tool access: %r belongs to no known integration; not offered", tool.name)
            continue
        if integration is None or (integration in integrations and tool.name in names):
            kept.append(tool)
    return kept


def local_servers(access: Any) -> set[str] | None:
    """The MCP server names an allowlist names (None: no allowlist)."""
    parsed = access_of(access)
    if parsed is None:
        return None
    return {i.split(":", 1)[1] for i in parsed[0] if i.startswith("local:")}


def connector_toolkits(access: Any) -> list[str]:
    """The Composio toolkits an allowlist names, upper-case."""
    parsed = access_of(access)
    if parsed is None:
        return []
    return sorted({i.split(":", 1)[1].upper() for i in parsed[0] if i.startswith("connector:")})
