"""T090e/T090f — a rules change supersedes what it no longer needs to ask (FR-042, SC-025).

The occasion (ROADMAP-FOLLOWUPS, 2026-09-23): read-only email calls were Tier 3
under rules that did not match the connector's names; the rules were fixed, and
the pending actions became permanently un-confirmable, blocking every
confirmation for four hours. `Outcome.SUPERSEDED` existed and had no producer.

Driven through `registration.build` — the policy layer exactly as the gateway
builds it — and, for the reload, through the real confirmations router.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.routers import confirmations
from app.policy import registration
from app.policy.models import Outcome

TOOL = "gmail_fetch_emails"
RULES_TIER_3 = f'policy:\n  rules:\n    - pattern: "{TOOL}"\n      tier: 3\n'
RULES_TIER_1 = f'policy:\n  rules:\n    - pattern: "{TOOL}"\n      tier: 1\n'


@pytest.fixture
def policy(tmp_path, monkeypatch):
    rules = tmp_path / "rules.yaml"
    rules.write_text(RULES_TIER_3)
    app_config = SimpleNamespace(policy=SimpleNamespace(enabled=True, rules_path=str(rules), state_dir=str(tmp_path / "state")))
    monkeypatch.setattr("omniharness.config.get_app_config", lambda: app_config)
    ran: list[str] = []

    async def _runner(request, thread_id, user_id):
        return lambda name, args: ran.append(name) or "ran"

    monkeypatch.setattr(confirmations, "_runner", _runner)
    middleware = registration.build(app_config)
    app = make_authed_test_app()
    app.include_router(confirmations.router)
    return SimpleNamespace(rules=rules, app_config=app_config, middleware=middleware, app=app, ran=ran)


def _state_a_plan(middleware, call_id="tc1"):
    request = SimpleNamespace(tool_call={"name": TOOL, "args": {"max_results": 5}, "id": call_id}, runtime=None, state={"messages": []})
    middleware.wrap_tool_call(request, lambda r: pytest.fail("a Tier 3 call ran at statement"))
    return middleware.pending.open_actions(middleware.now())


def _list(app) -> list[dict]:
    with TestClient(app) as client:
        return client.get("/api/confirmations").json()["actions"]


def test_unchanged_rules_leave_a_pending_action_pending(policy) -> None:
    """Negative control: the sweep is not simply resolving everything."""
    [action] = _state_a_plan(policy.middleware)

    assert [a["id"] for a in _list(policy.app)] == [action.id]
    assert policy.middleware.pending.get(action.id).outcome is None


def test_a_rules_change_supersedes_and_does_not_run(policy) -> None:
    [action] = _state_a_plan(policy.middleware)

    policy.rules.write_text(RULES_TIER_1)  # the fix: reading mail is Tier 1
    listed = _list(policy.app)  # the next read of the pending set, as the UI does it

    assert listed == [], "an action the rules no longer require confirmation for is still pending"
    resolved = policy.middleware.pending.get(action.id)
    assert resolved.outcome is Outcome.SUPERSEDED
    assert "Tier 1" in resolved.outcome_reason and "NOT run" in resolved.outcome_reason, resolved.outcome_reason
    assert policy.ran == [], "superseding ran the tool"
    assert policy.middleware.audit.entries() == [], "a superseded action was recorded as a Tier 3 execution"


def test_superseding_unblocks_the_next_confirmation(policy) -> None:
    """The cost the follow-up recorded: with orphans pending, a bare 'yes'
    could not be matched to anything. After the sweep, it can."""
    from langchain_core.messages import HumanMessage

    from app.policy.confirm_flow import EXECUTED, ConfirmationFlow

    _state_a_plan(policy.middleware, "tc1")
    _state_a_plan(policy.middleware, "tc2")
    policy.rules.write_text(RULES_TIER_1)
    _list(policy.app)
    policy.rules.write_text(RULES_TIER_3 + '    - pattern: "calendar_decline"\n      tier: 3\n')
    request = SimpleNamespace(tool_call={"name": "calendar_decline", "args": {"meetings": ["Standup"]}, "id": "tc3"}, runtime=None, state={"messages": [HumanMessage(content="decline my standup")]})
    policy.middleware.wrap_tool_call(request, lambda r: pytest.fail("ran at statement"))

    flow = ConfirmationFlow(store=policy.middleware.pending, middleware=policy.middleware, now=policy.middleware.now)
    result = flow.from_message(HumanMessage(content="yes"), run_tool=lambda name, args: policy.ran.append(name) or "done")

    assert result.outcome == EXECUTED, result
    assert policy.ran == ["calendar_decline"]
