"""Install the tool-name model boundary on every agent's model calls.

See omniharness.models.tool_name_boundary. This middleware does not rename
anything itself: it hands the agent factory a model that renames at
``bind_tools``/``invoke``, the last step before the provider. So every other
middleware, wherever it sits in the chain (the policy layer included), sees
only full tool names in the request it gets and the response it returns.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse

from omniharness.models.tool_name_boundary import ToolNameBoundaryModel


class ToolNameBoundaryMiddleware(AgentMiddleware[AgentState]):
    @staticmethod
    def _bounded(request: ModelRequest) -> ModelRequest:
        if isinstance(request.model, ToolNameBoundaryModel):
            return request
        return request.override(model=ToolNameBoundaryModel(request.model))

    @override
    def wrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]) -> ModelCallResult:
        return handler(self._bounded(request))

    @override
    async def awrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]) -> ModelCallResult:
        return await handler(self._bounded(request))
