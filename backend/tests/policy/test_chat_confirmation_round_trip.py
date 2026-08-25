"""T006-T008 — the chat route, through a real agent.

NAMED FOR THE SEAM THAT WORKS. tasks.md calls this
`test_before_model_confirmation.py`, and research R1 did verify `before_model`
can read the latest human turn and drive recognise -> claim -> execute. What the
probe did not need was the TOOL: `before_model(state, runtime)` has no route to
one, and `AgentMiddleware.tools` contributes tools rather than receiving them.
`ModelRequest` carries `tools`, so the completion lives in `wrap_model_call`.

Recorded here rather than silently: a probe that answers the question asked can
still leave the question that matters unasked.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool as make_tool

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
SEEN: list[str] = []
RAN: list[dict] = []


class ToolCapableFake(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


@make_tool
def calendar_decline(meetings: list[str]) -> str:
    """Decline the named meetings."""
    RAN.append({"meetings": list(meetings)})
    return f"declined {len(meetings)}"


class Watcher(AgentMiddleware):
    """Records that the seam runs, and that it can see the tools."""

    def wrap_model_call(self, request, handler):
        SEEN.append(",".join(sorted(getattr(t, "name", "?") for t in (request.tools or []))))
        return handler(request)


def _agent(system, extra=()):
    model = ToolCapableFake(
        messages=iter(
            [
                AIMessage(content="", tool_calls=[{"name": "calendar_decline", "args": {"meetings": ["Standup", "Review"]}, "id": "tc1"}]),
                AIMessage(content="Here is the plan."),
                AIMessage(content="Anything else?"),
            ]
        )
    )
    return create_agent(model=model, tools=[calendar_decline], middleware=[*extra, system.middleware])


@pytest.fixture(autouse=True)
def _clear():
    SEEN.clear()
    RAN.clear()


def test_positive_control_the_seam_runs_and_can_see_the_tools(build_flow):
    """T007. Without this, 'the confirmation did not complete' is
    indistinguishable from 'the hook never ran' — which is precisely how the
    first subagent probe in this project produced a wrong finding."""
    system = build_flow()
    agent = _agent(system, extra=[Watcher()])
    agent.invoke({"messages": [HumanMessage(content="decline my morning meetings")]})

    assert SEEN, "wrap_model_call was never invoked; nothing below means anything"
    assert "calendar_decline" in SEEN[0], "the seam ran but could not see the tool it must execute"


def test_a_confirmation_in_chat_executes_the_action(build_flow):
    """T006. The round trip, end to end, through the agent."""
    system = build_flow()
    agent = _agent(system)
    first = agent.invoke({"messages": [HumanMessage(content="decline my morning meetings")]})
    assert RAN == [], "executed without confirmation"

    out = agent.invoke({"messages": [*first["messages"], HumanMessage(content="yes")]})

    assert RAN == [{"meetings": ["Standup", "Review"]}]
    assert any("Done." in getattr(m, "content", "") for m in out["messages"])
    assert not system.store.open_actions(NOW)


def test_a_phrase_outside_the_closed_set_leaves_the_action_open(build_flow):
    """T008. Without this the suite would pass by accepting everything."""
    system = build_flow()
    agent = _agent(system)
    first = agent.invoke({"messages": [HumanMessage(content="decline my morning meetings")]})

    agent.invoke({"messages": [*first["messages"], HumanMessage(content="maybe later on tuesday")]})

    assert RAN == []
    assert len(system.store.open_actions(NOW)) == 1, "an unrecognised reply resolved the action"


def test_the_proposal_turn_is_not_read_as_an_answer_to_itself(build_flow):
    """The turn that PROVOKES a Tier 3 proposal must not be re-read as a
    verdict on the next loop, or every proposal answers itself."""
    system = build_flow()
    agent = _agent(system)
    out = agent.invoke({"messages": [HumanMessage(content="decline my morning meetings")]})

    assert RAN == []
    assert not any("did not recognise" in getattr(m, "content", "") for m in out["messages"])
    assert len(system.store.open_actions(NOW)) == 1
