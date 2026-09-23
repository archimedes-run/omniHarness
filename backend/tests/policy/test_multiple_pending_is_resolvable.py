"""A user with several pending actions must be able to confirm one.

`recognise` refuses an ambiguous confirmation when more than one action is
pending. That is right — guessing which was meant is exactly the interpretation
this design rejects. But the plan text never showed the action id, so the user
was asked to name one they had never been told:

    3 actions are pending and the reply names none of them

with no way forward. The gate was correct and the interface made it unusable,
which is the same outcome as a broken gate.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from app.policy import confirm_flow as cf


def test_the_plan_text_tells_the_user_how_to_name_this_action(build_flow, make_pending):
    system = build_flow()
    action = make_pending(system, targets=["Standup"])
    text = system.middleware._plan_text_for(action)

    assert action.id in text, "the id the user must type is not in the message they read"
    assert f"yes {action.id}" in text


def test_a_bare_yes_with_several_pending_still_refuses(build_flow, make_pending):
    """The ambiguity rule is NOT relaxed. This is the control: if the fix had
    worked by guessing, this would pass silently and the defence would be gone."""
    system = build_flow()
    make_pending(system, targets=["A"])
    make_pending(system, targets=["B"])

    result = system.flow.from_message(HumanMessage(content="yes"), run_tool=system.run_tool)

    assert result.outcome == cf.UNRECOGNISED
    assert "2 actions are pending" in result.message
    assert system.ran == []


def test_naming_the_action_confirms_exactly_that_one(build_flow, make_pending):
    system = build_flow()
    first = make_pending(system, targets=["A"])
    second = make_pending(system, targets=["B"])

    result = system.flow.from_message(HumanMessage(content=f"yes {second.id}"), run_tool=system.run_tool)

    assert result.outcome == cf.EXECUTED
    assert system.ran == [("calendar_decline", {"meetings": ["B"]})]
    assert system.store.get(first.id).outcome is None, "confirming one resolved the other"


def test_naming_the_action_declines_exactly_that_one(build_flow, make_pending):
    system = build_flow()
    first = make_pending(system, targets=["A"])
    second = make_pending(system, targets=["B"])

    result = system.flow.from_message(HumanMessage(content=f"no {first.id}"), run_tool=system.run_tool)

    assert result.outcome == cf.DECLINED
    assert system.ran == []
    assert system.store.get(second.id).outcome is None
