"""FR-031, FR-033 — a subagent's Tier 3 call asks the USER.

Delegation grants no authority the delegator did not have. A subagent's tool
calls are classified identically, and a Tier 3 hit suspends the subagent and
asks through the lead agent's conversation.

The confirmation names the requester and the delegation chain, because "should I
delete these four events?" means something different when a subagent the user
never instructed by name is asking.

SC-017 is exercised in test_subagent_suspend.py, which confirms AFTER A DELAY —
an instant confirmation cannot distinguish suspend-and-resume from
stop-and-abandon, and a subagent without a checkpointer does the latter while
looking like a correct refusal.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage

from app.policy.config import ConfigLoader
from app.policy.disclose import DisclosureLedger
from app.policy.middleware import PolicyMiddleware
from app.policy.pending import PendingStore

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
RULES = 'policy:\n  rules:\n    - pattern: "calendar_read"\n      tier: 1\n    - pattern: "calendar_delete"\n      tier: 3\n'


@pytest.fixture
def middleware(tmp_path):
    (tmp_path / "policy.yaml").write_text(RULES)
    return PolicyMiddleware(
        loader=ConfigLoader(path=tmp_path / "policy.yaml"),
        pending=PendingStore(directory=tmp_path / "pending"),
        ledger=DisclosureLedger(),
        resolve_targets=lambda n, a: list(a.get("ids", [])),
        now=lambda: NOW,
    )


def _request(name, context, args=None):
    return SimpleNamespace(
        tool_call={"name": name, "args": args or {}, "id": "tc1", "type": "tool_call"},
        tool=SimpleNamespace(name=name),
        state={"messages": [HumanMessage(content="tidy my calendar")]},
        runtime=SimpleNamespace(context=context),
    )


SUBAGENT = {"thread_id": "t1", "agent_name": "calendar-tidier", "delegation_chain": ["lead_agent", "calendar-tidier"]}
LEAD = {"thread_id": "t1"}


def test_a_subagents_tier3_call_is_classified_identically(middleware):
    """Delegation is not a way around the gate."""
    ran = []

    middleware.wrap_tool_call(_request("calendar_delete", SUBAGENT, {"ids": ["Standup"]}), lambda r: ran.append(r) or "deleted")

    assert not ran, "a subagent executed a Tier 3 action without confirmation"
    assert len(middleware.pending.open_actions(NOW)) == 1


def test_a_subagents_tier1_call_still_runs_silently(middleware):
    """The gate must not make delegation useless."""
    ran = []

    middleware.wrap_tool_call(_request("calendar_read", SUBAGENT), lambda r: ran.append(r) or "events")

    assert ran


def test_the_prompt_names_the_requester(middleware):
    """FR-033. The user is authorising an action by something they did not ask
    for by name."""
    plan = middleware.wrap_tool_call(_request("calendar_delete", SUBAGENT, {"ids": ["Standup"]}), lambda r: "deleted")

    assert "calendar-tidier" in plan
    assert "subagent" in plan.lower()


def test_the_prompt_names_the_delegation_chain(middleware):
    plan = middleware.wrap_tool_call(_request("calendar_delete", SUBAGENT, {"ids": ["Standup"]}), lambda r: "deleted")

    assert "lead_agent -> calendar-tidier" in plan


def test_the_lead_agents_own_prompt_does_not_mention_delegation(middleware):
    """The discriminator — otherwise every prompt would carry the wording and
    the subagent tests would pass vacuously."""
    plan = middleware.wrap_tool_call(_request("calendar_delete", LEAD, {"ids": ["Standup"]}), lambda r: "deleted")

    assert "subagent" not in plan.lower()
    assert "->" not in plan


def test_the_requester_is_recorded_on_the_pending_action(middleware):
    """So the audit entry can carry it too."""
    middleware.wrap_tool_call(_request("calendar_delete", SUBAGENT, {"ids": ["Standup"]}), lambda r: "deleted")

    action = middleware.pending.open_actions(NOW)[0]

    assert action.requester == "calendar-tidier"
    assert action.delegation_chain == ("lead_agent", "calendar-tidier")


def test_the_user_confirms_a_subagents_action_not_the_subagent(middleware):
    """The confirmation comes from a real user turn on the lead conversation.

    A subagent cannot answer its own question — it is not a user turn, and it
    has no way to produce one.
    """
    from app.policy.confirm import Verdict, recognise

    middleware.wrap_tool_call(_request("calendar_delete", SUBAGENT, {"ids": ["Standup"]}), lambda r: "deleted")
    pending = middleware.pending.open_actions(NOW)

    assert recognise(HumanMessage(content=f"yes {pending[0].id}"), pending, runtime_context=LEAD).verdict is Verdict.CONFIRM
