"""Classification, unknown-tool default, and raise-only exceptions."""

from __future__ import annotations

import pytest

from app.policy.classify import classify
from app.policy.config import ConfigLoader
from app.policy.explain import explain, render
from app.policy.models import Tier

RULES = """
policy:
  rules:
    - pattern: "session_watcher_*"
      tier: 1
    - pattern: "calendar_*"
      tier: 1
    - pattern: "calendar_create_hold"
      tier: 2
    - pattern: "calendar_delete_event"
      tier: 3
    - pattern: "browser_*"
      tier: 1
      exceptions:
        - when: {action: [click, submit]}
          tier: 3
  confirmation:
    expires_after_seconds: 3600
"""


@pytest.fixture
def ruleset(tmp_path):
    path = tmp_path / "policy.yaml"
    path.write_text(RULES)
    return ConfigLoader(path=path).load()


def test_tiers_are_read_from_the_file(ruleset):
    assert classify("session_watcher_list", {}, ruleset).tier is Tier.TIER_1
    assert classify("calendar_create_hold", {}, ruleset).tier is Tier.TIER_2
    assert classify("calendar_delete_event", {}, ruleset).tier is Tier.TIER_3


def test_an_argument_exception_raises_the_tier(ruleset):
    assert classify("browser_click", {"action": "read"}, ruleset).tier is Tier.TIER_1
    assert classify("browser_click", {"action": "click"}, ruleset).tier is Tier.TIER_3


def test_overlapping_patterns_resolve_to_the_highest_tier(ruleset):
    """Same direction as FR-037 — ambiguity resolves toward asking."""
    assert classify("calendar_delete_event", {}, ruleset).tier is Tier.TIER_3


# ---------------------------------------------------------------------------
# US4 — unknown tools
# ---------------------------------------------------------------------------


def test_an_unknown_tool_is_tier_3(ruleset):
    assert classify("something_nobody_wrote_a_rule_for", {}, ruleset).tier is Tier.TIER_3


def test_a_tool_added_after_the_config_was_written_is_tier_3(ruleset):
    """The requirement is about tools that did not exist when the rules were
    written, which is the case a static review cannot cover."""
    assert classify("newly_connected_server_send_money", {}, ruleset).tier is Tier.TIER_3


def test_a_missing_rules_file_makes_everything_tier_3(tmp_path):
    ruleset = ConfigLoader(path=tmp_path / "absent.yaml").load()

    assert ruleset.unreadable
    assert classify("session_watcher_list", {}, ruleset).tier is Tier.TIER_3


def test_an_unreadable_rules_file_makes_everything_tier_3(tmp_path):
    path = tmp_path / "policy.yaml"
    path.write_text("policy:\n  rules:\n    - this is not: [a valid rule\n")

    ruleset = ConfigLoader(path=path).load()

    assert ruleset.unreadable
    assert classify("anything", {}, ruleset).tier is Tier.TIER_3


def test_unreadable_is_distinguishable_from_empty(tmp_path):
    """Both make everything Tier 3. Only one is a mistake."""
    empty = tmp_path / "empty.yaml"
    empty.write_text("policy:\n  rules: []\n")

    assert not ConfigLoader(path=empty).load().unreadable
    assert ConfigLoader(path=tmp_path / "gone.yaml").load().unreadable


# ---------------------------------------------------------------------------
# FR-037 — raise only, rejected AT LOAD
# ---------------------------------------------------------------------------


def test_a_lowering_exception_is_rejected_at_load(tmp_path):
    """Not ignored at match time.

    A file that silently does something safer than what its author wrote is a
    file whose author never learns they were wrong.
    """
    path = tmp_path / "policy.yaml"
    path.write_text(
        """
policy:
  rules:
    - pattern: "calendar_delete_event"
      tier: 3
      exceptions:
        - when: {owner: me}
          tier: 1
"""
    )

    ruleset = ConfigLoader(path=path).load()

    assert ruleset.unreadable, "a lowering exception must fail the load, not be skipped"
    assert "only RAISE" in ruleset.error
    assert "calendar_delete_event" in ruleset.error


def test_the_rejection_names_the_file(tmp_path):
    """The author has to be able to find it."""
    path = tmp_path / "policy.yaml"
    path.write_text('policy:\n  rules:\n    - pattern: "x_*"\n      tier: 3\n      exceptions:\n        - when: {a: b}\n          tier: 2\n')

    error = ConfigLoader(path=path).load().error

    assert str(path) in error
    assert "exceptions[0]" in error


def test_a_raising_exception_is_accepted(tmp_path):
    path = tmp_path / "policy.yaml"
    path.write_text('policy:\n  rules:\n    - pattern: "x_*"\n      tier: 1\n      exceptions:\n        - when: {a: b}\n          tier: 3\n')

    assert not ConfigLoader(path=path).load().unreadable


def test_a_bad_reload_keeps_the_previous_rules(tmp_path):
    """A config error must never silently widen what is permitted."""
    path = tmp_path / "policy.yaml"
    path.write_text(RULES)
    loader = ConfigLoader(path=path)
    good = loader.load()
    assert classify("calendar_create_hold", {}, good).tier is Tier.TIER_2

    path.write_text('policy:\n  rules:\n    - pattern: "x"\n      tier: 3\n      exceptions:\n        - when: {a: b}\n          tier: 1\n')
    after = loader.load()

    assert len(after.rules) == len(good.rules), "the previous rules must survive a bad reload"
    assert classify("calendar_create_hold", {}, after).tier is Tier.TIER_2


# ---------------------------------------------------------------------------
# FR-038 — inspection uses the SAME path
# ---------------------------------------------------------------------------


def test_inspection_agrees_with_live_classification(ruleset):
    for name, args in [("browser_click", {"action": "click"}), ("calendar_delete_event", {}), ("unknown_tool", {})]:
        assert explain(name, args, ruleset) == classify(name, args, ruleset)


def test_inspection_names_the_deciding_rule(ruleset):
    rendered = render(explain("calendar_delete_event", {}, ruleset), ruleset)

    assert "tier:       3" in rendered
    assert "calendar_delete_event" in rendered


def test_inspection_names_the_exception_that_raised_it(ruleset):
    """The reason FR-038 exists: raise-only is safe but opaque."""
    rendered = render(explain("browser_click", {"action": "click"}, ruleset), ruleset)

    assert "raised_by:  exception" in rendered
    assert "tier 3" in rendered


def test_inspection_says_when_the_rules_could_not_be_read(tmp_path):
    ruleset = ConfigLoader(path=tmp_path / "gone.yaml").load()

    assert "could not be read" in render(explain("x", {}, ruleset), ruleset)
