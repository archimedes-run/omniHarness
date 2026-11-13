"""FR-058a: in a run resumed after a confirmation, a call identical (tool +
canonical arguments) to one the person DECLINED in the same turn is refused,
and only then. Deterministic: the pending store and the turn key are fakes.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.policy.middleware import PolicyMiddleware
from omniharness.agents.called_agents import RESUME_ACTION_KEY

TURN = "turn-1"


def _middleware(declined: list) -> PolicyMiddleware:
    mw = PolicyMiddleware.__new__(PolicyMiddleware)
    mw.pending = SimpleNamespace(declined_in_thread=lambda thread_id, owner: list(declined))
    mw._private_read = lambda request, ruleset=None: SimpleNamespace(turn_key=TURN)
    return mw


def _request(args: dict, *, resumed: bool = True, tool: str = "ledger_apply"):
    context = {"thread_id": "t1", "user_id": "u1"}
    if resumed:
        context[RESUME_ACTION_KEY] = {"ids": ["a1"]}
    return SimpleNamespace(tool_call={"name": tool, "args": args, "id": "c9"}, runtime=SimpleNamespace(context=context), tool=None)


def _declined(args: dict, *, group_key: str = TURN, tool: str = "ledger_apply"):
    return SimpleNamespace(id="a1", tool_name=tool, group_key=group_key, arguments=args)


ARGS = {"plan": {"project": "Kitchen", "tasks": ["quotes"]}}


def _refused(result) -> bool:
    return result is not None and PolicyMiddleware.DECLINED_REPEAT_TEXT in str(getattr(result, "content", result))


def test_the_same_call_in_the_same_turn_is_refused():
    mw = _middleware([_declined(ARGS)])
    # Key order does not make it a different call.
    assert _refused(mw._declined_this_turn(_request({"plan": {"tasks": ["quotes"], "project": "Kitchen"}})))


@pytest.mark.parametrize(
    "case",
    ["other_arguments", "other_turn", "other_tool", "not_resumed"],
)
def test_anything_else_is_not_refused(case):
    declined = _declined(ARGS, group_key="turn-0" if case == "other_turn" else TURN)
    mw = _middleware([declined])
    request = _request(
        {"plan": {"project": "Kitchen", "tasks": ["tiles"]}} if case == "other_arguments" else ARGS,
        resumed=case != "not_resumed",
        tool="ledger_read" if case == "other_tool" else "ledger_apply",
    )
    assert mw._declined_this_turn(request) is None
