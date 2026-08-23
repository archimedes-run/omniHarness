"""Quiet hours honour the configuration the user actually wrote.

Two defects, both surfaced by wiring the engine into the gateway and starting it.

1. TWO CLASSES NAMED QuietHours. `config.QuietHours` is frozen data parsed from
   the rules file; `politeness.QuietHours` decides suppression. Nothing
   converted between them, so what a user wrote under `quiet_hours:` never
   reached enforcement. Every test passed because each constructed the
   enforcing type directly — the test environment differed structurally from
   production, and hid exactly the defect it existed to catch.

2. The enforcing type had no timezone and compared naive local times, so a
   configured zone was parsed and ignored. That is worse than quiet hours being
   off: the user sees the setting, sees messages suppressed, and has no reason
   to check the hours are the ones they wrote.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from app.trigger_engine.config import ConfigLoader
from app.trigger_engine.politeness.quiet_hours import QuietHours

RULE = {"id": "r", "type": "cron", "match": {"schedule": "* * * * *"}, "prompt": "p", "destination": "quiet"}


def _load(tmp_path, quiet_hours: dict | None):
    doc = {"rules": [RULE]}
    if quiet_hours is not None:
        doc["quiet_hours"] = quiet_hours
    f = tmp_path / "rules.json"
    f.write_text(json.dumps(doc))
    return ConfigLoader(path=f).load()


# ---------------------------------------------------------------------------
# Gap 1: `enabled` is expressible in configuration
# ---------------------------------------------------------------------------


def test_quiet_hours_can_be_switched_off_from_the_rules_file(tmp_path):
    cfg = _load(tmp_path, {"start": "22:00", "end": "07:30", "enabled": False})

    assert cfg.quiet_hours.enabled is False


def test_quiet_hours_default_to_on(tmp_path):
    """Absence must not read as 'off' — a user who writes a window and omits the
    flag means to use it."""
    cfg = _load(tmp_path, {"start": "22:00", "end": "07:30"})

    assert cfg.quiet_hours.enabled is True


# ---------------------------------------------------------------------------
# Gap 2: the configured timezone changes behaviour
# ---------------------------------------------------------------------------


def test_the_configured_timezone_actually_moves_the_window():
    """02:00 UTC is 07:30 in Asia/Kolkata (UTC+5:30).

    With a 22:00-07:30 window that instant is INSIDE the UTC window and OUTSIDE
    the Kolkata one, whose end it exactly reaches. If the timezone were ignored
    both would agree, which is what made the bug invisible.
    """
    at = datetime(2026, 8, 24, 2, 0, tzinfo=UTC)

    assert QuietHours(start="22:00", end="07:30", timezone="UTC").contains(at) is True
    assert QuietHours(start="22:00", end="07:30", timezone="Asia/Kolkata").contains(at) is False


def test_a_naive_instant_is_read_as_utc():
    naive = datetime(2026, 8, 24, 2, 0)
    aware = datetime(2026, 8, 24, 2, 0, tzinfo=UTC)
    window = QuietHours(start="22:00", end="07:30", timezone="Asia/Kolkata")

    assert window.contains(naive) == window.contains(aware)


def test_an_unknown_timezone_falls_back_to_utc_loudly(caplog):
    """Silently suppressing at unpredictable hours would be the same class of
    defect as ignoring the zone."""
    at = datetime(2026, 8, 24, 2, 0, tzinfo=UTC)

    with caplog.at_level("ERROR"):
        result = QuietHours(start="22:00", end="07:30", timezone="Not/AZone").contains(at)

    assert result is True  # i.e. the UTC answer
    assert any("not a known zone" in r.message for r in caplog.records)


def test_disabled_beats_everything():
    at = datetime(2026, 8, 24, 2, 0, tzinfo=UTC)

    assert QuietHours(start="22:00", end="07:30", timezone="UTC", enabled=False).contains(at) is False


# ---------------------------------------------------------------------------
# The two types agree
# ---------------------------------------------------------------------------


def test_config_reaches_enforcement(tmp_path):
    """The end-to-end claim: what the rules file says is what suppresses.

    This is the test whose absence let the two types diverge — every other
    quiet-hours test builds the enforcing type by hand and so cannot notice
    that nothing loads it from configuration.
    """
    from app.gateway.trigger_engine_wiring import _quiet_hours

    cfg = _load(tmp_path, {"start": "01:00", "end": "03:00", "timezone": "Asia/Kolkata", "enabled": True})
    enforced = _quiet_hours(cfg)

    assert enforced.start == "01:00"
    assert enforced.end == "03:00"
    assert enforced.timezone == "Asia/Kolkata"
    assert enforced.enabled is True
    # 20:00 UTC == 01:30 IST next day -> inside the configured window
    assert enforced.contains(datetime(2026, 8, 23, 20, 0, tzinfo=UTC)) is True
    # 20:00 UTC is NOT inside 01:00-03:00 when read as UTC, so this also proves
    # the zone survived the adapter.
    assert QuietHours(start="01:00", end="03:00", timezone="UTC").contains(datetime(2026, 8, 23, 20, 0, tzinfo=UTC)) is False


def test_a_disabled_config_reaches_enforcement_as_disabled(tmp_path):
    from app.gateway.trigger_engine_wiring import _quiet_hours

    cfg = _load(tmp_path, {"start": "22:00", "end": "07:30", "enabled": False})

    assert _quiet_hours(cfg).enabled is False
