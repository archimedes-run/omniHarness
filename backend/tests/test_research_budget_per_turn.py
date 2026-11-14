"""One research budget per person's turn, enforced at the tool chokepoint for
every agent (live chat 2026-11-14: 19 searches over 7+ minutes for "who is X").

Through a real agent loop (langchain create_agent) with a model that never
stops searching: the lead, and a subagent joining the lead's turn, both stop
at the cap, and a final reply exists that says research stopped early. The
gateway-level paths (summaries, the research tool, batches, repeats) are the
M-WHOIS* eval tasks (tests/eval).
"""

from __future__ import annotations

import itertools
from typing import Any

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from pydantic import ConfigDict

from omniharness.agents import research_ledger
from omniharness.agents.middlewares.turn_budget_middleware import STOPPED_EARLY_PREFIX, TurnBudgetMiddleware
from omniharness.agents.turns import USER_TURN_MARKER
from omniharness.config.research_budget_config import ResearchBudgetConfig

RAN: list[str] = []


@tool
def web_search(query: str) -> str:
    """Search the web."""
    RAN.append(query)
    return '{"results":[{"title":"Profile","url":"https://example.org/p"},{"title":"News","url":"https://news.example.com/n"}]}'


class KeepsSearching(BaseChatModel):
    """Asks for `per_reply` new searches in every reply, forever."""

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)
    per_reply: int = 1
    seen: list[list[Any]] = []

    @property
    def _llm_type(self) -> str:
        return "keeps-searching"

    def bind_tools(self, tools: Any, **kwargs: Any) -> KeepsSearching:
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.seen.append(list(messages))
        n = next(_COUNTER)
        calls = [{"name": "web_search", "args": {"query": f"topic {n} part {i}"}, "id": f"c{n}_{i}", "type": "tool_call"} for i in range(self.per_reply)]
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="", tool_calls=calls))])


_COUNTER = itertools.count()


@pytest.fixture(autouse=True)
def _fresh():
    RAN.clear()
    research_ledger.reset_for_tests()
    yield
    research_ledger.reset_for_tests()


def _agent(mw: TurnBudgetMiddleware, per_reply: int = 1):
    model = KeepsSearching(per_reply=per_reply, seen=[])
    return create_agent(model=model, tools=[web_search], middleware=[mw]), model


def _final(state: dict) -> AIMessage:
    last = state["messages"][-1]
    assert isinstance(last, AIMessage) and not last.tool_calls, "the loop ended without a final reply"
    return last


BUDGET = ResearchBudgetConfig(max_searches=6, max_fetches=4, max_seconds=90)


@pytest.mark.parametrize("per_reply", [1, 4], ids=["one-at-a-time", "batch"])
def test_the_lead_stops_at_the_cap_and_answers(per_reply: int) -> None:
    agent, model = _agent(TurnBudgetMiddleware(BUDGET), per_reply)
    state = agent.invoke({"messages": [HumanMessage(content="who is Jane Roe", id="h1", additional_kwargs={USER_TURN_MARKER: True})]}, context={"thread_id": "t1", "run_id": "r1"}, config={"recursion_limit": 60})
    assert len(RAN) == 6, RAN
    final = _final(state)
    assert STOPPED_EARLY_PREFIX in final.content
    assert "https://example.org/p" in final.content, "the fallback answer lists the sources found"
    # The last model call was told research stopped.
    assert "no more web lookups for this question" in str(model.seen[-1][-1].content)


def test_a_subagent_shares_the_turns_budget() -> None:
    lead = TurnBudgetMiddleware(BUDGET)
    lead_agent, _ = _agent(lead)
    # The lead made 4 searches in this turn...
    ledger = research_ledger.ledgers().open("t2", "h2", lead._caps(None, BUDGET), run_id="r2")
    for i in range(4):
        assert research_ledger.ledgers().reserve(ledger, "web_search", {"query": f"lead {i}"})[0] == research_ledger.OK
    # ...so a subagent (its own per-call budget is 5) gets the 2 that are left.
    sub_agent, _ = _agent(TurnBudgetMiddleware(BUDGET.for_subagent(), scale_to_items=False, shared="join"))
    state = sub_agent.invoke({"messages": [HumanMessage(content="brief: who is Jane Roe")]}, context={"thread_id": "t2", "run_id": "r2"}, config={"recursion_limit": 60})
    assert len(RAN) == 2, RAN
    assert STOPPED_EARLY_PREFIX in _final(state).content
    assert ledger.searches == 6
    del lead_agent


def test_a_request_for_many_items_keeps_its_scaled_budget() -> None:
    agent, _ = _agent(TurnBudgetMiddleware(BUDGET))
    agent.invoke({"messages": [HumanMessage(content="Find 12 date-night restaurants in Philadelphia", id="h3", additional_kwargs={USER_TURN_MARKER: True})]}, context={"thread_id": "t3", "run_id": "r3"}, config={"recursion_limit": 120})
    assert len(RAN) == 16, len(RAN)


def test_research_time_is_one_clock_per_turn() -> None:
    now = [0.0]
    ledgers = research_ledger.reset_for_tests(clock=lambda: now[0])
    caps = research_ledger.Caps(searches=6, fetches=4, research=3, seconds=90)
    ledger = ledgers.open("t4", "h4", caps, run_id="r4")
    assert ledgers.reserve(ledger, "web_search", {"query": "a"})[0] == research_ledger.OK
    now[0] = 91.0
    # The same turn after a summary (same turn key) does not restart the clock.
    assert ledgers.open("t4", "h4", caps, run_id="r4") is ledger
    assert ledgers.reserve(ledger, "web_search", {"query": "b"})[0] == research_ledger.OUT_OF_TIME
    # A resume run of the turn (a card answered later) gets its own clock, same counts.
    again = ledgers.open("t4", "h4", caps, run_id="r5")
    assert again is ledger and ledger.searches == 1
    assert ledgers.reserve(ledger, "web_search", {"query": "c"})[0] == research_ledger.OK


def test_near_duplicate_searches_are_refused() -> None:
    from omniharness.agents.research_ledger import query_terms

    assert query_terms("Who is Jane Roe?") == query_terms("jane roe") == query_terms("JANE  ROE!")
    assert query_terms("new york to boston") != query_terms("boston to new york"), "word order counts in a short query"
    assert query_terms("latest react release") != query_terms("react release")
    assert query_terms("jane roe awards") != query_terms("jane roe")


def test_the_caps_come_from_the_persons_message_never_a_summary() -> None:
    """After a summary the turn starts with the summary, whose plan record has
    numbers: they raised the search cap mid-turn (found while reproducing)."""
    from types import SimpleNamespace

    from omniharness.agents.turns import TURN_SUMMARY_MARKER

    mw = TurnBudgetMiddleware(BUDGET)
    summary = HumanMessage(content="Here is a summary: 12 items found, 3 left.", name="summary", additional_kwargs={TURN_SUMMARY_MARKER: {"turn_key": "h5", "tools": [], "start_found": True}})
    assert mw._search_cap(SimpleNamespace(state={"messages": [summary]}), BUDGET) == 6
    # And a turn's caps are fixed when it opens.
    ledgers = research_ledger.ledgers()
    small = research_ledger.Caps(searches=6, fetches=4, research=3, seconds=90)
    ledger = ledgers.open("t5", "h5", small, run_id="r")
    ledgers.open("t5", "h5", research_ledger.Caps(searches=16, fetches=9, research=3, seconds=170), run_id="r")
    assert ledger.caps == small


# -- review H1: the budget and its stop are for LOOKUPS only ------------------

WROTE: list[str] = []


@tool
def write_file(path: str, content: str) -> str:
    """Write a file."""
    WROTE.append(path)
    return "OK"


@tool
def bash(command: str) -> str:
    """Run a command."""
    return f"ran {command}"


class Scripted(BaseChatModel):
    """Replies with the given steps in order (each: content and tool calls)."""

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)
    steps: list[dict] = []
    seen: list[list[Any]] = []

    @property
    def _llm_type(self) -> str:
        return "scripted-steps"

    def bind_tools(self, tools: Any, **kwargs: Any) -> Scripted:
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.seen.append(list(messages))
        step = self.steps.pop(0) if self.steps else {"content": "done"}
        calls = [{"name": n, "args": a, "id": f"s{next(_COUNTER)}", "type": "tool_call"} for n, a in step.get("calls", [])]
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=step.get("content", ""), tool_calls=calls))])


def _searches(n: int, tag: str) -> list:
    return [("web_search", {"query": f"{tag} topic {i}"}) for i in range(n)]


def test_after_the_stop_other_tools_still_run() -> None:
    WROTE.clear()
    model = Scripted(steps=[{"calls": _searches(8, "crm")}, {"calls": [("web_search", {"query": "one more"}), ("write_file", {"path": "summary.md", "content": "x"})]}, {"content": "Summary written to summary.md."}], seen=[])
    agent = create_agent(model=model, tools=[web_search, write_file], middleware=[TurnBudgetMiddleware(BUDGET)])
    state = agent.invoke(
        {"messages": [HumanMessage(content="Research CRM tools, then write me a summary file", id="h6", additional_kwargs={USER_TURN_MARKER: True})]}, context={"thread_id": "t6", "run_id": "r6"}, config={"recursion_limit": 60}
    )
    assert len(RAN) == 6, RAN
    assert WROTE == ["summary.md"], "a non-lookup tool call was dropped after the research stop"
    assert "one more" not in " ".join(RAN), "a lookup ran after the stop"
    final = _final(state)
    assert final.content.startswith("Summary written") and STOPPED_EARLY_PREFIX in final.content


def test_a_lookup_after_the_stop_is_refused() -> None:
    from types import SimpleNamespace

    mw = TurnBudgetMiddleware(BUDGET)
    ledger = research_ledger.ledgers().open("t7", "h7", mw._caps(None, BUDGET), run_id="r7")
    research_ledger.ledgers().stop(ledger, "search budget")
    request = SimpleNamespace(
        state={"messages": [HumanMessage(content="q", id="h7", additional_kwargs={USER_TURN_MARKER: True})]},
        tool_call={"name": "web_fetch", "args": {"url": "https://a.example"}, "id": "f1"},
        runtime=SimpleNamespace(context={"thread_id": "t7", "run_id": "r7"}),
    )
    out = mw.wrap_tool_call(request, lambda r: (_ for _ in ()).throw(AssertionError("the lookup ran")))
    assert out.content.startswith("Not run:")
    # A non-lookup call goes through untouched.
    request.tool_call = {"name": "write_file", "args": {"path": "a", "content": "b"}, "id": "w1"}
    from langchain_core.messages import ToolMessage

    assert mw.wrap_tool_call(request, lambda r: ToolMessage(content="OK", tool_call_id="w1", name="write_file")).content == "OK"


def test_a_coding_subagent_started_late_gets_no_research_notes() -> None:
    now = [0.0]
    research_ledger.reset_for_tests(clock=lambda: now[0])
    lead = TurnBudgetMiddleware(BUDGET, clock=lambda: now[0])
    research_ledger.ledgers().open("t8", "h8", lead._caps(None, BUDGET), run_id="r8")
    now[0] = 120.0  # two minutes of turn time, no lookups
    model = Scripted(steps=[{"calls": [("bash", {"command": f"step {i}"})]} for i in range(30)] + [{"content": "built"}], seen=[])
    sub = create_agent(model=model, tools=[bash], middleware=[TurnBudgetMiddleware(BUDGET, scale_to_items=False, shared="join", notes=False, clock=lambda: now[0])])
    state = sub.invoke({"messages": [HumanMessage(content="build the app")]}, context={"thread_id": "t8", "run_id": "r8", research_ledger.TURN_KEY_CONTEXT: "h8"}, config={"recursion_limit": 100})
    results = [m.content for m in state["messages"] if getattr(m, "type", "") == "tool"]
    assert len(results) == 30 and all(r.startswith("ran step") and "[This task" not in r for r in results), results[-1]
    assert state["messages"][-1].content == "built"


def test_a_long_turn_with_one_late_lookup_is_allowed() -> None:
    from types import SimpleNamespace

    from langchain_core.messages import ToolMessage

    now = [0.0]
    research_ledger.reset_for_tests(clock=lambda: now[0])
    mw = TurnBudgetMiddleware(BUDGET, clock=lambda: now[0])
    state = {"messages": [HumanMessage(content="build me an app", id="h9", additional_kwargs={USER_TURN_MARKER: True})]}
    ctx = SimpleNamespace(context={"thread_id": "t9", "run_id": "r9"})
    for i in range(5):  # coding calls for a long time
        mw.wrap_tool_call(SimpleNamespace(state=state, tool_call={"name": "bash", "args": {"command": str(i)}, "id": f"b{i}"}, runtime=ctx), lambda r: ToolMessage(content="ok", tool_call_id=r.tool_call["id"], name="bash"))
        now[0] += 60
    out = mw.wrap_tool_call(SimpleNamespace(state=state, tool_call={"name": "web_search", "args": {"query": "vite docs"}, "id": "s1"}, runtime=ctx), lambda r: ToolMessage(content="results", tool_call_id="s1", name="web_search"))
    assert out.content == "results", "a late first lookup was refused as out of research time"


def test_a_research_call_keeps_its_floor_when_the_turn_is_spent() -> None:
    caps = research_ledger.Caps(searches=6, fetches=6, research=3, seconds=90)
    ledgers = research_ledger.ledgers()
    turn = ledgers.open("t10", "h10", caps, run_id="r10")
    for i in range(6):
        assert ledgers.reserve(turn, "web_search", {"query": f"lead {i}"})[0] == research_ledger.OK
    own = research_ledger.TurnLedger(thread_id="t10", turn_key="sub", caps=research_ledger.Caps(5, 5, 1, 90), floor=(2, 2))
    assert [ledgers.reserve(turn, "web_search", {"query": f"sub {i}"}, extra=own)[0] for i in range(3)] == [research_ledger.OK, research_ledger.OK, research_ledger.OVER_SEARCHES]


def test_repeats_are_per_tool_and_never_count_toward_the_stop() -> None:
    caps = research_ledger.Caps(searches=6, fetches=6, research=3, seconds=90)
    ledgers = research_ledger.ledgers()
    turn = ledgers.open("t11", "h11", caps, run_id="r11")
    assert ledgers.reserve(turn, "web_search", {"query": "eiffel tower"})[0] == research_ledger.OK
    assert ledgers.reserve(turn, "image_search", {"query": "eiffel tower"})[0] == research_ledger.OK
    for _ in range(4):
        assert ledgers.reserve(turn, "web_search", {"query": "Eiffel Tower?"})[0] == research_ledger.REPEAT
    assert turn.budget_refusals == 0 and not turn.stopped
