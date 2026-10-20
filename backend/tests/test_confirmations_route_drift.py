"""POST /api/confirmations/{id}/confirm, through the real router (audit P-3).

The web route passed the action's OWN recorded targets as "current", so the
FR-029 re-check compared the record with itself and drift could never be
detected from the UI. These drive the route the frontend calls, with the
policy layer built by the same `registration.build` the gateway uses.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.routers import confirmations
from app.policy.models import Outcome


@pytest.fixture
def policy(tmp_path, monkeypatch):
    """The gateway's policy layer, on tmp state, and a recording tool runner
    in place of the thread's real tool surface."""
    from app.policy import registration

    app_config = SimpleNamespace(policy=SimpleNamespace(enabled=True, rules_path="", state_dir=str(tmp_path / "policy")))
    monkeypatch.setattr("omniharness.config.get_app_config", lambda: app_config)
    ran: list[tuple[str, dict]] = []

    async def _runner(request, thread_id, user_id):
        return lambda name, args: ran.append((name, args)) or "done"

    monkeypatch.setattr(confirmations, "_runner", _runner)
    middleware = registration.build(app_config)
    app = make_authed_test_app()
    app.include_router(confirmations.router)
    return SimpleNamespace(app=app, middleware=middleware, ran=ran)


def _state_a_plan(middleware, meetings: list[str]):
    """Through the real chokepoint: googlecalendar_decline* is Tier 3 in the shipped rules, so this records a plan. (An UNKNOWN tool is refused outright since 007, and records nothing.)"""
    request = SimpleNamespace(tool_call={"name": "googlecalendar_decline_everything", "args": {"meetings": meetings}, "id": "tc1"}, runtime=None, state={"messages": []})
    middleware.wrap_tool_call(request, lambda r: pytest.fail("a Tier 3 call executed at statement"))
    [action] = middleware.pending.open_actions(middleware.now())
    return action


def test_an_unchanged_plan_confirmed_from_the_ui_executes(policy) -> None:
    """Positive control: the route can say yes."""
    action = _state_a_plan(policy.middleware, ["Standup", "Review"])

    with TestClient(policy.app) as client:
        body = client.post(f"/api/confirmations/{action.id}/confirm", json={}).json()

    assert body["outcome"] == "executed", body
    assert policy.ran == [("googlecalendar_decline_everything", {"meetings": ["Standup", "Review"]})]


def test_a_drifted_plan_confirmed_from_the_ui_is_declined_and_restated(policy) -> None:
    action = _state_a_plan(policy.middleware, ["Standup", "Review"])
    action.arguments = {"meetings": ["Standup"]}  # the record no longer resolves to what was stated
    policy.middleware.pending.save(action)

    with TestClient(policy.app) as client:
        body = client.post(f"/api/confirmations/{action.id}/confirm", json={}).json()

    assert body["outcome"] == "targets_drifted", body
    assert body["detail"]["confirmed"] == ["Standup", "Review"] and body["detail"]["current"] == ["Standup"]
    assert policy.ran == []
    assert policy.middleware.pending.get(action.id).outcome is Outcome.TARGETS_DRIFTED
