"""T004 — every one of the seven outcomes, from the one implementation.

Seven distinct outcomes exist so that a user is never told "that didn't work"
when the truth is "someone else already confirmed it", "it expired", or "the
items changed". Each of those needs a different response from the person
reading it, and collapsing them is how a user retries something that will never
succeed.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from langchain_core.messages import HumanMessage

from app.policy import confirm_flow as cf
from app.policy.models import Outcome


@pytest.fixture
def system(build_flow):
    return build_flow()


def test_executed(system, make_pending):
    action = make_pending(system, targets=["Standup", "Review"])
    result = system.flow.from_message(HumanMessage(content="yes"), run_tool=system.run_tool)
    assert result.outcome == cf.EXECUTED
    assert system.ran == [("calendar_decline", {"meetings": ["Standup", "Review"]})]
    assert system.store.get(action.id).outcome == Outcome.EXECUTED


def test_declined(system, make_pending):
    action = make_pending(system, targets=["Standup"])
    result = system.flow.from_message(HumanMessage(content="no"), run_tool=system.run_tool)
    assert result.outcome == cf.DECLINED
    assert system.ran == [], "a decline must not run the tool"
    assert system.store.get(action.id).outcome == Outcome.DECLINED


def test_already_resolved_names_the_prior_outcome(system, make_pending):
    """The losing side of a race is told WHAT happened, not that it failed."""
    action = make_pending(system, targets=["Standup"])
    system.flow.from_message(HumanMessage(content="yes"), run_tool=system.run_tool)
    again = system.flow.explicit(action.id, confirm=True, run_tool=system.run_tool)
    assert again.outcome == cf.ALREADY_RESOLVED
    assert "executed" in again.message
    assert len(system.ran) == 1, "the action executed twice"


def test_expired(system, make_pending):
    action = make_pending(system, targets=["Standup"], expires_in=timedelta(seconds=-1))
    result = system.flow.explicit(action.id, confirm=True, run_tool=system.run_tool)
    assert result.outcome in {cf.EXPIRED, cf.ALREADY_RESOLVED}
    assert system.ran == []


def test_targets_drifted(system, make_pending):
    make_pending(system, targets=["Standup", "Review"])
    result = system.flow.from_message(HumanMessage(content="yes"), run_tool=system.run_tool, current_targets=["Standup"])
    assert result.outcome == cf.TARGETS_DRIFTED
    assert system.ran == [], "drifted targets must not execute"
    assert result.detail["confirmed"] == ["Standup", "Review"]


def test_unrecognised_leaves_the_action_open(system, make_pending):
    action = make_pending(system, targets=["Standup"])
    result = system.flow.from_message(HumanMessage(content="maybe tomorrow"), run_tool=system.run_tool)
    assert result.outcome == cf.UNRECOGNISED
    assert system.store.get(action.id).outcome is None
    assert system.ran == []


def test_an_ordinary_sentence_produces_no_verdict(system, make_pending):
    """The common case. A turn about something else must not be judged."""
    make_pending(system, targets=["Standup"])
    result = system.flow.from_message(
        HumanMessage(content="what does the calendar look like next week for the platform team"),
        run_tool=system.run_tool,
    )
    assert result.outcome == cf.NO_VERDICT


def test_threshold_not_met(build_flow, make_pending):
    system = build_flow(threshold=2)
    action = make_pending(system, targets=["a", "b", "c"])
    result = system.flow.from_message(HumanMessage(content="yes"), run_tool=system.run_tool)
    assert result.outcome == cf.THRESHOLD_NOT_MET
    assert system.ran == []
    assert system.store.get(action.id).outcome is None, "a wrong count must not resolve the action"
    assert system.store.get(action.id).claimed_by is None, "a wrong count must not claim the action"
