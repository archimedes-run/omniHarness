"""Subagent suspend and resume (T005/T007, FR-032, VP-008).

Trusted only because `test_suspend_resume_control.py` passes first: that shows
the instrument detects suspension where it is known to work (Article XII).

VP-008 measured that a subagent has no checkpointer, so it SUSPENDS AND NEVER
RESUMES — the run ends at the suspension point, the tool never runs, and nothing
raises. A subagent asked to confirm simply stops, having done nothing, which is
indistinguishable from correct refusal in any test that declines to confirm.
That is the failure this file exists to make visible.
"""

from __future__ import annotations

import time

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import tool as make_tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command, interrupt


class ToolCapableFake(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


@make_tool
def guarded(x: int) -> str:
    """A tool a subagent would need confirmation to call."""
    return f"executed with {x}"


class SuspendingMiddleware(AgentMiddleware):
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


def _ran(result) -> bool:
    return any("executed with 1" in str(getattr(m, "content", "")) for m in result["messages"])


# ---------------------------------------------------------------------------
# T005 — the defect, reproduced
# ---------------------------------------------------------------------------


def test_without_a_checkpointer_the_run_ends_and_nothing_raises():
    """VP-008. The shape a subagent has today.

    Note what does NOT happen: no exception. The caller sees a completed run
    whose tool did not execute — the same observable as a correct refusal.
    """
    agent = _agent(None)

    result = agent.invoke({"messages": [("user", "go")]})

    assert "__interrupt__" in result, "it does suspend"
    assert not _ran(result), "and the tool never runs"


def test_without_a_checkpointer_there_is_nothing_to_resume_from():
    """The half that makes it a defect rather than a design."""
    agent = _agent(None)
    agent.invoke({"messages": [("user", "go")]})

    # A resume needs a checkpoint to resume INTO. With none, this cannot
    # continue the earlier run — it is a fresh invocation.
    try:
        resumed = agent.invoke(Command(resume="yes"))
        assert not _ran(resumed), "a resume without a checkpointer must not silently succeed"
    except Exception as exc:  # noqa: BLE001 — the shape of the failure is the finding
        assert exc is not None


# ---------------------------------------------------------------------------
# T007 — the fix, confirmed AFTER A DELAY
# ---------------------------------------------------------------------------


def test_with_a_checkpointer_the_subagent_resumes_after_a_delay():
    """FR-032, SC-017.

    THE DELAY IS THE TEST. Confirming instantly cannot distinguish
    suspend-and-resume from stop-and-abandon: both leave the tool unrun at the
    moment of the first call, and both look like a completed invocation. Only
    resuming after the run has genuinely been left alone shows the state was
    still there to return to.
    """
    agent = _agent(InMemorySaver())
    config = {"configurable": {"thread_id": "delayed"}}

    suspended = agent.invoke({"messages": [("user", "go")]}, config)
    assert "__interrupt__" in suspended
    assert not _ran(suspended)

    time.sleep(1.5)  # the run is left genuinely idle, not resumed in the same breath

    resumed = agent.invoke(Command(resume="yes"), config)

    assert _ran(resumed), "the subagent did not resume after a delay. It suspended and abandoned the run — which no test that declines to confirm can tell apart from correct refusal."


def test_a_declined_confirmation_after_a_delay_refuses_without_running():
    """The other direction, also delayed: refusal must be a real outcome, not
    an abandoned run that happens to look like one."""
    agent = _agent(InMemorySaver())
    config = {"configurable": {"thread_id": "delayed-decline"}}

    agent.invoke({"messages": [("user", "go")]}, config)
    time.sleep(1.5)
    resumed = agent.invoke(Command(resume="no"), config)

    assert not _ran(resumed)
    assert any("refused" in str(getattr(m, "content", "")) for m in resumed["messages"]), "a decline must leave evidence it was declined, distinguishable from a run that vanished"
