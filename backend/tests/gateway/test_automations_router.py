"""Automations: the one write path for trigger rules (Phase 2.5).

Through the real routers (triggers to read, automations to write), against a
real rule file, with the engine's own ConfigLoader to show the change is what
the engine will run.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.trigger_engine_wiring import SUPPORTED_SOURCE_TYPES
from app.trigger_engine.config import ConfigLoader

DOC = {
    "_comment": ["kept as written"],
    "quiet_hours": {"start": "22:00", "end": "07:30", "timezone": "America/New_York", "enabled": True},
    "rules": [
        {"id": "morning-briefing", "type": "cron", "enabled": True, "match": {"schedule": "45 8 * * 1-5", "timezone": "America/New_York"}, "prompt": "Brief me as of {scheduled_at}.", "destination": "auto"},
        {"id": "blocked-session", "type": "watcher", "enabled": True, "match": {"event": "waiting-on-user"}, "prompt": "{project} is waiting: {last_message}", "destination": "auto"},
    ],
}


@pytest.fixture
def env(tmp_path):
    from app.gateway.routers import automations, triggers

    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps(DOC, indent=2))
    rules.chmod(0o644)
    app = make_authed_test_app()
    app.state.config = SimpleNamespace(trigger_engine=SimpleNamespace(enabled=True, rules_path=str(rules), state_dir=str(tmp_path / "state"), actor="default"))
    app.include_router(triggers.router)
    app.include_router(automations.router)
    return SimpleNamespace(rules=rules, client=TestClient(app), app=app)


def _read(env) -> dict:
    body = env.client.get("/api/triggers/rules").json()
    assert body["writable"] is True and body["version"], body
    return body


def _engine_rules(env):
    return {r.id: r for r in ConfigLoader(path=env.rules, supported_types=SUPPORTED_SOURCE_TYPES).load().rules}


def test_the_read_view_carries_what_the_edit_form_needs(env) -> None:
    rule = next(r for r in _read(env)["rules"] if r["id"] == "morning-briefing")
    assert rule["prompt"] == "Brief me as of {scheduled_at}." and rule["destination"] == "auto"


def test_a_toggle_is_written_and_the_engine_reloads_it(env) -> None:
    engine = ConfigLoader(path=env.rules, supported_types=SUPPORTED_SOURCE_TYPES)
    assert {r.id: r.enabled for r in engine.load().rules}["morning-briefing"] is True
    version = _read(env)["version"]

    resp = env.client.patch("/api/automations/rules/morning-briefing/enabled", json={"enabled": False, "version": version})

    assert resp.status_code == 200, resp.text
    assert resp.json()["version"] != version
    assert {r.id: r.enabled for r in engine.load().rules}["morning-briefing"] is False, "the running engine's loader did not pick the change up"


def test_an_edit_keeps_everything_else_in_the_file(env) -> None:
    version = _read(env)["version"]
    edited = {**DOC["rules"][0], "match": {"schedule": "30 9 * * 1-5", "timezone": "Europe/London"}, "prompt": "Morning, it is {scheduled_at}."}

    resp = env.client.put("/api/automations/rules/morning-briefing", json={"rule": edited, "version": version})

    assert resp.status_code == 200, resp.text
    doc = json.loads(env.rules.read_text())
    assert doc["quiet_hours"] == DOC["quiet_hours"] and doc["_comment"] == DOC["_comment"]
    assert [r["id"] for r in doc["rules"]] == ["morning-briefing", "blocked-session"], "order or other rules changed"
    assert _engine_rules(env)["morning-briefing"].match["schedule"] == "30 9 * * 1-5"
    assert env.rules.stat().st_mode & 0o777 == 0o644, "the file's permissions changed"
    assert [p.name for p in env.rules.parent.iterdir() if p.name.endswith(".tmp")] == [], "a temp file was left behind"


@pytest.mark.parametrize(
    "change,expect",
    [
        ({"match": {"schedule": "61 25 * * *", "timezone": "America/New_York"}}, "not a valid cron expression"),
        ({"match": {"schedule": "0 9 * * *", "timezone": "Mars/Olympus"}}, "not an IANA time zone"),
        ({"prompt": "Brief me about {project}."}, "cannot supply"),
        ({"destination": "carrier-pigeon"}, "unknown destination"),
        ({"type": "completion"}, ""),
    ],
)
def test_an_invalid_edit_is_refused_with_the_reason_and_changes_nothing(env, change, expect) -> None:
    before = env.rules.read_bytes()
    version = _read(env)["version"]

    resp = env.client.put("/api/automations/rules/morning-briefing", json={"rule": {**DOC["rules"][0], **change}, "version": version})

    assert resp.status_code == 422, resp.text
    assert expect in resp.json()["detail"], resp.json()
    assert env.rules.read_bytes() == before, "an invalid edit reached the file"
    assert _read(env)["rules_error"] is None, "the rules in force were disturbed"


def test_an_edit_based_on_a_stale_version_is_refused(env) -> None:
    version = _read(env)["version"]
    env.rules.write_text(env.rules.read_text().replace("Brief me", "Hand-edited: brief me"))  # edited elsewhere meanwhile
    before = env.rules.read_bytes()

    resp = env.client.patch("/api/automations/rules/blocked-session/enabled", json={"enabled": False, "version": version})

    assert resp.status_code == 409 and "changed since" in resp.json()["detail"]
    assert env.rules.read_bytes() == before, "the hand edit was overwritten"


def test_the_shipped_defaults_are_not_edited_in_place(env) -> None:
    from app.gateway.trigger_engine_wiring import DEFAULT_RULES

    env.app.state.config.trigger_engine.rules_path = ""
    before = DEFAULT_RULES.read_bytes()
    body = env.client.get("/api/triggers/rules").json()
    assert body["writable"] is False and "rules_path" in body["not_writable_reason"]

    resp = env.client.patch(f"/api/automations/rules/{body['rules'][0]['id']}/enabled", json={"enabled": True, "version": body["version"]})

    assert resp.status_code == 409 and "rules_path" in resp.json()["detail"]
    assert DEFAULT_RULES.read_bytes() == before


def test_every_template_creates_a_valid_rule_and_a_duplicate_id_is_refused(env) -> None:
    templates = env.client.get("/api/automations/templates").json()
    assert {t["template"] for t in templates} == {"morning-brief", "blocked-session", "weekly-review"}
    for t in templates:
        rule = {**t["rule"], "id": f"from-{t['template']}"}
        resp = env.client.post("/api/automations/rules", json={"rule": rule, "version": _read(env)["version"]})
        assert resp.status_code == 201, (t["template"], resp.text)
    assert {"from-morning-brief", "from-blocked-session", "from-weekly-review"} <= set(_engine_rules(env))

    dup = env.client.post("/api/automations/rules", json={"rule": {**templates[0]["rule"], "id": "morning-briefing"}, "version": _read(env)["version"]})
    assert dup.status_code == 409


def test_delete_removes_the_rule_and_an_id_cannot_be_changed(env) -> None:
    renamed = env.client.put("/api/automations/rules/blocked-session", json={"rule": {**DOC["rules"][1], "id": "other"}, "version": _read(env)["version"]})
    assert renamed.status_code == 422 and "id cannot be changed" in renamed.json()["detail"]

    resp = env.client.delete("/api/automations/rules/blocked-session", params={"version": _read(env)["version"]})

    assert resp.status_code == 200, resp.text
    assert "blocked-session" not in _engine_rules(env)


def test_the_gateway_serves_the_routes() -> None:
    from app.gateway.app import create_app

    paths = {getattr(r, "path", None) for r in create_app().routes}
    assert {"/api/automations/rules", "/api/automations/rules/{rule_id}", "/api/automations/rules/{rule_id}/enabled", "/api/automations/templates"} <= paths
