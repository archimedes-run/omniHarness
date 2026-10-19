"""Inbox alerts: what the engine tried to tell the user (Phase 2.5).

Audit entries are written by the engine's own AuditLog, then read through the
real router.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.trigger_engine.audit import AuditLog
from app.trigger_engine.models import Firing, Outcome, TriggerEvent, TriggerType

NOW = datetime.now(UTC)


def _firing(rule: str, event: str, outcome: Outcome, reason: str = "") -> Firing:
    f = Firing(rule_id=rule, event=TriggerEvent(type=TriggerType.CRON, event_id=event, at=NOW), prompt="p", thread_id=f"thread-{rule}")
    return f.resolve(outcome, reason)


@pytest.fixture
def client(tmp_path):
    from app.gateway.routers import inbox

    log = AuditLog(path=tmp_path / "audit.jsonl", actor="default")
    app = make_authed_test_app()
    app.state.config = SimpleNamespace(trigger_engine=SimpleNamespace(enabled=True, state_dir=str(tmp_path), actor="default"))
    app.include_router(inbox.router)
    return SimpleNamespace(log=log, client=TestClient(app), app=app)


def _alerts(client) -> dict:
    resp = client.client.get("/api/inbox/alerts")
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_each_firing_reads_by_its_latest_outcome_and_only_waiting_or_missed_count(client) -> None:
    client.log.record(_firing("morning", "e1", Outcome.QUEUED, "quiet hours"), NOW - timedelta(minutes=30))
    client.log.record(_firing("morning", "e1", Outcome.DELIVERED), NOW - timedelta(minutes=5))  # later: delivered
    client.log.record(_firing("blocked", "s1", Outcome.QUEUED, "awaiting the coalescing window"), NOW - timedelta(minutes=1))
    client.log.record(_firing("weekly", "w1", Outcome.EXPIRED, "held past 2h"), NOW - timedelta(hours=3))
    client.log.record(_firing("drift", "d1", Outcome.SUPPRESSED, "no longer true"), NOW - timedelta(hours=1))

    body = _alerts(client)
    states = {(a["rule_id"], a["event_id"]): a["state"] for a in body["alerts"]}

    assert states == {("morning", "e1"): "delivered", ("blocked", "s1"): "waiting", ("weekly", "w1"): "not-delivered", ("drift", "d1"): "suppressed"}
    assert body["waiting_count"] == 2, "only what is waiting or was missed may count toward the badge"
    assert next(a for a in body["alerts"] if a["rule_id"] == "weekly")["reason"] == "held past 2h", "reasons are verbatim"
    assert body["alerts"][0]["rule_id"] == "blocked", "newest first"


def test_old_history_drops_out_but_a_held_firing_never_does(client) -> None:
    client.log.record(_firing("old", "o1", Outcome.DELIVERED), NOW - timedelta(days=3))
    client.log.record(_firing("oldfail", "f1", Outcome.FAILED, "telegram 502"), NOW - timedelta(days=3))
    client.log.record(_firing("held", "h1", Outcome.QUEUED, "quiet hours"), NOW - timedelta(days=3))

    body = _alerts(client)

    assert [(a["rule_id"], a["state"]) for a in body["alerts"]] == [("held", "waiting")]
    assert body["waiting_count"] == 1


def test_a_disabled_engine_has_no_alerts(client) -> None:
    client.app.state.config.trigger_engine.enabled = False
    assert _alerts(client) == {"alerts": [], "waiting_count": 0}


def test_the_gateway_serves_the_route() -> None:
    from app.gateway.app import create_app

    assert "/api/inbox/alerts" in {getattr(r, "path", None) for r in create_app().routes}
