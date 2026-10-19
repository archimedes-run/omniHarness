"""T070-T073 — the policy inspector (Feature 004 US4: FR-025..FR-029, SC-011, SC-012).

Through the real router, over the policy layer as the gateway builds it.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.routers import policy as policy_router
from app.policy import registration

RULES = """policy:
  rules:
    - pattern: "gmail_fetch_*"
      tier: 1
    - pattern: "calendar_delete_event"
      tier: 3
"""


@pytest.fixture
def inspector(tmp_path, monkeypatch):
    rules = tmp_path / "rules.yaml"
    rules.write_text(RULES)
    app_config = SimpleNamespace(policy=SimpleNamespace(enabled=True, rules_path=str(rules), state_dir=str(tmp_path / "state")))
    monkeypatch.setattr("omniharness.config.get_app_config", lambda: app_config)
    app = make_authed_test_app()
    app.include_router(policy_router.router)
    return SimpleNamespace(rules=rules, app_config=app_config, client=TestClient(app))


def _explain(client, tool, args=None) -> dict:
    resp = client.get("/api/policy/explain", params={"tool": tool, "args": json.dumps(args or {})})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_explain_runs_nothing_and_records_nothing(inspector) -> None:
    """FR-025, SC-011: no pending action, no audit entry, for a Tier 3 tool."""
    body = _explain(inspector.client, "calendar_delete_event", {"event_id": "e1"})

    assert body["tier"] == 3
    middleware = registration.build(inspector.app_config)
    assert middleware.pending.open_actions(middleware.now()) == [], "explaining a Tier 3 call stated a plan"
    assert middleware.audit.entries() == []


def test_explain_uses_the_classify_live_dispatch_uses() -> None:
    """FR-025: the same function object, not a parallel implementation."""
    import app.policy.explain as explain_module
    import app.policy.middleware as middleware_module

    assert explain_module.classify is middleware_module.classify


def test_the_default_is_marked_apart_from_an_explicit_tier_3(inspector) -> None:
    """FR-026, FR-027, SC-012."""
    explicit = _explain(inspector.client, "calendar_delete_event")
    default = _explain(inspector.client, "some_tool_nobody_classified")

    assert explicit["tier"] == default["tier"] == 3
    assert explicit["from_default"] is False and "calendar_delete_event" in explicit["deciding_rule"]
    assert default["from_default"] is True and default["deciding_rule"] is None


def test_a_refused_edit_leaves_the_previous_rules_in_force_for_everyone(inspector) -> None:
    """FR-029, T073 — forced bad reload. The inspector shows the LAST GOOD rules,
    says the edit was refused and why, and a NEW agent built after the edit
    enforces those rules too (it used to fall to Tier 3 for everything)."""
    before = inspector.client.get("/api/policy/rules").json()
    assert [r["pattern"] for r in before["rules"]] == ["gmail_fetch_*", "calendar_delete_event"]

    inspector.rules.write_text("policy:\n  rules:\n    - pattern: [this is not valid\n")
    after = inspector.client.get("/api/policy/rules").json()

    assert after["kept_previous"] is True and after["error"], after
    assert [r["pattern"] for r in after["rules"]] == ["gmail_fetch_*", "calendar_delete_event"]
    assert _explain(inspector.client, "gmail_fetch_emails")["tier"] == 1, "the inspector stopped describing the rules in force"
    new_agent = registration.build(inspector.app_config)
    assert new_agent.loader.load().unreadable is False, "a new agent after a refused edit lost the rules in force"


def test_recent_tier3_executions_show_plan_actor_and_authoriser(inspector) -> None:
    """FR-028, written by the real audit writer."""
    from datetime import UTC, datetime, timedelta

    from app.policy.audit import PolicyAuditLog
    from app.policy.models import Outcome, PendingAction, Tier

    action = PendingAction(plan_text="I will delete 1 event: Standup", tool_name="calendar_delete_event", arguments={"event_id": "e1"}, targets=["Standup"], tier_at_statement=Tier.TIER_3, expires_at=datetime.now(UTC) + timedelta(hours=1))
    action.claimed_by = "worker-1"
    action.resolve(Outcome.EXECUTED)
    PolicyAuditLog(path=inspector.rules.parent / "state" / "audit.jsonl", actor="default").record_tier3(action)

    [row] = inspector.client.get("/api/policy/audit").json()

    assert row["plan_as_stated"] == "I will delete 1 event: Standup"
    assert row["actor"] == "default" and row["authorised_by"] == "worker-1"


def test_the_gateway_serves_the_routes() -> None:
    from app.gateway.app import create_app

    paths = {getattr(r, "path", None) for r in create_app().routes}
    assert {"/api/policy/rules", "/api/policy/explain", "/api/policy/audit"} <= paths
