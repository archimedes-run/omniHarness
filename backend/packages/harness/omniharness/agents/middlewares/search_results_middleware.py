"""Compacts search tools' results before the model reads them (Feature 007).

web_search and image_search answer with each provider's own, indented JSON;
`omniharness.tools.search_results` reduces it to title, url and a one-line
snippet per result, the same shape the chat renders as a list of links. Every
agent gets it: it is installed with the shared runtime middlewares, beside the
policy layer, so the lead, a delegated subagent and a called-in agent all see
the compact form.
"""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import AgentMiddleware


def _compact(request: Any, result: Any) -> Any:
    from omniharness.tools.search_results import SEARCH_TOOLS, compact_tool_output

    call = getattr(request, "tool_call", None) or {}
    name = call.get("name") or getattr(getattr(request, "tool", None), "name", "") or ""
    if name not in SEARCH_TOOLS:
        return result
    update = getattr(result, "update", None)
    if isinstance(update, dict) and isinstance(update.get("messages"), list):
        for message in update["messages"]:
            if getattr(message, "type", None) == "tool":
                compact_tool_output(name, message)
        return result
    return compact_tool_output(name, result)


class SearchResultsMiddleware(AgentMiddleware):
    def wrap_tool_call(self, request, handler):
        return _compact(request, handler(request))

    async def awrap_tool_call(self, request, handler):
        return _compact(request, await handler(request))
