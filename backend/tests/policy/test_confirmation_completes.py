"""T001/T002 — a Tier 3 action, proposed and then CONFIRMED, actually happens.

WHAT THIS CATCHES THAT NOTHING ELSE DID. Every other policy test drives the
pieces directly: it constructs a PendingAction, calls `recognise`, calls
`claim`, calls `execute_confirmed`. All of them pass. None of them asks whether
anything in production ever makes those calls, and nothing did — `recognise`,
`open_actions`, `claim` and `execute_confirmed` had test-only callers, so Tier 3
was deny-with-explanation: the assistant stated the plan, recorded the action,
and no code path could ever grant it.

This test speaks to the agent the way a user does — a turn saying "yes" — and
asks whether the thing happened.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool as make_tool

from app.policy.audit import PolicyAuditLog
from app.policy.config import ConfigLoader
from app.policy.disclose import DisclosureLedger
from app.policy.middleware import PolicyMiddleware
from app.policy.models import Outcome
from app.policy.pending import PendingStore

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)

RULES = """
policy:
  rules:
    - pattern: "calendar_decline"
      tier: 3
  confirmation:
    expires_after_seconds: 14400
"""

EXECUTED: list[dict] = []


class ToolCapableFake(GenericFakeChatModel):
    """GenericFakeChatModel raises NotImplementedError from bind_tools, and
    create_agent binds before the graph runs — so a plain fake fails BEFORE
    reaching any policy logic and reports that as the answer (Article XII)."""

    def bind_tools(self, tools, **kwargs):
        return self


@make_tool
def calendar_decline(meetings: list[str]) -> str:
    """Decline the named meetings."""
    EXECUTED.append({"meetings": list(meetings)})
    return f"declined {len(meetings)}"


@pytest.fixture
def system(tmp_path):
    EXECUTED.clear()
    (tmp_path / "policy.yaml").write_text(RULES)
    store = PendingStore(directory=tmp_path / "pending")
    audit = PolicyAuditLog(path=tmp_path / "audit.jsonl", actor="default")
    middleware = PolicyMiddleware(
        loader=ConfigLoader(path=tmp_path / "policy.yaml"),
        pending=store,
        ledger=DisclosureLedger(),
        audit=audit,
        actor="default",
        resolve_targets=lambda name, args: list(args.get("meetings", [])),
        now=lambda: NOW,
    )
    return SimpleNamespace(middleware=middleware, store=store, audit=audit)


def _agent(system):
    model = ToolCapableFake(
        messages=iter(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "calendar_decline",
                            "args": {"meetings": ["Standup 9am", "Review 2pm"]},
                            "id": "tc1",
                        }
                    ],
                ),
                AIMessage(content="Here is the plan."),
                AIMessage(content="Done."),
            ]
        )
    )
    return create_agent(model=model, tools=[calendar_decline], middleware=[system.middleware])


def test_a_confirmed_tier3_action_executes_once_and_is_audited(system):
    """T001. Fails on main with the action still open."""
    agent = _agent(system)
    first = agent.invoke({"messages": [HumanMessage(content="decline my morning meetings")]})

    assert EXECUTED == [], "the action executed WITHOUT confirmation — a worse failure than the one under test"
    pending = system.store.open_actions(NOW)
    assert len(pending) == 1, "no pending action was created; the proposal half is broken, not the grant half"

    # The user says yes, in the ordinary way, in the conversation.
    agent.invoke({"messages": [*first["messages"], HumanMessage(content="yes")]})

    assert EXECUTED == [{"meetings": ["Standup 9am", "Review 2pm"]}], "the user confirmed and nothing happened. Tier 3 is deny-with-explanation: approve, nothing; approve again, nothing; learn to do it by hand instead."
    assert not system.store.open_actions(NOW), "the action is still open after being confirmed"
    entries = system.audit.entries()
    assert len(entries) == 1 and entries[0]["outcome"] == str(Outcome.EXECUTED)


def test_the_proposal_half_works_so_the_failure_localises(system):
    """T002. Without this, 'nothing executed' and 'nothing was proposed' are
    the same red, and the first would be blamed on the wrong half."""
    agent = _agent(system)
    agent.invoke({"messages": [HumanMessage(content="decline my morning meetings")]})

    pending = system.store.open_actions(NOW)
    assert len(pending) == 1
    action = pending[0]
    assert action.tool_name == "calendar_decline"
    assert action.targets == ["Standup 9am", "Review 2pm"]
    assert action.outcome is None
    assert EXECUTED == []
