"""T079-T081 — US5: rules change without a restart (FR-005, SC-008, SC-009)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from app.trigger_engine.config import ConfigLoader


def _touch(p: Path) -> None:
    t = time.time() + 1
    os.utime(p, (t, t))


def test_a_rule_added_while_running_becomes_active(rule_file, a_rule) -> None:
    f = rule_file([a_rule("r1")])
    loader = ConfigLoader(path=f)
    assert [r.id for r in loader.load().rules] == ["r1"]
    f.write_text(json.dumps({"rules": [a_rule("r1"), a_rule("r2")]}))
    _touch(f)
    assert [r.id for r in loader.load().rules] == ["r1", "r2"]


def test_a_rule_removed_while_running_stops_firing(rule_file, a_rule) -> None:
    f = rule_file([a_rule("r1"), a_rule("r2")])
    loader = ConfigLoader(path=f)
    loader.load()
    f.write_text(json.dumps({"rules": [a_rule("r2")]}))
    _touch(f)
    assert [r.id for r in loader.load().rules] == ["r2"]


def test_an_edited_rule_takes_effect(rule_file, a_rule) -> None:
    f = rule_file([a_rule("r1", destination="quiet")])
    loader = ConfigLoader(path=f)
    assert loader.load().rules[0].destination.value == "quiet"
    f.write_text(json.dumps({"rules": [a_rule("r1", destination="remote")]}))
    _touch(f)
    assert loader.load().rules[0].destination.value == "remote"


def test_an_unchanged_file_is_not_reparsed(rule_file, a_rule) -> None:
    """Reload is mtime-gated: hot reload must not mean re-reading every cycle."""
    f = rule_file([a_rule("r1")])
    loader = ConfigLoader(path=f)
    first = loader.load()
    assert loader.load() is first


def test_a_typo_does_not_disarm_the_engine(rule_file, a_rule) -> None:
    """SC-009 — a config that fails OPEN is worse than one that fails to load,
    because nobody notices."""
    f = rule_file([a_rule("r1"), a_rule("r2")])
    loader = ConfigLoader(path=f)
    assert len(loader.load().rules) == 2
    f.write_text('{"rules": [ oops')
    _touch(f)
    cfg = loader.load()
    assert [r.id for r in cfg.rules] == ["r1", "r2"], "a typo disarmed both rules"
    assert loader.last_error


def test_recovery_after_a_bad_edit(rule_file, a_rule) -> None:
    f = rule_file([a_rule("r1")])
    loader = ConfigLoader(path=f)
    loader.load()
    f.write_text("{ broken")
    _touch(f)
    loader.load()
    assert loader.last_error
    f.write_text(json.dumps({"rules": [a_rule("r1"), a_rule("r3")]}))
    _touch(f)
    cfg = loader.load()
    assert [r.id for r in cfg.rules] == ["r1", "r3"]
    assert loader.last_error is None


def test_a_semantically_invalid_edit_is_also_inert(rule_file, a_rule) -> None:
    """Not just syntax: a duplicate id is caught at load and the prior config
    stays active, because the id is the thread-map key."""
    f = rule_file([a_rule("r1")])
    loader = ConfigLoader(path=f)
    loader.load()
    f.write_text(json.dumps({"rules": [a_rule("dup"), a_rule("dup")]}))
    _touch(f)
    assert [r.id for r in loader.load().rules] == ["r1"]
    assert "duplicate" in (loader.last_error or "")
