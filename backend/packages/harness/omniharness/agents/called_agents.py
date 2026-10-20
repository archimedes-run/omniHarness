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

import asyncio
import logging
import re
import uuid
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.tools import ToolRuntime, tool

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


#: Runtime-context key the gateway sets (server-side only) when the user's own
#: turn @-mentions an agent that is a member of the chat.
CALLED_AGENT_KEY = "called_agent"
CALL_AGENT_TOOL = "call_agent"

_MENTION = re.compile(r"(?<![\w@])@([A-Za-z0-9][A-Za-z0-9_-]{0,127})")


def mentioned_member(text: str, members: list[str]) -> str | None:
    """The first chat member the text @-mentions, or None.

    Only members can be called: "@unknown" calls nobody, and an agent taken
    out of the chat is no longer called. Matching ignores case and treats
    "_" and "-" alike, as agent names do.
    """
    if not text or not members:
        return None

    def key(name: str) -> str:
        return name.strip().lower().replace("_", "-")

    by_key = {key(name): name for name in members}
    for match in _MENTION.finditer(text):
        found = by_key.get(key(match.group(1)))
        if found:
            return found
    return None


def _text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, list):
        return " ".join(block.get("text", "") for block in content if isinstance(block, dict))
    return str(content or "")


class CalledAgentMiddleware(AgentMiddleware):
    """Hands a turn that called an agent in to that agent, and reports its reply.

    Deterministic, with no lead model call either side:
    1. on the user's turn, the lead "hands off": an AI message calling
       `call_agent` (the chat shows "Lead agent -> <agent>");
    2. the call goes through the policy layer like any tool call, so the
       called agent starts from the provenance of the user's turn;
    3. the called agent's answer is posted as ITS message (`name` = agent).
    """

    def __init__(self, agent: str) -> None:
        super().__init__()
        self.agent = agent

    def _step(self, request: Any) -> Any:
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

        messages = list(getattr(request, "messages", None) or [])
        if not messages:
            return None
        last = messages[-1]
        if isinstance(last, HumanMessage):
            return AIMessage(
                content="",
                tool_calls=[{"name": CALL_AGENT_TOOL, "args": {"agent": self.agent, "prompt": _text(last)}, "id": f"call-{uuid.uuid4().hex[:12]}", "type": "tool_call"}],
            )
        if isinstance(last, ToolMessage) and last.name == CALL_AGENT_TOOL:
            return AIMessage(content=_text(last), name=self.agent)
        return None

    def wrap_model_call(self, request: Any, handler: Any) -> Any:
        step = self._step(request)
        return step if step is not None else handler(request)

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        step = self._step(request)
        return step if step is not None else await handler(request)


@tool(CALL_AGENT_TOOL, parse_docstring=True)
async def call_agent_tool(runtime: ToolRuntime, agent: str, prompt: str) -> str:
    """Run an agent the user called into this chat, and return its answer.

    Args:
        agent: The called-in agent's name.
        prompt: What the user asked it.
    """
    from omniharness.agents.tool_surface import subagent_surface
    from omniharness.config.agents_config import load_agent_config
    from omniharness.subagents.config import resolve_subagent_model_name
    from omniharness.subagents.executor import SubagentExecutor, SubagentStatus
    from omniharness.tools.builtins.task_tool import subagent_base_tools

    context = dict(getattr(runtime, "context", None) or {})
    user_id = context.get("user_id")
    config = called_agent_config(agent, user_id=user_id)
    if config is None:
        return f"{agent} is not available: no such agent."
    try:
        tool_groups = load_agent_config(agent, user_id=user_id).tool_groups  # type: ignore[union-attr]
    except (FileNotFoundError, ValueError, AttributeError):
        tool_groups = None
    app_config = context.get("app_config")
    metadata = (getattr(runtime, "config", None) or {}).get("metadata", {}) or {}
    model_name = resolve_subagent_model_name(config, metadata.get("model_name"), app_config=app_config)
    raw = context.get("selected_sources")
    selected = sorted(raw) if isinstance(raw, (list, set, tuple)) else None
    # Its tools: the chat's selection, within the agent's own tool groups.
    tools = subagent_base_tools(model_name=model_name, tool_groups=tool_groups, app_config=app_config, selected_sources=selected, user_id=user_id)
    state = getattr(runtime, "state", None) or {}
    executor = SubagentExecutor(
        config=config,
        tools=tools,
        app_config=app_config,
        parent_model=model_name,
        sandbox_state=state.get("sandbox"),
        thread_data=state.get("thread_data"),
        thread_id=context.get("thread_id"),
        tool_surface=subagent_surface(subagent_type=agent, model_name=model_name, tool_groups=tool_groups, skills=config.skills, user_id=user_id, called_agent=True, selected_sources=selected),
        user_id=user_id,
    )
    result = await asyncio.to_thread(executor.execute, prompt)
    if result.status == SubagentStatus.COMPLETED:
        return result.result or "(no answer)"
    return f"{agent} could not answer: {result.error or result.status.value}"
