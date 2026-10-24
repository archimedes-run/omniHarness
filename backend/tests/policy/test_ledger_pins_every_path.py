"""A pin (app.ledger.service.PIN_KEY) is the server's: whatever tier a
ledger_apply call gets, it runs without any pin its model wrote."""

from __future__ import annotations

from types import SimpleNamespace

from langgraph.prebuilt.tool_node import ToolCallRequest

from app.policy.models import Tier


def test_a_model_pin_is_stripped_on_the_tier_1_path(monkeypatch) -> None:
    from app.policy.middleware import PolicyMiddleware
    from omniharness.tools.builtins.ledger_tool import ledger_apply_tool

    middleware = PolicyMiddleware.__new__(PolicyMiddleware)
    monkeypatch.setattr(PolicyMiddleware, "_classify", lambda self, request: SimpleNamespace(refused=False, tier=Tier.TIER_1, tool_name="ledger_apply"))
    monkeypatch.setattr(PolicyMiddleware, "_inviting_for", lambda self, request: None)
    seen = {}

    def handler(request):
        seen["changes"] = request.tool_call["args"]["changes"]
        return "ran"

    call = {"name": "ledger_apply", "args": {"changes": [{"op": "update_task", "task": "T-1", "status": "done", "_pin": {"task_id": "elsewhere"}}]}, "id": "c1"}
    request = ToolCallRequest(tool_call=call, tool=ledger_apply_tool, state={}, runtime=None)
    assert middleware.wrap_tool_call(request, handler) == "ran"
    assert seen["changes"] == [{"op": "update_task", "task": "T-1", "status": "done"}]
