"""Record, per tool source, whether its calls work (Feature 006).

At the tool-call chokepoint: a call to a tool tagged with a source
(tools/source_tags.py) that returns without error is an OBSERVED success for
that source; one that raises or returns an error message is an observed
failure. The chat bar reads these through /api/tool-sources: "Connected" until
a call has worked, then "Live · last worked <time>".

It sits inside the policy layer, so a call the policy blocked never reaches a
source and is never counted against it. Recording never affects the call: a
write that fails is logged and dropped. Only the async path records (every
agent run is async); a sync call is passed through unrecorded.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphBubbleUp
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from omniharness.tools.source_tags import source_of

logger = logging.getLogger(__name__)


def _health_repo():
    from omniharness.persistence.engine import get_session_factory
    from omniharness.persistence.tool_source_health import ToolSourceHealthRepository

    sf = get_session_factory()
    return ToolSourceHealthRepository(sf) if sf is not None else None


def call_outcome(result: ToolMessage | Command) -> tuple[bool, str]:
    """(worked, error text). A Command (control flow) counts as worked."""
    if isinstance(result, ToolMessage) and result.status == "error":
        return False, str(result.content)
    return True, ""


class ToolSourceHealthMiddleware(AgentMiddleware[AgentState]):
    def __init__(self, repo_factory: Callable[[], object | None] = _health_repo) -> None:
        super().__init__()
        self._repo_factory = repo_factory

    async def _record(self, request: ToolCallRequest, worked: bool, error: str) -> None:
        tagged = source_of(getattr(request, "tool", None))
        if tagged is None:
            return
        source_id, owner_id = tagged
        try:
            repo = self._repo_factory()
            if repo is None:
                return
            if worked:
                await repo.record_success(owner_id=owner_id, source_id=source_id)
            else:
                await repo.record_failure(owner_id=owner_id, source_id=source_id, error=error)
        except Exception:
            logger.warning("Could not record tool-source health for %s", source_id, exc_info=True)

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        return handler(request)

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        try:
            result = await handler(request)
        except GraphBubbleUp:
            raise
        except Exception as exc:
            await self._record(request, False, f"{type(exc).__name__}: {exc}")
            raise
        worked, error = call_outcome(result)
        await self._record(request, worked, error)
        return result
