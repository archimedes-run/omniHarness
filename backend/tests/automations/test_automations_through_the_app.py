"""Feature 006 Automations panel, through create_app() and its lifespan.

Create from scratch, edit a trigger, read the next run, quiet hours and the
worded run history: each through the routers production mounts, against a real
rule file, with the engine's own loader to show the result is what it runs.
"""

from __future__ import annotations

import json
from datetime import datetime

from app.gateway.trigger_engine_wiring import SUPPORTED_SOURCE_TYPES
from app.trigger_engine.config import ConfigLoader


def _view(gw) -> dict:
    resp = gw.client.get("/api/triggers/rules")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _engine(gw):
    return {r.id: r for r in ConfigLoader(path=gw.rules, supported_types=SUPPORTED_SOURCE_TYPES).load().rules}


def test_a_new_automation_from_scratch_is_created_and_listed(make_gateway) -> None:
    gw = make_gateway()
    view = _view(gw)
    blank = {
        "id": "standup-nudge",
        "name": "Standup nudge",
        "type": "cron",
        "enabled": True,
        "match": {"schedule": "55 9 * * 1-5", "timezone": "Europe/London"},
        "prompt": "Standup in five minutes ({scheduled_at}).",
        "destination": "remote",
        "urgent": False,
    }

    resp = gw.client.post("/api/automations/rules", json={"rule": blank, "version": view["version"]})

    assert resp.status_code == 201, resp.text
    listed = {r["id"]: r for r in _view(gw)["rules"]}
    assert listed["standup-nudge"]["name"] == "Standup nudge" and listed["standup-nudge"]["destination"] == "remote"
    assert _engine(gw)["standup-nudge"].match["schedule"] == "55 9 * * 1-5", "the engine would not run what was saved"
    assert json.loads(gw.rules.read_text())["quiet_hours"]["end"] == "07:00", "the rest of the file changed"


def test_an_invalid_new_automation_is_refused_with_the_engines_reason(make_gateway) -> None:
    gw = make_gateway()
    before = gw.rules.read_bytes()
    bad = {"id": "x", "name": "X", "type": "watcher", "enabled": True, "match": {"event": "idle"}, "prompt": "It is {scheduled_at}", "destination": "auto"}

    resp = gw.client.post("/api/automations/rules", json={"rule": bad, "version": _view(gw)["version"]})

    assert resp.status_code == 422 and "cannot supply" in resp.json()["detail"], resp.text
    assert gw.rules.read_bytes() == before


def test_editing_a_trigger_is_saved_and_versioned(make_gateway) -> None:
    gw = make_gateway()
    view = _view(gw)
    rule = next(r for r in view["rules"] if r["id"] == "morning-brief")
    edited = {k: rule[k] for k in ("id", "name", "type", "enabled", "match", "prompt", "destination", "urgent")}
    edited["match"] = {"schedule": "0 7 * * 1-5", "timezone": "America/Chicago"}

    resp = gw.client.put("/api/automations/rules/morning-brief", json={"rule": edited, "version": view["version"]})

    assert resp.status_code == 200, resp.text
    after = _view(gw)
    assert after["version"] == resp.json()["version"] != view["version"]
    assert next(r for r in after["rules"] if r["id"] == "morning-brief")["match"]["schedule"] == "0 7 * * 1-5"
    assert _engine(gw)["morning-brief"].match["timezone"] == "America/Chicago"
    # The page's old version is now stale: a second write from it is refused.
    stale = gw.client.put("/api/automations/rules/morning-brief", json={"rule": edited, "version": view["version"]})
    assert stale.status_code == 409


def test_the_rules_view_has_quiet_hours_and_next_run(make_gateway) -> None:
    gw = make_gateway(engine_enabled=True)
    view = _view(gw)
    assert view["quiet_hours"] == {"enabled": True, "start": "22:00", "end": "07:00", "timezone": "America/New_York"}
    rules = {r["id"]: r for r in view["rules"]}
    brief = rules["morning-brief"]
    assert brief["next_run"] == "scheduled"
    due = datetime.fromisoformat(brief["next_run_at"])
    assert (due.hour, due.minute) == (8, 45) and due.weekday() < 5
    assert rules["blocked-session"]["next_run"] == "on-event"


def test_with_the_engine_off_there_is_no_next_run(make_gateway) -> None:
    gw = make_gateway(engine_enabled=False)
    assert {r["next_run"] for r in _view(gw)["rules"]} == {"engine-off"}


def test_the_run_history_is_worded_from_the_audit_log(make_gateway) -> None:
    def row(event_id, at, outcome, reason="", batch=None, rule="morning-brief"):
        return {"actor": "default", "at": at, "rule_id": rule, "event_type": "cron", "event_id": event_id, "thread_id": "thread-9", "outcome": outcome, "reason": reason, "batch_id": batch, "delivered_chars": 5}

    audit = [
        row("2026-10-20T08:45:00-04:00", "2026-10-20T12:46:00+00:00", "delivered"),
        row("2026-10-16T08:45:00-04:00", "2026-10-16T12:45:00+00:00", "queued", "user is mid-exchange on the target thread"),
        row("2026-10-16T08:45:00-04:00", "2026-10-16T13:02:00+00:00", "delivered"),
        row("2026-10-15T08:45:00-04:00", "2026-10-15T12:46:00+00:00", "delivered", batch="b1"),
        row("s1", "2026-10-15T12:46:00+00:00", "delivered", batch="b1", rule="blocked-session"),
        row("2026-10-14T08:45:00-04:00", "2026-10-14T12:50:00+00:00", "failed", "gave up after 3 attempts: model timeout"),
    ]
    gw = make_gateway(audit=audit)

    resp = gw.client.get("/api/triggers/rules/morning-brief/runs")

    assert resp.status_code == 200, resp.text
    runs = resp.json()["runs"]
    assert [r["kind"] for r in runs] == ["delivered", "held-then-delivered", "delivered-with-others", "failed"]
    assert runs[1]["held_because"] == "mid-conversation" and runs[1]["settled_at"] == "2026-10-16T13:02:00+00:00"
    assert runs[2]["delivered_with"] == [{"rule_id": "blocked-session", "event_id": "s1"}]
    assert runs[3]["reason"] == "gave up after 3 attempts: model timeout"
    assert runs[0]["thread_id"] == "thread-9"


def test_the_reads_need_a_signed_in_user(make_gateway) -> None:
    gw = make_gateway()
    gw.client.cookies.clear()
    assert gw.client.get("/api/triggers/rules/morning-brief/runs").status_code == 401


def test_a_next_run_inside_quiet_hours_says_when_it_will_be_delivered(make_gateway) -> None:
    gw = make_gateway(engine_enabled=True)
    view = _view(gw)
    rule = next(r for r in view["rules"] if r["id"] == "morning-brief")
    edited = {k: rule[k] for k in ("id", "name", "type", "enabled", "match", "prompt", "destination", "urgent")}
    edited["match"] = {"schedule": "30 5 * * *", "timezone": "America/New_York"}
    assert gw.client.put("/api/automations/rules/morning-brief", json={"rule": edited, "version": view["version"]}).status_code == 200

    brief = next(r for r in _view(gw)["rules"] if r["id"] == "morning-brief")

    assert brief["held_for_quiet_hours"] is True
    due, deliver = datetime.fromisoformat(brief["next_run_at"]), datetime.fromisoformat(brief["deliver_at"])
    assert (due.hour, due.minute) == (5, 30) and (deliver.hour, deliver.minute) == (7, 0)
    assert brief["timezone"] == "America/New_York"


def test_each_run_links_to_its_full_content_in_the_run_history(make_gateway) -> None:
    audit = [
        {"actor": "default", "at": "2026-10-20T12:46:00+00:00", "rule_id": "morning-brief", "event_type": "cron", "event_id": "2026-10-20T08:45:00-04:00", "thread_id": "t", "outcome": "delivered", "reason": "", "batch_id": None},
        {"actor": "default", "at": "2026-10-19T12:46:00+00:00", "rule_id": "morning-brief", "event_type": "cron", "event_id": "2026-10-19T08:45:00-04:00", "thread_id": "t", "outcome": "delivered", "reason": "", "batch_id": None},
    ]
    gw = make_gateway(audit=audit)
    history = gw.client.app.state.run_history
    run_id = history.record(kind="automation", source_id="morning-brief", event_id="2026-10-20T08:45:00-04:00", body={"prompt": "Brief me", "reply": "Here it is"}, status="completed")

    runs = gw.client.get("/api/triggers/rules/morning-brief/runs").json()["runs"]

    assert [(r["run_id"], r["content"]) for r in runs] == [(run_id, "stored"), (None, "not-stored")]
    detail = gw.client.get(f"/api/run-history/runs/{run_id}").json()
    assert detail["body"] == {"prompt": "Brief me", "reply": "Here it is"}
