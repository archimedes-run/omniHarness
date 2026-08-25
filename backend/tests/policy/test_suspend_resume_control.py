"""POSITIVE CONTROL for the subagent suspend/resume spike (T004, Article XII).

Before trusting a report that the SUBAGENT cannot suspend and resume, the
instrument must be seen detecting suspension where it is known to work.

The lead agent has a checkpointer attached at run time by the run worker, so it
is the known-positive case. If this test fails, the harness is wrong and any
negative result from the subagent test means nothing — which is exactly what
happened the first time this was probed: the measurement failed on a missing
`bind_tools` in the stand-in model and would have reported "this runtime cannot
suspend at all", a wrong finding of far larger scope.
"""

from __future__ import annotations

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import tool as make_tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command, interrupt


class ToolCapableFake(GenericFakeChatModel):
    """A fake that can be bound to tools.

    GenericFakeChatModel raises NotImplementedError from bind_tools, and
    create_agent binds tools before the graph runs — so a probe using the plain
    fake fails BEFORE reaching any suspension logic, and reports that failure as
    if it were the answer. This class is the fix for that, and the reason
    Article XII exists.
    """

    def bind_tools(self, tools, **kwargs):
        return self


@make_tool
def guarded(x: int) -> str:
    """A tool a policy layer would classify Tier 3."""
    return f"executed with {x}"


class SuspendingMiddleware(AgentMiddleware):
    """Stands in for the policy layer: suspends at the chokepoint."""

    def wrap_tool_call(self, request, handler):
        decision = interrupt({"ask": "confirm?"})
        if decision != "yes":
            return "refused"
        return handler(request)


def _agent(checkpointer):
    model = ToolCapableFake(
        messages=iter(
            [
                AIMessage(content="", tool_calls=[{"name": "guarded", "args": {"x": 1}, "id": "tc1"}]),
                AIMessage(content="done"),
            ]
        )
    )
    return create_agent(model=model, tools=[guarded], middleware=[SuspendingMiddleware()], checkpointer=checkpointer)


def test_the_known_positive_case_suspends():
    """With a checkpointer — the lead agent's shape — the run suspends."""
    agent = _agent(InMemorySaver())
    config = {"configurable": {"thread_id": "control-1"}}

    result = agent.invoke({"messages": [("user", "go")]}, config)

    assert "__interrupt__" in result, "the control did not suspend. The harness is wrong, and any negative result from the subagent probe is meaningless until this passes."


def test_the_known_positive_case_resumes_and_the_tool_runs():
    """And resumes, with the tool actually executing afterwards."""
    agent = _agent(InMemorySaver())
    config = {"configurable": {"thread_id": "control-2"}}

    agent.invoke({"messages": [("user", "go")]}, config)
    resumed = agent.invoke(Command(resume="yes"), config)

    assert any("executed with 1" in str(getattr(m, "content", "")) for m in resumed["messages"]), "the control suspended but the tool never ran on resume"


def test_the_control_can_also_refuse():
    """Refusal must be expressible, since that is what Tier 3 does on decline."""
    agent = _agent(InMemorySaver())
    config = {"configurable": {"thread_id": "control-3"}}

    agent.invoke({"messages": [("user", "go")]}, config)
    resumed = agent.invoke(Command(resume="no"), config)

    assert not any("executed with 1" in str(getattr(m, "content", "")) for m in resumed["messages"])


@pytest.mark.parametrize("bad_probe", [GenericFakeChatModel])
def test_the_plain_fake_would_have_produced_a_false_negative(bad_probe):
    """Pins the trap itself.

    A probe built on the plain fake fails before reaching suspension. Recording
    it here means the next person to write one of these sees why the wrapper
    exists rather than removing it as ceremony.
    """
    model = bad_probe(messages=iter([AIMessage(content="", tool_calls=[{"name": "guarded", "args": {"x": 1}, "id": "tc1"}])]))
    agent = create_agent(model=model, tools=[guarded], middleware=[SuspendingMiddleware()], checkpointer=InMemorySaver())

    with pytest.raises(NotImplementedError):
        agent.invoke({"messages": [("user", "go")]}, {"configurable": {"thread_id": "trap"}})
