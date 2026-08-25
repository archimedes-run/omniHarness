"""T021/T022 — an expired action TELLS the user (FR-038).

Feature 003's FR-019 required this and `expire_due` was written for it. It had
no production caller: `open_actions` filtered expired actions out at read time,
so nothing displayed wrongly and nothing was ever said either. Silence is
exactly what that requirement forbids.

Expiry happens on read rather than from a background task. See the comment on
`PendingStore.open_actions` for why a lifespan hook was rejected.
"""

from __future__ import annotations

from datetime import timedelta

from langchain_core.messages import HumanMessage

from app.policy import confirm_flow as cf
from app.policy.models import Outcome


def test_reading_resolves_an_expired_action(build_flow, make_pending):
    system = build_flow()
    action = make_pending(system, targets=["Standup"], expires_in=timedelta(seconds=-1))
    assert system.store.get(action.id).outcome is None

    system.store.open_actions(system.now)

    stored = system.store.get(action.id)
    assert stored.outcome == Outcome.EXPIRED
    assert stored.outcome_reason, "an expiry with no reason tells the user nothing"


def test_the_flow_reports_what_expired_so_it_can_be_said(build_flow, make_pending):
    system = build_flow()
    make_pending(system, targets=["Standup"], expires_in=timedelta(seconds=-1))
    result = system.flow.from_message(HumanMessage(content="hello"), run_tool=system.run_tool)
    assert [a.tool_name for a in result.expired_meanwhile] == ["calendar_decline"]


def test_expiry_is_announced_once_not_every_turn(build_flow, make_pending):
    """T022. Resolving is what makes it idempotent: the second reader finds
    nothing to expire, so a user is not told the same thing on every turn."""
    system = build_flow()
    make_pending(system, targets=["Standup"], expires_in=timedelta(seconds=-1))

    first = system.flow.from_message(HumanMessage(content="hello"), run_tool=system.run_tool)
    second = system.flow.from_message(HumanMessage(content="hello again"), run_tool=system.run_tool)

    assert len(first.expired_meanwhile) == 1
    assert second.expired_meanwhile == (), "the same expiry was announced twice"


def test_an_expired_action_cannot_then_be_confirmed(build_flow, make_pending):
    system = build_flow()
    action = make_pending(system, targets=["Standup"], expires_in=timedelta(seconds=-1))
    result = system.flow.explicit(action.id, confirm=True, run_tool=system.run_tool)
    assert result.outcome in {cf.EXPIRED, cf.ALREADY_RESOLVED}
    assert system.ran == []
