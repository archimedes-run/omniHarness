"""The tool surface a run had, recorded so a confirmation can rebuild it.

A Tier 3 call is stated in one run and confirmed later, from the chat or from
its card. Executing it needs THE TOOL, and the run that proposed it is gone.
Both confirmation paths used to take whatever tools were at hand:

    chat   the lead's live tool list            -> a subagent's own tool: LookupError
    card   the thread's selection, without task -> a confirmed delegation: LookupError

(AUDIT-2026-10, addendum 2026-10-20; decision in specs/006-workspace-studio/plan.md §2.0.)

So every run carries a description of how its tool list was assembled, the
policy layer records it on the pending action, and the confirmation rebuilds
the list with the SAME functions that built it the first time:

    lead      omniharness.agents.lead_agent.agent.lead_agent_tools
    subagent  task_tool.subagent_base_tools + SubagentExecutor.effective_tools
    @-called  the same, with the called agent's own config (called_agent_config)

The description is plain JSON (it is stored with the pending action, one file
per action, and must survive a restart and be readable by any worker).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

#: Runtime-context key carrying a run's surface. Absent means a lead run, whose
#: surface is read from the keys the lead's factory reads (LEAD_KEYS).
TOOL_SURFACE_KEY = "tool_surface"

LEAD = "lead"
SUBAGENT = "subagent"

#: The runtime-config keys `_make_lead_agent` assembles its tools from.
LEAD_KEYS = ("model_name", "model", "agent_name", "subagent_enabled", "is_bootstrap", "selected_sources", "user_id", "excluded_skills")


def _jsonable(value: Any) -> Any:
    if isinstance(value, (set, tuple)):
        return sorted(value) if all(isinstance(v, str) for v in value) else list(value)
    return value


def lead_surface(context: dict | None) -> dict:
    """A lead run's surface, from its runtime context."""
    context = context or {}
    return {"kind": LEAD, "config": {key: _jsonable(context[key]) for key in LEAD_KEYS if key in context and context[key] is not None}}


def subagent_surface(
    *,
    subagent_type: str,
    model_name: str | None,
    tool_groups: list[str] | None,
    skills: list[str] | None,
    max_turns: int | None = None,
    user_id: str | None = None,
    called_agent: bool = False,
    selected_sources: list[str] | None = None,
) -> dict:
    """A delegated (or @-called) agent's surface."""
    return {
        "kind": SUBAGENT,
        "subagent_type": subagent_type,
        "model_name": model_name,
        "tool_groups": list(tool_groups) if tool_groups is not None else None,
        "skills": list(skills) if skills is not None else None,
        "max_turns": max_turns,
        "user_id": user_id,
        "called_agent": called_agent,
        "selected_sources": list(selected_sources) if selected_sources is not None else None,
    }


def surface_of(context: dict | None) -> dict:
    """The surface of the run whose runtime context this is."""
    context = context or {}
    recorded = context.get(TOOL_SURFACE_KEY)
    if isinstance(recorded, dict) and recorded.get("kind"):
        return dict(recorded)
    return lead_surface(context)


def surface_agent(surface: dict) -> str:
    if surface.get("kind") == SUBAGENT:
        return str(surface.get("subagent_type") or "subagent")
    return str((surface.get("config") or {}).get("agent_name") or "lead_agent")


def subagent_config_for(surface: dict, *, app_config: Any = None) -> Any:
    """The SubagentConfig a subagent surface names, with its recorded skills."""
    from dataclasses import replace

    name = str(surface.get("subagent_type") or "")
    if surface.get("called_agent"):
        from omniharness.agents.called_agents import called_agent_config

        config = called_agent_config(name, user_id=surface.get("user_id"))
    else:
        from omniharness.subagents import get_subagent_config

        config = get_subagent_config(name, app_config=app_config) if app_config is not None else get_subagent_config(name)
    if config is None:
        raise LookupError(f"the agent {name!r} that proposed this action no longer exists, so its tools cannot be rebuilt")
    overrides: dict[str, Any] = {"skills": surface.get("skills")}
    if surface.get("max_turns"):
        overrides["max_turns"] = surface["max_turns"]
    return replace(config, **overrides)


def tools_for_surface(surface: dict, *, app_config: Any = None) -> list:
    """Rebuild the tool list of the run that recorded `surface`."""
    kind = surface.get("kind")
    if kind == LEAD:
        from omniharness.agents.lead_agent.agent import lead_agent_tools

        return lead_agent_tools(dict(surface.get("config") or {}), app_config=app_config)
    if kind == SUBAGENT:
        from omniharness.subagents.executor import SubagentExecutor
        from omniharness.tools.builtins.task_tool import subagent_base_tools

        config = subagent_config_for(surface, app_config=app_config)
        base = subagent_base_tools(
            model_name=surface.get("model_name"),
            tool_groups=surface.get("tool_groups"),
            app_config=app_config,
            selected_sources=surface.get("selected_sources"),
            user_id=surface.get("user_id"),
        )
        executor = SubagentExecutor(config=config, tools=base, app_config=app_config, parent_model=surface.get("model_name"))
        return executor.effective_tools()
    raise LookupError(f"unknown tool surface {kind!r}")
