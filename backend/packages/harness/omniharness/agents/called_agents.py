"""Agents called into a chat with "@" (Feature 006, Phase 2).

A called-in agent is one of the user's custom agents (Agent Studio). It runs
through the SAME machinery as a delegated subagent (plan.md §2.0):

- the subagent executor, with the agent's own config: its instructions
  (SOUL.md) as the system prompt, its skills, its model, and its tool groups;
- `invited_agent_context`, so it starts from the provenance of the user turn
  that mentioned it, which only ever degrades;
- a `subagent` tool surface with `called_agent: true`, so a Tier 3 call it
  proposes is confirmed against ITS tools, from the chat or from the card.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_FALLBACK_PROMPT = "You are {name}, an agent the user called into this conversation. Do what the user asked you, using your tools. Answer directly."


def called_agent_config(name: str, *, user_id: str | None = None) -> Any:
    """The SubagentConfig for a custom agent called in by name, or None."""
    from omniharness.config.agents_config import load_agent_config, load_agent_soul
    from omniharness.subagents.config import SubagentConfig

    try:
        agent = load_agent_config(name, user_id=user_id)
    except (FileNotFoundError, ValueError):
        return None
    if agent is None:
        return None
    soul = load_agent_soul(agent.name, user_id=user_id)
    return SubagentConfig(
        name=agent.name,
        description=agent.description,
        system_prompt=soul or _FALLBACK_PROMPT.format(name=agent.name),
        tools=None,
        # A called-in agent cannot delegate further: no nesting, as for `task`.
        disallowed_tools=["task", "call_agent"],
        skills=agent.skills,
        model=agent.model or "inherit",
    )
