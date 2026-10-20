"""FR-035: an unrecognised answer restates the plan IN FULL.

`confirm.restate` was written for this and never called (wiring gate). The
flow answered an unrecognised reply with its internal reason ("ambiguous: …"),
so a user who typed "hmm, which ones?" was not shown the plan again and was
left to approve something they could no longer see.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from app.policy import confirm_flow as cf


def test_an_unrecognised_answer_restates_the_plan_and_its_items(build_flow, make_pending):
    system = build_flow()
    action = make_pending(system, targets=["Standup", "1:1 with Sam"])

    result = system.flow.from_message(HumanMessage(content="hmm which ones"), run_tool=system.run_tool)

    assert result.outcome == cf.UNRECOGNISED
    assert "Here is the plan again in full" in result.message
    assert "Standup" in result.message and "1:1 with Sam" in result.message
    assert f"yes {action.id}" in result.message
    assert system.ran == [], "an unrecognised reply ran something"


def test_with_several_pending_and_none_named_each_is_restated_with_its_id(build_flow, make_pending):
    system = build_flow()
    first = make_pending(system, targets=["Standup"])
    second = make_pending(system, targets=["Retro"])

    result = system.flow.from_message(HumanMessage(content="yes"), run_tool=system.run_tool)

    assert result.outcome == cf.UNRECOGNISED
    assert f"yes {first.id}" in result.message and f"yes {second.id}" in result.message
    assert system.ran == []
