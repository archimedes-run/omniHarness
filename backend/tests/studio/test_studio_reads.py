"""An agent's schedule and recent runs come from the trigger engine (T303).

Every rule today runs as the lead agent (the injector's assistant id), so the
lead agent owns them all and a custom agent has none until a rule names it.
Next run is the engine's own computation, in the rule's zone (or the engine's
default zone when it names none), held to the end of quiet hours unless the rule is urgent.
"""

from __future__ import annotations

import json
from datetime import datetime

RULES = {
    "quiet_hours": {"start": "22:00", "end": "07:30", "timezone": "America/New_York", "enabled": True},
    "rules": [
        {"id": "evening-wrap", "type": "cron", "enabled": True, "match": {"schedule": "0 18 * * 1-5", "timezone": "America/New_York"}, "prompt": "Wrap up", "destination": "auto"},
        {"id": "late-digest", "type": "cron", "enabled": True, "match": {"schedule": "30 23 * * *", "timezone": "America/New_York"}, "prompt": "Digest", "destination": "auto"},
        {"id": "utc-ping", "type": "cron", "enabled": True, "match": {"schedule": "0 12 * * *"}, "prompt": "Ping", "destination": "auto"},
        {"id": "off-rule", "type": "cron", "enabled": False, "match": {"schedule": "0 9 * * *"}, "prompt": "Off", "destination": "auto"},
    ],
}


def _write(studio, audit: list[dict]) -> None:
    (studio.tmp / "rules.json").write_text(json.dumps(RULES))
    (studio.tmp / "triggers").mkdir(exist_ok=True)
    (studio.tmp / "triggers" / "audit.jsonl").write_text("".join(json.dumps(e) + "\n" for e in audit))


def test_the_lead_agent_owns_every_rule_with_engine_next_runs(studio) -> None:
    _write(studio, [{"at": "2026-10-19T22:00:05+00:00", "rule_id": "evening-wrap", "event_type": "cron", "event_id": "e1", "outcome": "delivered", "reason": "", "batch_id": None}])
    body = studio.client.get("/api/studio/agents/lead_agent/runs").json()
    assert body["not_set_up_reason"] is None
    by_id = {s["rule_id"]: s for s in body["schedules"]}
    assert set(by_id) == {"evening-wrap", "late-digest", "utc-ping", "off-rule"}

    wrap = datetime.fromisoformat(by_id["evening-wrap"]["next_run"])
    local = wrap.astimezone(__import__("zoneinfo").ZoneInfo("America/New_York"))
    assert (local.hour, local.minute) == (18, 0) and local.weekday() < 5
    assert by_id["evening-wrap"]["held_until"] is None

    # 23:30 New York is inside 22:00-07:30: held until 07:30 the next morning.
    held = datetime.fromisoformat(by_id["late-digest"]["held_until"]).astimezone(__import__("zoneinfo").ZoneInfo("America/New_York"))
    assert (held.hour, held.minute) == (7, 30)

    # A rule that names no zone runs in the engine's default zone (New York
    # since main's d059617), and says so.
    assert (by_id["utc-ping"]["timezone"], by_id["utc-ping"]["timezone_named"]) == ("America/New_York", False)
    ping = datetime.fromisoformat(by_id["utc-ping"]["next_run"]).astimezone(__import__("zoneinfo").ZoneInfo("America/New_York"))
    assert (ping.hour, ping.minute) == (12, 0)
    assert by_id["off-rule"]["next_run"] is None

    assert [(r["rule_id"], r["outcome"]) for r in body["recent"]] == [("evening-wrap", "delivered")]


def test_a_custom_agent_has_no_schedule_until_a_rule_names_it(studio) -> None:
    _write(studio, [])
    body = studio.client.get("/api/studio/agents/evening-wrap-up/runs").json()
    assert (body["schedules"], body["recent"], body["not_set_up_reason"]) == ([], [], "none-name-this-agent")


def test_a_rule_that_names_the_agent_is_its_own(studio) -> None:
    named = json.loads(json.dumps(RULES))
    named["rules"][0]["match"]["agent"] = "evening-wrap-up"
    (studio.tmp / "rules.json").write_text(json.dumps(named))
    (studio.tmp / "triggers").mkdir(exist_ok=True)
    body = studio.client.get("/api/studio/agents/evening-wrap-up/runs").json()
    assert [s["rule_id"] for s in body["schedules"]] == ["evening-wrap"]
    lead = studio.client.get("/api/studio/agents/lead_agent/runs").json()
    assert "evening-wrap" not in {s["rule_id"] for s in lead["schedules"]}


def test_studio_options_name_the_configured_tool_groups_and_model(studio) -> None:
    body = studio.client.get("/api/studio/options").json()
    assert body["tool_groups"] == ["web", "file:read", "file:write", "bash"]
    assert body["default_model"] == "default"
