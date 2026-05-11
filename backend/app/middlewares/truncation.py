"""LargeContextTruncatorMiddleware — trims oversized ToolMessage payloads before the model call.

Positioned immediately before OmniHarnessSummarizationMiddleware in the chain
via @Prev so that the model's effective input window is never exceeded before
summarization runs.

Usage with create_omniharness_agent:
    from app.middlewares.truncation import LargeContextTruncatorMiddleware

    agent = create_omniharness_agent(
        model=model,
        tools=tools,
        extra_middleware=[LargeContextTruncatorMiddleware()],
    )
"""

from __future__ import annotations

from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import RemoveMessage, ToolMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.runtime import Runtime
from pydantic import Field

from omniharness.agents.features import Prev
from omniharness.agents.middlewares.summarization_middleware import OmniHarnessSummarizationMiddleware


@Prev(OmniHarnessSummarizationMiddleware)
class LargeContextTruncatorMiddleware(AgentMiddleware):
    """Truncates ToolMessage content that exceeds *threshold* characters.

    Replaces excess content with a compact marker so the model still sees
    the beginning of long tool outputs without consuming the full context window.
    Creates new ToolMessage objects rather than mutating frozen LangGraph state.
    """

    threshold: int = Field(default=50_000)
    keep: int = Field(default=10_000)

    @override
    def before_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        messages = state.get("messages", [])
        new_messages: list = []
        changed = False

        for msg in messages:
            if isinstance(msg, ToolMessage) and isinstance(msg.content, str) and len(msg.content) > self.threshold:
                trimmed = msg.content[: self.keep] + f"\n\n[... TRUNCATED {len(msg.content) - self.keep} chars ...]"
                msg = ToolMessage(
                    content=trimmed,
                    tool_call_id=msg.tool_call_id,
                    name=msg.name,
                )
                changed = True
            new_messages.append(msg)

        if not changed:
            return None

        return {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES)] + new_messages}
