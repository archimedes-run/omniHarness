"""T011-T013 — the scope threshold, on EVERY route (FR-009).

WHY THIS FILE EXISTS AT ALL, AND IN PHASE 1. FR-009 originally sat under the
spec heading "Functional Requirements — Pending confirmations (Surface 1)". The
content was right; the LOCATION scoped it. Read literally, the threshold was a
browser rule, and this phase would have shipped standalone as a route where
"yes" grants sixty targets while a UI two phases later demanded proof of
reading. A defence that depends on which route the user takes is not a defence.

So the threshold lives in `confirm_flow`, and T013 below is the assertion that
the chat route is held to it.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage

from app.policy import confirm_flow as cf


def test_below_the_threshold_a_bare_affirmation_confirms(build_flow, make_pending):
    system = build_flow(threshold=10)
    make_pending(system, targets=["a", "b"])
    result = system.flow.from_message(HumanMessage(content="yes"), run_tool=system.run_tool)
    assert result.outcome == cf.EXECUTED


def test_above_the_threshold_a_bare_affirmation_does_not(build_flow, make_pending):
    """T013. The chat route, refusing a click-through equivalent."""
    system = build_flow(threshold=2)
    action = make_pending(system, targets=["a", "b", "c"])
    result = system.flow.from_message(HumanMessage(content="yes"), run_tool=system.run_tool)

    assert result.outcome == cf.THRESHOLD_NOT_MET
    assert system.ran == []
    assert "3" in result.message, "the message must tell the user what to type"
    stored = system.store.get(action.id)
    assert stored.outcome is None and stored.claimed_by is None


def test_above_the_threshold_the_correct_count_confirms(build_flow, make_pending):
    system = build_flow(threshold=2)
    make_pending(system, targets=["a", "b", "c"])
    result = system.flow.from_message(HumanMessage(content="yes 3"), run_tool=system.run_tool)
    assert result.outcome == cf.EXECUTED
    assert system.ran == [("calendar_decline", {"meetings": ["a", "b", "c"]})]


@pytest.mark.parametrize("reply", ["yes 2", "yes 4", "yes 30"])
def test_a_wrong_count_neither_confirms_nor_resolves(build_flow, make_pending, reply):
    system = build_flow(threshold=2)
    action = make_pending(system, targets=["a", "b", "c"])
    result = system.flow.from_message(HumanMessage(content=reply), run_tool=system.run_tool)

    assert result.outcome == cf.THRESHOLD_NOT_MET
    assert system.ran == []
    stored = system.store.get(action.id)
    assert stored.outcome is None, "a wrong count destroyed the action the user is still trying to approve"


def test_the_count_alone_is_not_an_affirmation(build_flow, make_pending):
    """The number is the scope proof, not the verdict. Stripping it must leave
    an exact member of the closed set behind, and a bare number leaves nothing."""
    system = build_flow(threshold=2)
    result = system.flow.from_message(HumanMessage(content="3"), run_tool=system.run_tool)
    make_pending(system, targets=["a", "b", "c"])
    assert result.outcome in {cf.NO_VERDICT, cf.UNRECOGNISED}
    assert system.ran == []


def test_declining_is_never_blocked_by_the_threshold(build_flow, make_pending):
    """Proof of reading is required to ACT, not to refuse. Making a decline
    harder than a confirmation would push users toward the dangerous answer."""
    system = build_flow(threshold=2)
    action = make_pending(system, targets=["a", "b", "c"])
    result = system.flow.from_message(HumanMessage(content="no"), run_tool=system.run_tool)
    assert result.outcome == cf.DECLINED
    assert system.store.get(action.id).outcome is not None


def test_the_threshold_is_read_from_configuration(build_flow, make_pending):
    """SC-019. Same action, different config, different demand."""
    lenient = build_flow(threshold=10)
    make_pending(lenient, targets=["a", "b", "c"])
    assert lenient.flow.from_message(HumanMessage(content="yes"), run_tool=lenient.run_tool).outcome == cf.EXECUTED

    strict = build_flow(threshold=2)
    make_pending(strict, targets=["a", "b", "c"])
    assert strict.flow.from_message(HumanMessage(content="yes"), run_tool=strict.run_tool).outcome == cf.THRESHOLD_NOT_MET


def test_the_default_is_ten(tmp_path):
    """The number a reader sees. Labelled a guess where it is defined."""
    from app.policy.config import RuleSet

    assert RuleSet().threshold_targets == 10
