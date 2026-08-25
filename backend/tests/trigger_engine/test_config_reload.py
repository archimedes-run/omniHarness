"""T012 — config load, validation and hot reload (FR-001, FR-005, FR-006)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.trigger_engine.config import ConfigError, ConfigLoader, parse
from app.trigger_engine.models import Destination, TriggerType

FIXTURES = Path(__file__).parent / "fixtures"


def _doc(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_valid_rules_parse() -> None:
    cfg = parse(_doc("rules_valid.json"))
    assert [r.id for r in cfg.rules] == ["blocked-session", "morning-briefing"]
    assert cfg.rules[0].type is TriggerType.WATCHER
    assert cfg.rules[0].destination is Destination.AUTO
    assert cfg.rules[1].destination is Destination.REMOTE
    assert cfg.quiet_hours.start == "22:00"


def test_duplicate_id_is_a_load_error() -> None:
    """The id is the thread-map key; a duplicate would merge two rules' history."""
    with pytest.raises(ConfigError, match="duplicate rule id"):
        parse(_doc("rules_duplicate_id.json"))


def test_template_referencing_an_unavailable_field_fails_at_load() -> None:
    """FR-004 — a typo must not surface as a half-rendered message at 3am."""
    with pytest.raises(ConfigError, match="cannot supply"):
        parse(_doc("rules_bad_template.json"))


def test_calendar_is_now_accepted() -> None:
    """The reservation paid off.

    This test used to assert calendar rules were REFUSED at load, pinning the
    Feature 002 deferral. It failed on the commit that implemented them, which
    is what the reservation was for: adding calendar was a new source plus two
    registration points, not a schema migration.
    """
    cfg = parse(_doc("rules_calendar.json"))

    assert any(r.type is TriggerType.CALENDAR for r in cfg.rules)


def test_a_calendar_rule_must_say_how_far_ahead_to_fire() -> None:
    """The one thing a calendar rule cannot do without. Absent it, the engine
    would have to invent a lead time, and a pre-alert at a guessed interval is
    worse than none."""
    doc = _doc("rules_calendar.json")
    for rule in doc["rules"]:
        rule.get("match", {}).pop("minutes_before", None)

    with pytest.raises(ConfigError, match="minutes_before"):
        parse(doc)


def test_urgent_defaults_to_false_and_must_be_explicit() -> None:
    """FR-014 — no implicit escalation."""
    cfg = parse(_doc("rules_valid.json"))
    assert all(r.urgent is False for r in cfg.rules)


def test_hot_reload_picks_up_changes(rule_file, a_rule) -> None:
    """FR-005 — no restart."""
    f = rule_file([a_rule("r1")])
    loader = ConfigLoader(path=f)
    assert [r.id for r in loader.load().rules] == ["r1"]

    f.write_text(json.dumps({"rules": [a_rule("r1"), a_rule("r2")]}))
    import os
    import time

    os.utime(f, (time.time() + 1, time.time() + 1))
    assert [r.id for r in loader.load().rules] == ["r1", "r2"]


def test_removing_a_rule_stops_it(rule_file, a_rule) -> None:
    f = rule_file([a_rule("r1"), a_rule("r2")])
    loader = ConfigLoader(path=f)
    assert len(loader.load().rules) == 2
    import os
    import time

    f.write_text(json.dumps({"rules": [a_rule("r1")]}))
    os.utime(f, (time.time() + 1, time.time() + 1))
    assert [r.id for r in loader.load().rules] == ["r1"]


def test_invalid_edit_keeps_the_previous_config_active(rule_file, a_rule) -> None:
    """FR-006, SC-009 — a config that fails OPEN is worse than one that fails
    to load, because nobody notices. The previous rules must stay armed."""
    f = rule_file([a_rule("r1")])
    loader = ConfigLoader(path=f)
    assert len(loader.load().rules) == 1

    import os
    import time

    f.write_text("{ not valid json")
    os.utime(f, (time.time() + 1, time.time() + 1))
    cfg = loader.load()

    assert [r.id for r in cfg.rules] == ["r1"], "a typo disarmed the engine"
    assert loader.last_error, "the error was not reported"


def test_unreadable_file_keeps_previous_config(rule_file, a_rule) -> None:
    f = rule_file([a_rule("r1")])
    loader = ConfigLoader(path=f)
    loader.load()
    f.unlink()
    assert [r.id for r in loader.load().rules] == ["r1"]
    assert loader.last_error
