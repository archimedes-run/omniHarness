"""Keeps a research task bounded (spec 009 Slice 0; owner rule of 2026-11-13
after the real-model eval: research tasks made 40 to 80 tool calls, fetched the
same pages again and timed out without an answer).

Wraps tool calls only (no graph node of its own). Per task (the person's turn
and the runs that resume it):

1. FETCH CACHE. A web_fetch of a URL already fetched successfully in the task
   is answered with that result: no network call, and it does not count
   against the budget; an identical web search the same way. Public web
   lookups only (never a ledger, file or private read), and never a result
   that was an error, a refusal or a card. The cache is the task's own
   messages: one thread, one turn, one person.
2. BUDGET. At most `research_budget.max_searches` searches (web_search,
   image_search), `max_fetches` fetches (distinct URLs) and `max_research`
   delegated research calls. Past a cap the
   lookup is not made; the result tells the lead to answer with what it has
   and to say what is still uncertain.
3. TIME. From 60% of `max_seconds` (research time per task, default 150 s)
   each result says to write the answer now; past it no lookup is made.
4. Past `answer_after_calls` tool calls, each result carries a one-line note
   to write the answer now. A fetched page is shortened to `max_page_chars`.

Steering only: it never runs a call and never decides a tier (the policy layer
classifies the call before it gets here).
"""

from __future__ import annotations

import json
import time
from typing import Any
from urllib.parse import urldefrag

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

#: Lookups whose identical repeat in one task is answered from the earlier
#: result: ONLY public web lookups, which do not change within a task. Never a
#: ledger, file or other private or local read: a write in the task (or a
#: confirmed card's resume) changes those, and a cached answer would be stale.
REPEATABLE_READS = frozenset({"web_search", "web_fetch", "image_search"})
#: A result that is not a lookup's answer is never served from the cache.
_NOT_CACHEABLE = ("Error", "Not run", "Waiting for you", "Refused", "Tool '")
SEARCH_TOOLS = frozenset({"web_search", "image_search"})
FETCH_TOOLS = frozenset({"web_fetch"})

CACHED_PREFIX = "[From earlier in this task: this exact call already ran; its result is repeated here, nothing was fetched again.]\n\n"
OVER_BUDGET = 'Not run: this task has used its {what} budget ({n}). Answer now with the sources you already have (3 to 5 solid sources are enough), and say plainly what is still uncertain under "Not verified".'
ANSWER_NOTE = '\n\n[This task has used {n} tool calls. Write the answer now with what you have; list anything still missing under "Not verified".]'
TIME_NOTE = '\n\n[This task has spent {s} s researching. Write the answer now with the sources you have; list anything still missing under "Not verified".]'
OUT_OF_TIME = 'Not run: this task has used its research time ({n} s). Answer now with the sources you already have, and say plainly what is still uncertain under "Not verified".'
SHORTENED = "\n\n[Page shortened for reading: the first {n} of {total} characters.]"


def _canonical(args: Any) -> str:
    """A call's arguments as compared for "the same lookup". A URL's #fragment
    is dropped: "page#whats-new" is the same page (the real eval refetched one
    page under five anchors)."""
    if isinstance(args, dict) and isinstance(args.get("url"), str):
        args = {**args, "url": urldefrag(args["url"])[0]}
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


def _compact_json(text: str, limit: int) -> str | None:
    """A JSON page made readable: long strings described by their length,
    long lists and maps cut to their first and last few entries (with a
    count). PyPI's package JSON is ~100 KB, its README sits before "version",
    and a plain cut lost the very field asked for (real eval T13). None when
    the text is not JSON."""
    stripped = text.lstrip()
    if not stripped.startswith(("{", "[")):
        return None
    try:
        data = json.loads(stripped)
    except ValueError:
        return None

    def shrink(value: Any, depth: int = 0) -> Any:
        if isinstance(value, str):
            return value if len(value) <= 300 else f"<{len(value)} characters>"
        if isinstance(value, list):
            items = [shrink(v, depth + 1) for v in value[:5]]
            return items + ([f"<{len(value) - 5} more items>"] if len(value) > 5 else [])
        if isinstance(value, dict):
            keys = list(value)
            if len(keys) > 40:
                kept = keys[:5] + keys[-5:]
                out = {k: shrink(value[k], depth + 1) for k in kept}
                out["<omitted>"] = f"{len(keys) - 10} more keys"
                return out
            return {k: shrink(v, depth + 1) for k, v in value.items()}
        return value

    compact = json.dumps(shrink(data), ensure_ascii=False, indent=1)
    return compact[:limit]


class TurnBudgetMiddleware(AgentMiddleware):
    def __init__(self, budget: Any = None, *, scale_to_items: bool = True, clock: Any = time.monotonic) -> None:
        super().__init__()
        self._fixed = budget
        self._scale = scale_to_items
        self._clock = clock
        #: When each task's first lookup was made (by its first message's id).
        self._started: dict[str, float] = {}

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

    def _elapsed(self, request: Any) -> float:
        """Seconds since this task's first tool call (per task: the id of the
        message that started it)."""
        from omniharness.agents.working_loop import turn_messages

        state = getattr(request, "state", None) or {}
        messages = state.get("messages") if isinstance(state, dict) else getattr(state, "messages", None)
        turn = turn_messages(list(messages or []))
        first = turn[0] if turn else None
        key = str((first.get("id") if isinstance(first, dict) else getattr(first, "id", None)) or "task")
        now = self._clock()
        start = self._started.setdefault(key, now)
        if len(self._started) > 256:  # a long-lived instance: forget the oldest tasks
            for old in list(self._started)[:128]:
                self._started.pop(old, None)
        return now - start

    def _early(self, request: Any, steps: list[dict]) -> ToolMessage | None:
        call = getattr(request, "tool_call", None) or {}
        name = str(call.get("name") or "")
        call_id = str(call.get("id") or "")
        self._last_elapsed = self._elapsed(request)
        if name in REPEATABLE_READS:
            wanted = _canonical(call.get("args"))
            for step in steps:
                if step["name"] == name and step["id"] != call_id and step["ok"] is True and _canonical(step["args"]) == wanted and not step["output"].lstrip().startswith(_NOT_CACHEABLE):
                    earlier = step["output"].removeprefix(CACHED_PREFIX)
                    return ToolMessage(content=CACHED_PREFIX + earlier, tool_call_id=call_id, name=name)
        budget = self.budget
        if not getattr(budget, "enabled", True):
            return None
        # Past the task's research time, no more lookups (the person is waiting).
        if name in SEARCH_TOOLS | FETCH_TOOLS | {"research"} and self._last_elapsed >= budget.max_seconds:
            return ToolMessage(content=OUT_OF_TIME.format(n=budget.max_seconds), tool_call_id=call_id, name=name)
        # Calls of the same reply made before this one count too: a reply with
        # 13 searches at once used to pass a cap of 8 whole (real eval T06).
        batch = self._earlier_in_batch(steps, call_id)
        if name in SEARCH_TOOLS:
            cap = self._search_cap(request, budget) if self._scale else budget.max_searches
            used = sum(1 for s in steps if s["name"] in SEARCH_TOOLS and self._counted(s)) + sum(1 for s in batch if s["name"] in SEARCH_TOOLS)
            if used >= cap:
                return ToolMessage(content=OVER_BUDGET.format(what="search", n=cap), tool_call_id=call_id, name=name)
        if name == "research":
            used = sum(1 for s in steps if s["name"] == "research" and self._counted(s)) + sum(1 for s in batch if s["name"] == "research")
            if used >= getattr(budget, "max_research", 3):
                return ToolMessage(content=OVER_BUDGET.format(what="research", n=budget.max_research), tool_call_id=call_id, name=name)
        if name in FETCH_TOOLS:
            used = len({_canonical(s["args"]) for s in steps if s["name"] in FETCH_TOOLS and (self._counted(s) or s in batch)})
            if used >= budget.max_fetches:
                return ToolMessage(content=OVER_BUDGET.format(what="fetch", n=budget.max_fetches), tool_call_id=call_id, name=name)
        return None

    @staticmethod
    def _earlier_in_batch(steps: list[dict], call_id: str) -> list[dict]:
        """The calls of the current reply before this one (no result yet)."""
        pending = [s for s in steps if s["ok"] is None]
        ids = [s["id"] for s in pending]
        return pending[: ids.index(call_id)] if call_id in ids else []

    #: "12 restaurants", "find 5", "top 3 day trips": the number of items asked.
    _ITEMS_RE = __import__("re").compile(r"\b(\d{1,2})\b(?!\s*(?:%|am|pm|minutes?|hours?|days?|weeks?|months?|years?|\$))")

    def _search_cap(self, request: Any, budget: Any) -> int:
        """The search cap, scaled to the number of items the person asked for
        (one search per item, plus a few), never above twice the configured
        cap: "12 date-night restaurants" gets 16, "5 picks" keeps 8."""
        from omniharness.agents.working_loop import _type, text_of, turn_messages

        state = getattr(request, "state", None) or {}
        messages = state.get("messages") if isinstance(state, dict) else getattr(state, "messages", None)
        turn = turn_messages(list(messages or []))
        asked = text_of(turn[0]) if turn and _type(turn[0]) == "human" else ""
        numbers = [int(n) for n in self._ITEMS_RE.findall(asked or "") if 1 < int(n) <= 50]
        wanted = max(numbers) + 4 if numbers else 0
        return max(budget.max_searches, min(wanted, 2 * budget.max_searches))

    def _with_note(self, result: Any, steps: list[dict]) -> Any:
        from omniharness.agents.working_loop import NON_EVIDENCE_TOOLS

        budget = self.budget
        if not getattr(budget, "enabled", True) or not isinstance(result, ToolMessage) or not isinstance(result.content, str):
            return result
        content = result.content
        # A fetched page is shortened for reading: whole pages filled the
        # context, which was summarised again and again, and the page fetched
        # again after each summary (real eval T02).
        if result.name in FETCH_TOOLS and len(content) > budget.max_page_chars and not content.startswith(("Error", "Not run")):
            compact = _compact_json(content, budget.max_page_chars)
            if compact is not None:
                content = compact + f"\n\n[JSON shortened for reading from {len(content)} characters: long text and long lists are described, not shown.]"
            else:
                content = content[: budget.max_page_chars] + SHORTENED.format(n=budget.max_page_chars, total=len(content))
        count = sum(1 for s in steps if s["name"] not in NON_EVIDENCE_TOOLS and s["ok"] is not None) + 1
        elapsed = getattr(self, "_last_elapsed", 0.0)
        if elapsed >= 0.6 * budget.max_seconds:
            content += TIME_NOTE.format(s=int(elapsed))
        elif count >= budget.answer_after_calls:
            content += ANSWER_NOTE.format(n=count)
        return result if content == result.content else result.model_copy(update={"content": content})

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
