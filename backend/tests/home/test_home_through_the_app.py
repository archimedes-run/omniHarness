"""Home's own routes, through `create_app()` and its lifespan (Feature 006).

The dismissal repository, the inbox route that counts the New chat badge and
the Home reads are the ones startup wires. If startup stopped registering the
repository, or the inbox stopped reading it, these fail.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from functools import partial
from types import SimpleNamespace

import pytest

from app.trigger_engine.audit import AuditLog
from app.trigger_engine.models import Firing, Outcome, TriggerEvent, TriggerType

NOW = datetime.now(UTC)


def _firing(rule: str, event: str, outcome: Outcome, reason: str = "") -> Firing:
    f = Firing(rule_id=rule, event=TriggerEvent(type=TriggerType.CRON, event_id=event, at=NOW), prompt="p", thread_id=f"thread-{rule}")
    return f.resolve(outcome, reason)


@pytest.fixture
def engine(gateway, monkeypatch):
    """The trigger engine's files, read by the routes as the engine writes them.

    The engine itself stays off at startup (it would contend for leadership and
    run); the routes read its config at request time, so it is pointed at a
    temporary state dir and rule file once the app is up.
    """
    state = gateway.tmp / "engine"
    state.mkdir()
    rules = gateway.tmp / "rules.json"
    rules.write_text(
        json.dumps(
            {
                "rules": [
                    {"id": "morning-briefing", "type": "cron", "match": {"schedule": "45 8 * * *", "timezone": "America/New_York"}, "prompt": "Brief me on today", "destination": "auto"},
                    {"id": "weekly-review", "type": "cron", "match": {"schedule": "0 17 * * 5"}, "prompt": "Weekly review", "destination": "auto"},
                    {"id": "switched-off", "type": "cron", "enabled": False, "match": {"schedule": "* * * * *"}, "prompt": "never", "destination": "auto"},
                ]
            }
        )
    )
    monkeypatch.setattr(gateway.app.state.config, "trigger_engine", SimpleNamespace(enabled=True, state_dir=str(state), actor="default", rules_path=str(rules)))
    return SimpleNamespace(log=AuditLog(path=state / "audit.jsonl", actor="default"), rules=rules)


def test_a_dismissed_alert_leaves_the_badge_count_and_stays_dismissed(gateway, engine) -> None:
    engine.log.record(_firing("weekly", "w1", Outcome.EXPIRED, "held past 2h"), NOW - timedelta(hours=1))
    engine.log.record(_firing("blocked", "s1", Outcome.QUEUED, "quiet hours"), NOW - timedelta(minutes=1))
    before = gateway.client.get("/api/inbox/alerts").json()
    assert before["waiting_count"] == 2 and before["dismissals_readable"] is True

    resp = gateway.client.post("/api/home/dismissals", json={"kind": "alert", "keys": ["weekly:w1"]})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"alert_keys": ["weekly:w1"], "name_prompt_dismissed": False}

    after = gateway.client.get("/api/inbox/alerts").json()
    assert after["waiting_count"] == 1, "a dismissed alert must not count toward the New chat badge"
    flags = {a["rule_id"]: a["dismissed"] for a in after["alerts"]}
    assert flags == {"weekly": True, "blocked": False}, "still listed, marked dismissed"
    # On the server: a second read (another device) sees the same.
    assert gateway.client.get("/api/home/dismissals").json()["alert_keys"] == ["weekly:w1"]
    # Idempotent.
    gateway.client.post("/api/home/dismissals", json={"kind": "alert", "keys": ["weekly:w1"]})
    assert gateway.client.get("/api/inbox/alerts").json()["waiting_count"] == 1


def test_dismissals_are_per_user(gateway, engine) -> None:
    engine.log.record(_firing("weekly", "w1", Outcome.EXPIRED, "held"), NOW - timedelta(hours=1))
    repo = gateway.app.state.home_dismissal_repo
    gateway.client.portal.call(partial(repo.dismiss, user_id="someone-else", kind="alert", keys=["weekly:w1"]))
    gateway.client.portal.call(partial(repo.dismiss, user_id="someone-else", kind="name-prompt", keys=["name-prompt"]))

    assert gateway.client.get("/api/home/dismissals").json() == {"alert_keys": [], "name_prompt_dismissed": False}
    assert gateway.client.get("/api/inbox/alerts").json()["waiting_count"] == 1


def test_not_now_on_the_name_prompt_is_remembered(gateway) -> None:
    assert gateway.client.get("/api/home/dismissals").json()["name_prompt_dismissed"] is False
    resp = gateway.client.post("/api/home/dismissals", json={"kind": "name-prompt"})
    assert resp.status_code == 200, resp.text
    assert gateway.client.get("/api/home/dismissals").json()["name_prompt_dismissed"] is True


def test_bad_dismissals_are_refused(gateway) -> None:
    assert gateway.client.post("/api/home/dismissals", json={"kind": "alert", "keys": []}).status_code == 422
    assert gateway.client.post("/api/home/dismissals", json={"kind": "alert", "keys": ["x" * 257]}).status_code == 422
    assert gateway.client.post("/api/home/dismissals", json={"kind": "other", "keys": ["a"]}).status_code == 422


def test_upcoming_lists_the_next_run_of_each_enabled_cron_rule(gateway, engine) -> None:
    body = gateway.client.get("/api/home/upcoming").json()
    assert body["engine_enabled"] is True and body["rules_error"] is None
    assert body["calendar"] == {"state": "not-set-up", "detail": None, "events": []}, "no Google Calendar connection"
    ids = [r["rule_id"] for r in body["runs"]]
    assert sorted(ids) == ["morning-briefing", "weekly-review"], "a disabled rule has no next run"
    times = [datetime.fromisoformat(r["at"]) for r in body["runs"]]
    assert times == sorted(times), "soonest first"
    morning = next(r for r in body["runs"] if r["rule_id"] == "morning-briefing")
    at = datetime.fromisoformat(morning["at"])
    assert (at.hour, at.minute) == (8, 45) and morning["timezone"] == "America/New_York", "computed in the rule's own zone"
    assert at > NOW and morning["title"] == "Morning briefing"


def test_upcoming_with_the_engine_off_says_so(gateway) -> None:
    body = gateway.client.get("/api/home/upcoming").json()
    assert (body["engine_enabled"], body["rules_error"], body["runs"]) == (False, None, [])


def test_upcoming_with_an_unreadable_rule_file_is_cant_tell(gateway, engine) -> None:
    engine.rules.write_text("{not json")
    body = gateway.client.get("/api/home/upcoming").json()
    assert body["rules_error"] and body["runs"] == []


def test_today_lists_ledger_changes_and_deliveries_since_the_start_of_the_day(gateway, engine) -> None:
    project = gateway.client.post("/api/ledger/projects", json={"name": "OmniHarness"}).json()
    task = gateway.client.post(f"/api/ledger/projects/{project['id']}/tasks", json={"title": "Ship Home"}).json()
    gateway.client.patch(f"/api/ledger/tasks/{task['id']}", json={"version": task["version"], "status": "done"})
    engine.log.record(_firing("morning-briefing", "m1", Outcome.DELIVERED), NOW - timedelta(minutes=5))
    engine.log.record(_firing("yesterday", "y1", Outcome.DELIVERED), NOW - timedelta(hours=20))

    since = (NOW - timedelta(hours=2)).isoformat()
    body = gateway.client.get("/api/home/today", params={"since": since}).json()
    texts = [i["text"] for i in body["items"]]
    assert "Project “OmniHarness” created" in texts
    assert "Task added to OmniHarness: Ship Home" in texts
    assert "Task done in OmniHarness: Ship Home" in texts
    assert "Morning briefing delivered" in texts
    assert "Yesterday delivered" not in texts, "before the start of the day"
    assert {i["by"] for i in body["items"] if i["source"] == "ledger"} == {"you"}
    assert body["sources"] == {"ledger": "ok", "automations": "ok", "sessions": "not-set-up", "github": "not-set-up"}
    assert {i["known"] for i in body["items"]} == {"observed"}, "the ledger and the engine recorded these here"

    later = gateway.client.get("/api/home/today", params={"since": (NOW + timedelta(hours=1)).isoformat()}).json()
    assert later["items"] == [] and later["sources"]["ledger"] == "ok", "empty, and read"


def test_today_with_the_engine_off_says_automations_are_off(gateway) -> None:
    body = gateway.client.get("/api/home/today", params={"since": NOW.isoformat()}).json()
    assert (body["sources"]["ledger"], body["sources"]["automations"]) == ("ok", "off")


def test_today_needs_an_offset(gateway) -> None:
    assert gateway.client.get("/api/home/today", params={"since": "2026-10-20T00:00:00"}).status_code == 422


def test_project_summaries_carry_the_next_due_date(gateway) -> None:
    project = gateway.client.post("/api/ledger/projects", json={"name": "HackMIT"}).json()
    gateway.client.post(f"/api/ledger/projects/{project['id']}/tasks", json={"title": "b", "due_date": "2026-10-30"})
    gateway.client.post(f"/api/ledger/projects/{project['id']}/tasks", json={"title": "a", "due_date": "2026-10-23"})
    summary = next(p for p in gateway.client.get("/api/ledger/projects").json() if p["id"] == project["id"])
    assert summary["next_due"] == "2026-10-23"
