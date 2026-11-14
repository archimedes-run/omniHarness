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
OVER_BUDGET = 'Not run: this task has used its {what} budget ({n}). Budget spent: answer now from what you have (2 to 5 solid sources are enough), and say plainly what is unverified under "Not verified".'
ANSWER_NOTE = '\n\n[This task has used {n} tool calls. Write the answer now with what you have; list anything still missing under "Not verified".]'
TIME_NOTE = '\n\n[This task has spent {s} s researching. Write the answer now with the sources you have; list anything still missing under "Not verified".]'
OUT_OF_TIME = 'Not run: this task has used its research time ({n} s). Budget spent: answer now from what you have, and say plainly what is unverified under "Not verified".'
SHORTENED = "\n\n[Page shortened for reading: the first {n} of {total} characters.]"
REPEATED = 'Not run: this search repeats one already made in this task ("{q}"): same terms. Use those results. If the budget is spent, answer now from what you have, and say what is unverified.'
#: Every refusal starts with this (never counted as a lookup).
REFUSED_PREFIXES = ("Not run: this task has used", "Not run: this search repeats", "Not run: the last fetch")
#: The hard ceiling: the last model call of a turn whose lookups ended.
ANSWER_NOW = (
    "[System: no more web lookups for this question ({why} spent): web_search, web_fetch and research will not run. "
    'Continue the rest of the request with what you have; if nothing else is left to do, write the answer now, cite the sources you used, and list what is unverified under "Not verified".]'
)
#: The last fetch, kept for a second site.
SECOND_SITE_NOTE = (
    "Not run: the last fetch of this task is kept for a second site. Every page fetched so far is from {host}, and web claims "
    "need a second, independent source: fetch a page from another site, or cite a link from another site in your search results, then answer."
)
#: A lookup asked for after the stop.
LOOKUPS_STOPPED = "Not run: this task has used its research budget; no more lookups. Budget spent: answer now from what you have and continue the rest of the request, and say what is unverified."
STOPPED_EARLY_PREFIX = "Stopped early:"
STOPPED_EARLY = "Stopped early: the {why} for this question ran out ({searches} searches, {seconds} s), so some details above may be unverified."
#: On the final reply (and the reminder): research stopped for this turn.
RESEARCH_STOP_KEY = "omniharness_research_stopped"


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


def _canonical_url(args: Any) -> str:
    url = args.get("url") if isinstance(args, dict) else None
    return urldefrag(str(url))[0] if url else _canonical(args)


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
    """`shared`: "open" for the lead (it opens the turn's ledger), "join" for a
    subagent (its lookups count in the ledger the lead opened for the thread's
    current turn, beside its own per-call budget)."""

    def __init__(self, budget: Any = None, *, scale_to_items: bool = True, clock: Any = time.monotonic, shared: str = "open", notes: bool = True, floor: tuple[int, int] = (0, 0)) -> None:
        super().__init__()
        #: Time and "answer now" notes on lookup results (off for a subagent
        #: that is not a researcher: a coding subagent's work is not research).
        self._notes = notes
        #: A subagent call's guaranteed lookups when the turn's budget is spent.
        self._floor = floor
        self._fixed = budget
        self._scale = scale_to_items
        self._clock = clock
        self._shared = shared
        #: When each task's first lookup was made (by its first message's id).
        self._started: dict[str, float] = {}
        #: A subagent's own per-call ledger (this instance serves one call).
        self._own: Any = None

    @property
    def budget(self) -> Any:
        return self._fixed if self._fixed is not None else _budget()

    @staticmethod
    def _messages(request: Any) -> list:
        state = getattr(request, "state", None) or {}
        messages = state.get("messages") if isinstance(state, dict) else getattr(state, "messages", None)
        return list(messages or [])

    @classmethod
    def _steps(cls, request: Any) -> list[dict]:
        from omniharness.agents.working_loop import tool_steps, turn_messages

        return tool_steps(turn_messages(cls._messages(request)))

    @staticmethod
    def _counted(step: dict) -> bool:
        """A call that ran and counts: not a cached repeat, not refused here."""
        out = step["output"]
        return step["ok"] is True and not out.startswith(CACHED_PREFIX) and not out.startswith(REFUSED_PREFIXES)

    # -- the turn's shared ledger (omniharness.agents.research_ledger) ------

    @staticmethod
    def _context(request: Any) -> dict:
        runtime = getattr(request, "runtime", None)
        context = getattr(runtime, "context", None)
        return context if isinstance(context, dict) else {}

    def _caps(self, request: Any, budget: Any) -> Any:
        from omniharness.agents.research_ledger import Caps

        searches = self._search_cap(request, budget) if self._scale else budget.max_searches
        extra = max(0, searches - budget.max_searches)
        fetches = min(budget.max_fetches + (extra + 1) // 2, 2 * budget.max_fetches) if extra else budget.max_fetches
        seconds = min(budget.max_seconds + extra * getattr(budget, "seconds_per_extra_search", 8), 2 * budget.max_seconds) if extra else budget.max_seconds
        return Caps(searches=searches, fetches=fetches, research=getattr(budget, "max_research", 3), seconds=float(seconds))

    def _turn_key(self, request: Any) -> str:
        from omniharness.agents.turns import TURN_SUMMARY_MARKER
        from omniharness.agents.working_loop import _kwargs, turn_messages

        turn = turn_messages(self._messages(request))
        first = turn[0] if turn else None
        if first is None:
            return "task"
        record = _kwargs(first).get(TURN_SUMMARY_MARKER)
        if isinstance(record, dict) and record.get("turn_key"):
            return str(record["turn_key"])
        return str((first.get("id") if isinstance(first, dict) else getattr(first, "id", None)) or "task")

    def _seed(self, request: Any, steps: list[dict]) -> dict:
        """What the turn's messages show was already done (a turn resumed in
        another process, or after a summary): never count lower than that."""
        from omniharness.agents.research_ledger import query_terms
        from omniharness.agents.turns import TURN_SUMMARY_MARKER
        from omniharness.agents.working_loop import _kwargs, turn_messages

        turn = turn_messages(self._messages(request))
        record = _kwargs(turn[0]).get(TURN_SUMMARY_MARKER) if turn else None
        summarized = [str(t) for t in (record.get("tools") or [])] if isinstance(record, dict) and isinstance(record.get("tools"), list) else []
        done = [s for s in steps if self._counted(s)]
        queries = {query_terms(str(s["args"].get("query") or "")): str(s["args"].get("query") or "") for s in done if s["name"] in SEARCH_TOOLS and isinstance(s["args"], dict)}
        queries.pop("", None)
        return {
            "searches": sum(1 for t in summarized if t in SEARCH_TOOLS) + sum(1 for s in done if s["name"] in SEARCH_TOOLS),
            "fetches": {f"summarized:{i}" for i, t in enumerate(summarized) if t in FETCH_TOOLS} | {_canonical_url(s["args"]) for s in done if s["name"] in FETCH_TOOLS},
            "research": sum(1 for t in summarized if t == "research") + sum(1 for s in done if s["name"] == "research"),
            "queries": queries,
        }

    def _ledger(self, request: Any, steps: list[dict]) -> tuple[Any, Any]:
        """(the turn's ledger, this subagent call's own ledger or None), or
        (None, None) outside a thread (unit tests, a bare agent)."""
        from omniharness.agents.research_ledger import ledgers

        context = self._context(request)
        thread_id = str(context.get("thread_id") or "")
        if not thread_id:
            return None, None
        budget = self.budget
        if self._shared == "join":
            from omniharness.agents.research_ledger import TurnLedger

            if self._own is None:
                self._own = TurnLedger(thread_id=thread_id, turn_key="subagent-call", caps=self._caps(request, budget), floor=self._floor)
            return self._joined_turn(context, thread_id), self._own
        ledger = ledgers().open(thread_id, self._turn_key(request), self._caps(request, budget), run_id=str(context.get("run_id") or ""), seed=self._seed(request, steps))
        return ledger, None

    @staticmethod
    def _joined_turn(context: dict, thread_id: str) -> Any:
        """The ledger of the turn that started this subagent: the thread's
        current one, and only if it is the same turn (its key was passed to
        the subagent by the delegating call)."""
        from omniharness.agents.research_ledger import TURN_KEY_CONTEXT, ledgers

        current = ledgers().current(thread_id)
        wanted = context.get(TURN_KEY_CONTEXT)
        if current is not None and wanted and current.turn_key != wanted:
            return None
        return current

    def _refusal(self, outcome: str, detail: str, call_id: str, name: str, ledger: Any, own: Any) -> ToolMessage:
        from omniharness.agents import research_ledger as rl

        if outcome == rl.REPEAT:
            text = REPEATED.format(q=detail)
        elif outcome == rl.STOPPED:
            text = LOOKUPS_STOPPED + rl.sites_note(ledger or own)
        elif outcome == rl.SECOND_SITE:
            text = SECOND_SITE_NOTE.format(host=detail)
        elif outcome == rl.OUT_OF_TIME:
            text = OUT_OF_TIME.format(n=detail)
        else:
            text = OVER_BUDGET.format(what=outcome, n=detail) + rl.sites_note(ledger or own)
        budget = self.budget
        hard = getattr(budget, "hard_stop_after_refusals", 2)
        for one in (ledger, own):
            if one is not None and one.budget_refusals >= hard:
                rl.ledgers().stop(one, "research time" if outcome == rl.OUT_OF_TIME else f"{outcome} budget")
        return ToolMessage(content=text, tool_call_id=call_id, name=name)

    def _elapsed(self, request: Any) -> float:
        """Seconds since this task's first tool call (per task: the id of the
        message that started it). Only without a thread (no shared ledger)."""
        key = self._turn_key(request)
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
        self._reserved = None
        if name in REPEATABLE_READS:
            wanted = _canonical(call.get("args"))
            for step in steps:
                if step["name"] == name and step["id"] != call_id and step["ok"] is True and _canonical(step["args"]) == wanted and not step["output"].lstrip().startswith(_NOT_CACHEABLE):
                    earlier = step["output"].removeprefix(CACHED_PREFIX)
                    return ToolMessage(content=CACHED_PREFIX + earlier, tool_call_id=call_id, name=name)
        budget = self.budget
        self._last_elapsed = 0.0
        self._last_caps = None
        self._last_ledger = None
        if not getattr(budget, "enabled", True):
            return None
        from omniharness.agents.research_ledger import LOOKUP_TOOLS

        if name not in LOOKUP_TOOLS:
            return None  # the budget, its clock and its stop are for lookups only
        ledger, own = self._ledger(request, steps)
        if ledger is not None or own is not None:
            from omniharness.agents.research_ledger import OK, ledgers

            turn = ledger if ledger is not None else own
            extra = own if ledger is not None else None
            args = call.get("args") if isinstance(call.get("args"), dict) else {}
            outcome, detail = ledgers().reserve(turn, name, args, extra=extra)
            self._last_elapsed = max(one.elapsed(self._clock()) for one in (ledger, own) if one is not None)
            self._last_caps = turn.caps
            self._last_ledger = turn
            if outcome != OK:
                return self._refusal(outcome, detail, call_id, name, ledger, own)
            self._reserved = (turn, extra, name, args)
            return None
        return self._early_from_messages(request, steps, name, call_id, budget)

    def _early_from_messages(self, request: Any, steps: list[dict], name: str, call_id: str, budget: Any) -> ToolMessage | None:
        """No thread (no shared ledger): counted from the turn's messages."""
        self._last_elapsed = self._elapsed(request)
        self._last_caps = None
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

    def _settle(self, result: Any) -> None:
        """A reserved lookup that did not run as one (a card, a refusal, an
        error) gives its reservation back."""
        reserved, self._reserved = getattr(self, "_reserved", None), None
        if reserved is None:
            return
        content = getattr(result, "content", None)
        text = content if isinstance(content, str) else ""
        if isinstance(result, ToolMessage) and (getattr(result, "status", None) == "error" or text.lstrip().startswith(_NOT_CACHEABLE)):
            from omniharness.agents.research_ledger import ledgers

            turn, extra, name, args = reserved
            for one in (turn, extra):
                if one is not None:
                    ledgers().release(one, name, args)

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
        (one search per item, plus a few), never above `max_scaled_searches`:
        "12 date-night restaurants" gets 16, "who is X" keeps 6, "5 picks" 9."""
        from omniharness.agents.working_loop import _type, text_of, turn_messages

        state = getattr(request, "state", None) or {}
        messages = state.get("messages") if isinstance(state, dict) else getattr(state, "messages", None)
        turn = turn_messages(list(messages or []))
        # The person's own message only: after a summary the turn starts with
        # the summary, whose text (numbers in the plan record) scaled the cap.
        from omniharness.agents.turns import TURN_SUMMARY_MARKER
        from omniharness.agents.working_loop import _kwargs

        asked = text_of(turn[0]) if turn and _type(turn[0]) == "human" and TURN_SUMMARY_MARKER not in _kwargs(turn[0]) else ""
        numbers = [int(n) for n in self._ITEMS_RE.findall(asked or "") if 1 < int(n) <= 50]
        wanted = max(numbers) + 4 if numbers else 0
        ceiling = getattr(budget, "max_scaled_searches", 2 * budget.max_searches)
        return max(budget.max_searches, min(wanted, ceiling))

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
        from omniharness.agents.research_ledger import LOOKUP_TOOLS

        if not self._notes or result.name not in LOOKUP_TOOLS:
            # Notes are about research: only on a lookup's result, and never in
            # a subagent that is not a researcher.
            return result if content == result.content else result.model_copy(update={"content": content})
        count = sum(1 for s in steps if s["name"] not in NON_EVIDENCE_TOOLS and s["ok"] is not None) + 1
        elapsed = getattr(self, "_last_elapsed", 0.0)
        caps = getattr(self, "_last_caps", None)
        seconds = caps.seconds if caps is not None else budget.max_seconds
        from omniharness.agents.research_ledger import sites_note

        sites = sites_note(getattr(self, "_last_ledger", None))
        if elapsed >= 0.6 * seconds:
            content += TIME_NOTE.format(s=int(elapsed)).rstrip("]") + sites + "]"
        elif count >= budget.answer_after_calls:
            content += ANSWER_NOTE.format(n=count).rstrip("]") + sites + "]"
        return result if content == result.content else result.model_copy(update={"content": content})

    def _turn_token(self, request: Any) -> Any:
        """The lead's turn key, visible to a subagent the call starts."""
        if self._shared != "open":
            return None
        from omniharness.agents.research_ledger import CURRENT_TURN_KEY

        return CURRENT_TURN_KEY.set(self._turn_key(request))

    def wrap_tool_call(self, request, handler):
        steps = self._steps(request)
        early = self._early(request, steps)
        if early is not None:
            return early
        token = self._turn_token(request)
        try:
            result = handler(request)
        finally:
            if token is not None:
                from omniharness.agents.research_ledger import CURRENT_TURN_KEY

                CURRENT_TURN_KEY.reset(token)
        self._settle(result)
        return self._with_note(result, steps)

    async def awrap_tool_call(self, request, handler):
        steps = self._steps(request)
        early = self._early(request, steps)
        if early is not None:
            return early
        token = self._turn_token(request)
        try:
            result = await handler(request)
        finally:
            if token is not None:
                from omniharness.agents.research_ledger import CURRENT_TURN_KEY

                CURRENT_TURN_KEY.reset(token)
        self._settle(result)
        return self._with_note(result, steps)

    # -- the hard ceiling: tool calls end and the agent answers -------------

    def _stopped(self, request: Any) -> tuple[Any, str]:
        """(the ledger, why) when this turn's lookups have ended, else (None, "")."""
        from omniharness.agents.research_ledger import ledgers

        thread_id = str(self._context(request).get("thread_id") or "")
        if not thread_id or not getattr(self.budget, "enabled", True):
            return None, ""
        if self._shared == "join":
            for one in (self._own, self._joined_turn(self._context(request), thread_id)):
                if one is not None and one.stopped:
                    return one, one.stopped
            return None, ""
        ledger = ledgers().current(thread_id)
        if ledger is None or not ledger.stopped or ledger.turn_key != self._turn_key(request):
            return None, ""
        return ledger, ledger.stopped

    def _answer_request(self, request: Any, why: str) -> Any:
        from langchain_core.messages import HumanMessage

        reminder = HumanMessage(content=ANSWER_NOW.format(why=why), additional_kwargs={RESEARCH_STOP_KEY: True})
        try:
            return request.override(messages=[*request.messages, reminder])
        except Exception:  # noqa: BLE001 - an older request type: unchanged
            return request

    def _final(self, response: Any, request: Any, ledger: Any, why: str) -> Any:
        """After the stop: the reply's LOOKUP calls are dropped; every other
        tool call (a card, a file, an email, a delegation) goes through. Only
        when nothing is left to do is the reply final: never empty (a
        server-written list of the sources found, only then), and saying that
        research stopped early."""
        from langchain_core.messages import AIMessage

        from omniharness.agents.research_ledger import LOOKUP_TOOLS

        messages = list(getattr(response, "result", None) or ([response] if isinstance(response, AIMessage) else []))
        index = next((i for i in range(len(messages) - 1, -1, -1) if isinstance(messages[i], AIMessage)), None)
        if index is None:
            return response
        message = messages[index]
        calls = list(message.tool_calls or [])
        kept = [c for c in calls if str(c.get("name") or "") not in LOOKUP_TOOLS]
        invalid = [c for c in (message.invalid_tool_calls or []) if str(c.get("name") or "") not in LOOKUP_TOOLS]
        kwargs = {k: v for k, v in (message.additional_kwargs or {}).items() if k != "tool_calls"}
        if kept or invalid:
            if len(kept) == len(calls):
                return response
            final = message.model_copy(update={"tool_calls": kept, "invalid_tool_calls": invalid, "additional_kwargs": kwargs})
        else:
            text = message.text if isinstance(message.content, list) else str(message.content or "")
            if not text.strip():
                text = self._fallback_answer(request)
            if STOPPED_EARLY_PREFIX not in text:
                text = f"{text.rstrip()}\n\n{STOPPED_EARLY.format(why=why, searches=ledger.searches, seconds=int(ledger.elapsed(self._clock())))}"
            kwargs[RESEARCH_STOP_KEY] = {"why": why, "searches": ledger.searches, "fetches": len(ledger.fetches)}
            final = message.model_copy(update={"content": text, "tool_calls": [], "invalid_tool_calls": [], "additional_kwargs": kwargs})
        messages[index] = final
        if isinstance(response, AIMessage):
            return final
        try:
            return type(response)(result=messages, structured_response=getattr(response, "structured_response", None))
        except Exception:  # noqa: BLE001
            response.result = messages
            return response

    def _fallback_answer(self, request: Any) -> str:
        """A reply the server writes when the model wrote none after research
        stopped: the sources the turn's results named, never invented."""
        from omniharness.agents.working_loop import urls_in

        urls: list[str] = []
        for step in self._steps(request):
            if step["name"] in REPEATABLE_READS and step["ok"] is True and not step["output"].startswith(REFUSED_PREFIXES):
                urls.extend(u for u in urls_in(step["output"]) if u not in urls)
        urls = urls[:5]
        if not urls:
            return "I could not finish looking this up: the research budget for this question ran out before I found reliable sources. Not verified: everything above; ask again with more detail."
        return "I ran out of research budget before writing a full answer. Sources found so far:\n" + "\n".join(f"- {u}" for u in urls) + "\n\nNot verified: what these sources say about your question."

    def wrap_model_call(self, request, handler):
        ledger, why = self._stopped(request)
        if ledger is None:
            return handler(request)
        return self._final(handler(self._answer_request(request, why)), request, ledger, why)

    async def awrap_model_call(self, request, handler):
        ledger, why = self._stopped(request)
        if ledger is None:
            return await handler(request)
        return self._final(await handler(self._answer_request(request, why)), request, ledger, why)
