"""Keeps a research task bounded (spec 009 Slice 0; owner rule of 2026-11-13
after the real-model eval: research tasks made 40 to 80 tool calls, fetched the
same pages again and timed out without an answer).

Wraps tool calls only (no graph node of its own). Per task (the person's turn
and the runs that resume it):

1. FETCH CACHE. A web_fetch of a URL already fetched successfully in the task
   is answered with that result: no network call, and it does not count
   against the budget. An identical repeat of another read (a search with the
   same query, a ledger or file read) is answered the same way.
2. BUDGET. At most `research_budget.max_searches` searches (web_search,
   image_search) and `max_fetches` fetches (distinct URLs). Past a cap the
   lookup is not made; the result tells the lead to answer with what it has
   and to say what is still uncertain.
3. Past `answer_after_calls` tool calls, each result carries a one-line note
   to write the answer now.

Steering only: it never runs a call and never decides a tier (the policy layer
classifies the call before it gets here).
"""

from __future__ import annotations

import json
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

#: Reads whose identical repeat in one task is answered from the earlier result.
REPEATABLE_READS = frozenset({"web_search", "web_fetch", "image_search", "ledger_read", "read_file", "ls"})
SEARCH_TOOLS = frozenset({"web_search", "image_search"})
FETCH_TOOLS = frozenset({"web_fetch"})

CACHED_PREFIX = "[From earlier in this task: this exact call already ran; its result is repeated here, nothing was fetched again.]\n\n"
OVER_BUDGET = 'Not run: this task has used its {what} budget ({n}). Answer now with the sources you already have (3 to 5 solid sources are enough), and say plainly what is still uncertain under "Not verified".'
ANSWER_NOTE = '\n\n[This task has used {n} tool calls. Write the answer now with what you have; list anything still missing under "Not verified".]'


def _canonical(args: Any) -> str:
    try:
        return json.dumps(args or {}, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(args)


def _budget(app_config: Any = None) -> Any:
    try:
        if app_config is None:
            from omniharness.config import get_app_config

            app_config = get_app_config()
        return app_config.research_budget
    except Exception:  # noqa: BLE001 - the defaults apply without a config
        from omniharness.config.research_budget_config import ResearchBudgetConfig

        return ResearchBudgetConfig()


class TurnBudgetMiddleware(AgentMiddleware):
    def __init__(self, budget: Any = None) -> None:
        super().__init__()
        self._fixed = budget

    @property
    def budget(self) -> Any:
        return self._fixed if self._fixed is not None else _budget()

    @staticmethod
    def _steps(request: Any) -> list[dict]:
        from omniharness.agents.working_loop import tool_steps, turn_messages

        state = getattr(request, "state", None) or {}
        messages = state.get("messages") if isinstance(state, dict) else getattr(state, "messages", None)
        return tool_steps(turn_messages(list(messages or [])))

    @staticmethod
    def _counted(step: dict) -> bool:
        """A call that ran and counts: not a cached repeat, not refused here."""
        out = step["output"]
        return step["ok"] is True and not out.startswith(CACHED_PREFIX) and not out.startswith("Not run: this task has used")

    def _early(self, request: Any, steps: list[dict]) -> ToolMessage | None:
        call = getattr(request, "tool_call", None) or {}
        name = str(call.get("name") or "")
        call_id = str(call.get("id") or "")
        if name in REPEATABLE_READS:
            wanted = _canonical(call.get("args"))
            for step in steps:
                if step["name"] == name and step["id"] != call_id and step["ok"] is True and _canonical(step["args"]) == wanted:
                    earlier = step["output"].removeprefix(CACHED_PREFIX)
                    return ToolMessage(content=CACHED_PREFIX + earlier, tool_call_id=call_id, name=name)
        budget = self.budget
        if not getattr(budget, "enabled", True):
            return None
        if name in SEARCH_TOOLS:
            used = sum(1 for s in steps if s["name"] in SEARCH_TOOLS and self._counted(s))
            if used >= budget.max_searches:
                return ToolMessage(content=OVER_BUDGET.format(what="search", n=budget.max_searches), tool_call_id=call_id, name=name)
        if name in FETCH_TOOLS:
            used = len({_canonical(s["args"]) for s in steps if s["name"] in FETCH_TOOLS and self._counted(s)})
            if used >= budget.max_fetches:
                return ToolMessage(content=OVER_BUDGET.format(what="fetch", n=budget.max_fetches), tool_call_id=call_id, name=name)
        return None

    def _with_note(self, result: Any, steps: list[dict]) -> Any:
        from omniharness.agents.working_loop import NON_EVIDENCE_TOOLS

        budget = self.budget
        count = sum(1 for s in steps if s["name"] not in NON_EVIDENCE_TOOLS and s["ok"] is not None) + 1
        if not getattr(budget, "enabled", True) or count < budget.answer_after_calls:
            return result
        if not isinstance(result, ToolMessage) or not isinstance(result.content, str):
            return result
        return result.model_copy(update={"content": result.content + ANSWER_NOTE.format(n=count)})

    def wrap_tool_call(self, request, handler):
        steps = self._steps(request)
        early = self._early(request, steps)
        if early is not None:
            return early
        return self._with_note(handler(request), steps)

    async def awrap_tool_call(self, request, handler):
        steps = self._steps(request)
        early = self._early(request, steps)
        if early is not None:
            return early
        return self._with_note(await handler(request), steps)
