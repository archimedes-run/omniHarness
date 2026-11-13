"""Spec 010 Slice 1: automations in the versioned config store (FR-020 to FR-023).

Through create_app() and its lifespan (the make_gateway fixture), against a
real rule file, reading back both the rules file and the per-rule histories:
the state a call produces, not only its status.

  * every write through the Automations page or Studio's schedules is a
    version of each rule it changed (kind "automation");
  * the first write records every existing rule as a baseline (source
    "existing"), and a hand edit of the rules file is recorded as a new
    baseline before the next write: nothing on disk is lost or rewritten;
  * undo restores as a NEW version; undo of a create writes a deleted version;
  * a stale rule version is refused, also between two concurrent writers;
  * the engine reads identical rules before and after the migration.
"""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import pytest

from app.gateway.automations_store import history_dir
from app.gateway.trigger_engine_wiring import SUPPORTED_SOURCE_TYPES
from app.trigger_engine.config import ConfigLoader
from omniharness.config import config_versions


def _view(gw) -> dict:
    resp = gw.client.get("/api/triggers/rules")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _versions(gw, rule_id: str) -> dict:
    resp = gw.client.get(f"/api/automations/rules/{rule_id}/versions")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _file_rules(gw) -> dict:
    return {r["id"]: r for r in json.loads(gw.rules.read_text())["rules"]}


def _history(gw) -> SimpleNamespace:
    return SimpleNamespace(dir=history_dir(SimpleNamespace(state_dir=str(gw.state))))


def _records(gw, rule_id: str) -> list[dict]:
    path = config_versions._automation_file(_history(gw).dir, rule_id)
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _engine(path):
    return list(ConfigLoader(path=path, supported_types=SUPPORTED_SOURCE_TYPES).load().rules)


def _edit(gw, rule_id: str, **fields) -> dict:
    rule = {**_file_rules(gw)[rule_id], **fields}
    resp = gw.client.put(f"/api/automations/rules/{rule_id}", json={"rule": rule, "version": _view(gw)["version"]})
    assert resp.status_code == 200, resp.text
    return rule


def test_first_write_records_every_rule_as_a_baseline_then_undo_restores_as_a_new_version(make_gateway) -> None:
    gw = make_gateway()
    original = _file_rules(gw)
    # Before any write: no history, reading records nothing (current 1 is the
    # baseline the next write will record).
    assert not _history(gw).dir.exists() or not list(_history(gw).dir.glob("*.jsonl"))
    before = _versions(gw, "morning-brief")
    assert (before["current"], before["unrecorded"], before["versions"]) == (1, True, [])

    _edit(gw, "morning-brief", prompt="Shorter, as of {scheduled_at}.")

    brief = _versions(gw, "morning-brief")
    assert brief["current"] == 2 and not brief["unrecorded"]
    assert [(v["version"], v["source"], v["via"]) for v in brief["versions"]] == [(2, "manual", "page"), (1, "existing", "")]
    assert brief["versions"][0]["changed"] == ["prompt"] and brief["versions"][0]["who"].startswith("user:")
    # Every existing rule got its baseline on that first write (FR-023), the
    # untouched one included, exactly as it is in the file.
    assert _records(gw, "morning-brief")[0]["snapshot"] == original["morning-brief"]
    assert [(r["version"], r["source"], r["snapshot"]) for r in _records(gw, "blocked-session")] == [(1, "existing", original["blocked-session"])]

    written = _records(gw, "morning-brief")
    resp = gw.client.post("/api/automations/rules/morning-brief/undo", json={"to_version": 1, "base_version": 2})

    assert resp.status_code == 200, resp.text
    assert resp.json()["current"] == 3 and resp.json()["versions"][0]["source"] == "undo"
    assert _file_rules(gw)["morning-brief"] == original["morning-brief"], "undo did not restore the rule in the file"
    assert _records(gw, "morning-brief")[:2] == written, "undo rewrote history instead of adding a version"
    assert {r.id: r.prompt for r in _engine(gw.rules)}["morning-brief"] == original["morning-brief"]["prompt"]


def test_undo_of_a_create_writes_a_deleted_version_and_can_itself_be_undone(make_gateway) -> None:
    gw = make_gateway()
    rule = {"id": "standup", "name": "Standup", "type": "cron", "enabled": True, "match": {"schedule": "55 9 * * 1-5", "timezone": "UTC"}, "prompt": "Standup ({scheduled_at}).", "destination": "auto"}
    assert gw.client.post("/api/automations/rules", json={"rule": rule, "version": _view(gw)["version"]}).status_code == 201
    made = _versions(gw, "standup")
    assert made["can_undo_create"] and [(v["version"], v["changed"]) for v in made["versions"]] == [(1, ["created"])]

    resp = gw.client.post("/api/automations/rules/standup/undo", json={"to_version": 0, "base_version": 1})

    assert resp.status_code == 200, resp.text
    gone = resp.json()
    assert gone["exists"] is False and gone["current"] == 2 and gone["versions"][0]["deleted"] is True
    assert "standup" not in _file_rules(gw) and "standup" not in {r.id for r in _engine(gw.rules)}, "the schedule it created still runs"
    # Undo the undo: the rule comes back, as version 3.
    back = gw.client.post("/api/automations/rules/standup/undo", json={"to_version": 1, "base_version": 2})
    assert back.status_code == 200, back.text
    assert _file_rules(gw)["standup"] == rule and back.json()["current"] == 3


def test_a_rule_from_an_existing_file_cannot_be_undone_to_before_it_existed(make_gateway) -> None:
    gw = make_gateway()
    _edit(gw, "morning-brief", prompt="Edited {scheduled_at}.")
    assert _versions(gw, "morning-brief")["can_undo_create"] is False
    resp = gw.client.post("/api/automations/rules/morning-brief/undo", json={"to_version": 0, "base_version": 2})
    assert resp.status_code == 404
    assert "morning-brief" in _file_rules(gw)


def test_a_hand_edit_between_two_writes_is_recorded_as_a_baseline_and_kept(make_gateway) -> None:
    gw = make_gateway()
    _edit(gw, "morning-brief", prompt="From the page {scheduled_at}.")
    doc = json.loads(gw.rules.read_text())
    doc["rules"][0]["prompt"] = "Hand-written {scheduled_at}."
    gw.rules.write_text(json.dumps(doc, indent=4))
    history_before = [p.read_text() for p in sorted(_history(gw).dir.glob("*.jsonl"))]

    # Reading sees it, and writes nothing.
    seen = _versions(gw, "morning-brief")
    assert (seen["current"], seen["unrecorded"]) == (3, True)
    assert [p.read_text() for p in sorted(_history(gw).dir.glob("*.jsonl"))] == history_before

    resp = gw.client.patch("/api/automations/rules/morning-brief/enabled", json={"enabled": False, "version": _view(gw)["version"]})
    assert resp.status_code == 200, resp.text

    records = _records(gw, "morning-brief")
    assert [(r["version"], r["source"], r["via"]) for r in records] == [(1, "existing", ""), (2, "manual", "page"), (3, "existing", "hand-edit"), (4, "manual", "page")]
    assert records[2]["snapshot"]["prompt"] == "Hand-written {scheduled_at}." and records[2]["changed"] == ["prompt"]
    assert _file_rules(gw)["morning-brief"]["prompt"] == "Hand-written {scheduled_at}.", "the hand edit was lost"
    # Undo of the page's toggle goes back to the hand edit, not past it.
    assert gw.client.post("/api/automations/rules/morning-brief/undo", json={"to_version": 3, "base_version": 4}).status_code == 200
    assert _file_rules(gw)["morning-brief"]["prompt"] == "Hand-written {scheduled_at}." and _file_rules(gw)["morning-brief"]["enabled"] is True


def test_a_hand_deleted_rule_is_recorded_as_deleted_and_can_be_brought_back(make_gateway) -> None:
    gw = make_gateway()
    _edit(gw, "morning-brief", prompt="Edited {scheduled_at}.")
    doc = json.loads(gw.rules.read_text())
    doc["rules"] = [r for r in doc["rules"] if r["id"] != "blocked-session"]
    gw.rules.write_text(json.dumps(doc))
    _edit(gw, "morning-brief", prompt="Again {scheduled_at}.")

    records = _records(gw, "blocked-session")
    assert [(r["version"], r["source"], r["snapshot"] is None) for r in records] == [(1, "existing", False), (2, "existing", True)]
    assert gw.client.post("/api/automations/rules/blocked-session/undo", json={"to_version": 1, "base_version": 2}).status_code == 200
    assert "blocked-session" in _file_rules(gw)


def test_a_stale_undo_is_refused_and_changes_nothing(make_gateway) -> None:
    gw = make_gateway()
    _edit(gw, "morning-brief", prompt="One {scheduled_at}.")
    _edit(gw, "morning-brief", prompt="Two {scheduled_at}.")
    file_before, records_before = gw.rules.read_bytes(), _records(gw, "morning-brief")

    resp = gw.client.post("/api/automations/rules/morning-brief/undo", json={"to_version": 1, "base_version": 2})

    assert resp.status_code == 409 and "changed since" in resp.json()["detail"], resp.text
    assert gw.rules.read_bytes() == file_before and _records(gw, "morning-brief") == records_before


def test_two_workers_writing_the_same_rule_one_is_refused_as_stale(make_gateway) -> None:
    from app.gateway.automations_store import RulesEditError
    from app.gateway.routers.automations import edit_rules, undo_rule
    from omniharness.config.app_config import get_app_config

    gw = make_gateway()
    _edit(gw, "morning-brief", prompt="Base {scheduled_at}.")
    config = get_app_config()
    start = threading.Barrier(2)
    outcomes: list[str] = []

    def worker(prompt: str) -> None:
        def change(doc):
            return {**doc, "rules": [{**r, "prompt": prompt} if r["id"] == "morning-brief" else r for r in doc["rules"]]}

        start.wait()
        try:
            edit_rules(config, change, None, who="user:test", base_versions={"morning-brief": 2})
            outcomes.append(prompt)
        except RulesEditError as exc:
            assert exc.status == 409, exc
            outcomes.append("refused")

    threads = [threading.Thread(target=worker, args=(p,)) for p in ("A {scheduled_at}.", "B {scheduled_at}.")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(outcomes, key=lambda o: o == "refused")[1] == "refused" and outcomes.count("refused") == 1, outcomes
    winner = next(o for o in outcomes if o != "refused")
    assert _file_rules(gw)["morning-brief"]["prompt"] == winner
    assert [r["version"] for r in _records(gw, "morning-brief")] == [1, 2, 3]
    # undo_rule is the same path the chat builder will call.
    assert undo_rule(config, "morning-brief", 2, base_version=3, who="user:test")
    with pytest.raises(RulesEditError):
        undo_rule(config, "morning-brief", 2, base_version=3, who="user:test")


def test_the_engine_reads_identical_rules_before_and_after_the_migration(make_gateway) -> None:
    """Scheduled runs behave exactly as on main: the migration only adds
    history; the engine's rules (schedule, zone, prompt, destination, agent,
    every field it parses) are identical before and after it."""
    gw = make_gateway(engine_enabled=True)
    doc = json.loads(gw.rules.read_text())
    doc["rules"].append({"id": "Weekly Review!", "type": "cron", "enabled": False, "match": {"schedule": "0 16 * * 5", "timezone": "Europe/London"}, "prompt": "Review {scheduled_at}.", "destination": "quiet", "urgent": True})
    gw.rules.write_text(json.dumps(doc, indent=3, sort_keys=True))  # hand formatting
    before = _engine(gw.rules)
    rules_before = _file_rules(gw)
    next_runs = {r["id"]: r["next_run_at"] for r in _view(gw)["rules"]}

    # A write that changes no rule (switch on what is already on): the
    # migration alone. Every rule gets its baseline; the engine sees no change.
    resp = gw.client.patch("/api/automations/rules/morning-brief/enabled", json={"enabled": True, "version": _view(gw)["version"]})
    assert resp.status_code == 200, resp.text

    assert _engine(gw.rules) == before, "the engine reads different rules after the migration"
    assert _file_rules(gw) == rules_before
    for rule_id, rule in rules_before.items():
        assert [(r["version"], r["source"], r["snapshot"]) for r in _records(gw, rule_id)] == [(1, "existing", rule)], rule_id
    # A view of the scheduling: the next run of each rule is unchanged.
    assert {r["id"]: r["next_run_at"] for r in _view(gw)["rules"]} == next_runs

    # An edit and its undo leave the engine exactly where it started.
    _edit(gw, "Weekly Review!", prompt="Changed {scheduled_at}.")
    assert gw.client.post("/api/automations/rules/Weekly Review!/undo", json={"to_version": 1, "base_version": 2}).status_code == 200
    assert _engine(gw.rules) == before


def test_studio_schedule_writes_are_versions_and_undo_of_their_create_deletes_the_schedule(make_gateway) -> None:
    gw = make_gateway()
    c = gw.client
    version = c.get("/api/studio/agents/lead_agent/runs").json()["rules_version"]
    made = c.post("/api/studio/agents/lead_agent/schedules", json={"schedule": "0 18 * * 1-5", "timezone": "UTC", "version": version})
    assert made.status_code == 201, made.text
    rule_id = made.json()["rule_id"]

    history = _versions(gw, rule_id)
    assert [(v["version"], v["source"], v["via"], v["changed"]) for v in history["versions"]] == [(1, "manual", "studio", ["created"])]

    resp = c.post(f"/api/automations/rules/{rule_id}/undo", json={"to_version": 0, "base_version": 1, "via": "studio"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["versions"][0]["via"] == "studio" and resp.json()["versions"][0]["deleted"] is True
    assert rule_id not in {s["rule_id"] for s in c.get("/api/studio/agents/lead_agent/runs").json()["schedules"]}


def test_versions_of_an_unknown_rule_is_404_and_reads_need_the_owner(make_gateway) -> None:
    gw = make_gateway()
    assert gw.client.get("/api/automations/rules/nope/versions").status_code == 404
    assert gw.client.post("/api/automations/rules/nope/undo", json={"to_version": 1, "base_version": 0}).status_code == 404
    gw.client.cookies.clear()
    assert gw.client.get("/api/automations/rules/morning-brief/versions").status_code == 401
