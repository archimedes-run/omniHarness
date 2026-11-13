"""The Tier 2 disclosure is on the reply the person actually gets (spec 009
review, H1 and H2).

H1: since Slice 0 the checklist gate (TodoMiddleware) can send a finished
reply back. The disclosure used to be appended to that FIRST reply and the
ledger cleared, so the reply channels and scheduled runs deliver (the one after
the bounce) carried none.

H2: the trailing-offer removal (VerificationMiddleware) could delete the
sentence in which the model disclosed the action itself, which the policy
layer had counted as covering it. The notice is now always the server's line,
appended after every rewrite.

These drive a real agent with the middlewares in the lead's order: the policy
layer first (its after_model runs last), then the verification and checklist
middlewares.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool as make_tool

from app.channels.manager import _extract_response_text
from app.policy.config import ConfigLoader
from app.policy.disclose import DisclosureLedger
from app.policy.middleware import PolicyMiddleware
from app.trigger_engine.injector import _reply_text
from omniharness.agents.middlewares.verification_middleware import VerificationMiddleware
from omniharness.agents.turns import DISCLOSURE_MARKER

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
RULES = """
policy:
  rules:
    - pattern: "calendar_create_hold"
      tier: 2
    - pattern: "write_todos"
      tier: 1
  confirmation:
    expires_after_seconds: 14400
"""


class ToolCapableFake(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


@make_tool
def calendar_create_hold(title: str) -> str:
    """Create a tentative hold."""
    return f"held {title}"


@pytest.fixture
def policy(tmp_path):
    (tmp_path / "policy.yaml").write_text(RULES)
    return PolicyMiddleware(
        loader=ConfigLoader(path=tmp_path / "policy.yaml"),
        pending=SimpleNamespace(save=lambda a: a, open_actions=lambda now: [], get=lambda i: None, expire_due=lambda now: [], declined_in_thread=lambda *a, **k: []),
        ledger=DisclosureLedger(),
        actor="default",
        now=lambda: NOW,
    )


def _todo_middleware():
    from omniharness.agents.lead_agent.agent import _create_todo_list_middleware

    return _create_todo_list_middleware()


HOLD = {"name": "calendar_create_hold", "args": {"title": "Lunch"}, "id": "tc1"}


def _run(policy, replies: list[AIMessage], *, todos: list[dict] | None = None):
    model = ToolCapableFake(messages=iter([AIMessage(content="", tool_calls=[HOLD]), *replies]))
    # The lead's order: policy (runtime middlewares) before verification and the checklist.
    agent = create_agent(model=model, tools=[calendar_create_hold], middleware=[policy, VerificationMiddleware(), _todo_middleware()])
    state = {"messages": [HumanMessage(content="put lunch on my calendar and plan the week")]}
    if todos is not None:
        state["todos"] = todos
    return agent.invoke(state)


def _dicts(out) -> list[dict]:
    return [m.model_dump() for m in out["messages"]]


TODOS = [
    {"content": "Done when: lunch is on the calendar and the week is planned", "status": "completed"},
    {"content": "Hold lunch", "status": "completed"},
    {"content": "Plan the week", "status": "in_progress"},
]


def test_after_a_checklist_bounce_the_delivered_reply_carries_the_disclosure(policy):
    out = _run(policy, [AIMessage(content="Lunch is held."), AIMessage(content="Lunch is held.\n\nNot verified:\n- Plan the week: not started")], todos=TODOS)
    messages = out["messages"]
    assert any(getattr(m, "name", None) == "todo_completion_reminder" for m in messages), "the checklist gate did not send the reply back"
    for delivered in (_extract_response_text(_dicts(out)), _reply_text({"messages": _dicts(out)})):
        assert delivered.endswith("Ran without asking: calendar_create_hold"), f"the delivered reply lost the notice: {delivered!r}"
    # The web chat shows ONE note: only the final reply is marked.
    marked = [m for m in messages if isinstance(m, AIMessage) and DISCLOSURE_MARKER in (m.additional_kwargs or {})]
    assert len(marked) == 1 and marked[0] is [m for m in messages if isinstance(m, AIMessage)][-1]


def test_a_model_written_disclosure_inside_a_removed_offer_leaves_the_server_notice(policy):
    body = "Lunch is on your calendar for Friday at noon, held as tentative so you can still move it. " * 3
    out = _run(policy, [AIMessage(content=body.strip() + "\n\nI used calendar_create_hold for Lunch. Would you like me to add a reminder too?")])
    final = [m for m in out["messages"] if isinstance(m, AIMessage)][-1]
    text = str(final.content)
    assert "Would you like me to" not in text, "the trailing offer was not removed"
    assert text.endswith("Ran without asking: calendar_create_hold"), f"no server notice on the final reply: {text!r}"


def test_a_reply_with_no_tier2_action_has_no_notice(policy):
    model = ToolCapableFake(messages=iter([AIMessage(content="Nothing to change.")]))
    agent = create_agent(model=model, tools=[calendar_create_hold], middleware=[policy, VerificationMiddleware(), _todo_middleware()])
    out = agent.invoke({"messages": [HumanMessage(content="anything on friday?")]})
    final = [m for m in out["messages"] if isinstance(m, AIMessage)][-1]
    assert "Ran without asking" not in str(final.content)
    assert DISCLOSURE_MARKER not in (final.additional_kwargs or {})


@make_tool
def calendar_create_hold_failing(title: str) -> str:
    """Create a tentative hold (always fails)."""
    raise RuntimeError("the calendar refused the hold")


def test_a_tier2_call_that_did_not_run_is_not_listed(policy, tmp_path):
    (tmp_path / "policy.yaml").write_text(RULES.replace('"calendar_create_hold"', '"calendar_create_hold_failing"'))
    from omniharness.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware

    failing = PolicyMiddleware(loader=ConfigLoader(path=tmp_path / "policy.yaml"), pending=policy.pending, ledger=DisclosureLedger(), actor="default", now=lambda: NOW)
    call = {"name": "calendar_create_hold_failing", "args": {"title": "Lunch"}, "id": "tc1"}
    model = ToolCapableFake(messages=iter([AIMessage(content="", tool_calls=[call]), AIMessage(content="The hold failed.")]))
    # The error handler sits inside the policy layer, as in the lead's chain.
    agent = create_agent(model=model, tools=[calendar_create_hold_failing], middleware=[failing, ToolErrorHandlingMiddleware()])
    out = agent.invoke({"messages": [HumanMessage(content="hold lunch")]})
    final = [m for m in out["messages"] if isinstance(m, AIMessage)][-1]
    assert "Ran without asking" not in str(final.content), "a call that failed was listed as ran"


def test_control_no_bounce_one_notice(policy):
    out = _run(policy, [AIMessage(content="Lunch is held.")])
    final = [m for m in out["messages"] if isinstance(m, AIMessage)][-1]
    assert str(final.content) == "Lunch is held.\n\nRan without asking: calendar_create_hold"


# -- exactly once: specialists roll up onto the lead's reply; grants (owner) --

from omniharness.agents.turns import DELEGATED_DISCLOSURE_MARKER  # noqa: E402


def _specialist_result(call_id: str, items: list[dict], agent: str = "Repo analyst"):
    from langchain_core.messages import ToolMessage

    return ToolMessage(content="Task Succeeded. Result: done", tool_call_id=call_id, name="task", additional_kwargs={DELEGATED_DISCLOSURE_MARKER: {"agent": agent, "items": items}})


def _lead_turn(policy, *, own: bool, delegated_ids: list[str], earlier_marker_ids: list[str] = ()):
    from types import SimpleNamespace

    from omniharness.agents.turns import USER_TURN_MARKER

    messages = [HumanMessage(content="go", additional_kwargs={USER_TURN_MARKER: True})]
    if earlier_marker_ids:
        messages.append(AIMessage(content="first reply", additional_kwargs={DISCLOSURE_MARKER: {"text": "x", "items": [], "sources": list(earlier_marker_ids)}}))
    for call_id in delegated_ids:
        messages += [AIMessage(content="", tool_calls=[{"name": "task", "args": {}, "id": call_id}]), _specialist_result(call_id, [{"tool": "ledger_apply"}, {"tool": "ledger_apply"}])]
    if own:
        policy.ledger.record("code_job", {}, "ok")
    messages.append(AIMessage(content="Here is the result."))
    out = policy.after_model({"messages": messages}, SimpleNamespace(context={"thread_id": "t1"}))
    return str(out["messages"][0].content) if out else "Here is the result."


def test_a_specialists_actions_roll_up_onto_the_leads_reply_in_one_line(policy):
    text = _lead_turn(policy, own=True, delegated_ids=["d1"])
    assert text.endswith("Ran without asking: code_job, ledger_apply ×2 (via Repo analyst)"), text
    assert text.count("Ran without asking") == 1


def test_a_specialists_actions_already_disclosed_in_the_turn_are_not_repeated(policy):
    text = _lead_turn(policy, own=False, delegated_ids=["d1"], earlier_marker_ids=["d1"])
    assert "Ran without asking" not in text, "disclosed twice across a resume"


def test_the_specialists_own_reply_carries_no_notice(policy):
    from types import SimpleNamespace

    from omniharness.agents.invitation import DELEGATION_CHAIN_KEY, INVITED_ORIGIN_KEY

    policy.ledger.record("ledger_apply", {}, "ok")
    final = AIMessage(content="Specialist done.")
    out = policy.after_model({"messages": [HumanMessage(content="brief"), final]}, SimpleNamespace(context={INVITED_ORIGIN_KEY: "user", DELEGATION_CHAIN_KEY: ["lead_agent", "Repo analyst"]}))
    message = out["messages"][0]
    assert str(message.content) == "Specialist done.", "the specialist's result carries its own notice"
    assert [i["tool"] for i in message.additional_kwargs[DELEGATED_DISCLOSURE_MARKER]] == ["ledger_apply"]


def test_grant_actions_are_their_own_line():
    from app.policy.disclose import DisclosureLedger

    ledger = DisclosureLedger()
    ledger.record("ledger_apply", {}, None, grant=True)
    ledger.record("ledger_apply", {}, None, grant=True)
    text = ledger.apply("Morning brief sent.")
    assert text.endswith("Ran under grant: ledger_apply ×2")
    assert text.count("Ran under grant") == 1 and "Ran without asking" not in text
