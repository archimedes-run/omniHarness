"""GATE C — an exception may only RAISE a tier (FR-037).

A malformed or over-broad rule must fail toward ASKING, never toward acting.
The refusal happens AT LOAD, naming file and line, rather than at match time:

    A file that silently does something safer than what its author wrote is a
    file whose author never learns they were wrong.

Ignoring at match time produces correct behaviour and no understanding — the
user keeps a rule they believe is in force, is not, and writes more like it.
"""

from __future__ import annotations

import pytest

from app.policy.classify import classify
from app.policy.config import ConfigLoader
from app.policy.models import Tier


def _load(tmp_path, body: str):
    path = tmp_path / "policy.yaml"
    path.write_text(body)
    return ConfigLoader(path=path).load(), path


LOWERING_ATTEMPTS = [
    ("tier 3 rule, tier 1 exception", 3, 1),
    ("tier 3 rule, tier 2 exception", 3, 2),
    ("tier 2 rule, tier 1 exception", 2, 1),
]


@pytest.mark.parametrize("label,rule_tier,exception_tier", LOWERING_ATTEMPTS)
def test_a_lowering_exception_fails_the_load(tmp_path, label, rule_tier, exception_tier):
    ruleset, path = _load(
        tmp_path,
        f'policy:\n  rules:\n    - pattern: "danger_*"\n      tier: {rule_tier}\n      exceptions:\n        - when: {{owner: me}}\n          tier: {exception_tier}\n',
    )

    assert ruleset.unreadable, f"{label}: the load succeeded; a lowering exception was accepted"
    assert "only RAISE" in ruleset.error


@pytest.mark.parametrize("label,rule_tier,exception_tier", LOWERING_ATTEMPTS)
def test_the_lowering_exception_does_not_take_effect(tmp_path, label, rule_tier, exception_tier):
    """Belt and braces: even if a load ever let one through, the call must not
    be lowered."""
    ruleset, _ = _load(
        tmp_path,
        f'policy:\n  rules:\n    - pattern: "danger_*"\n      tier: {rule_tier}\n      exceptions:\n        - when: {{owner: me}}\n          tier: {exception_tier}\n',
    )

    assert classify("danger_delete", {"owner": "me"}, ruleset).tier is Tier.TIER_3


def test_an_equal_tier_exception_is_also_rejected(tmp_path):
    """It cannot raise, so it is either a mistake or noise. Either way the
    author should hear about it."""
    ruleset, _ = _load(tmp_path, 'policy:\n  rules:\n    - pattern: "x_*"\n      tier: 2\n      exceptions:\n        - when: {a: b}\n          tier: 2\n')

    assert ruleset.unreadable


def test_the_error_names_file_line_and_the_pattern(tmp_path):
    """The author has to be able to find it — that is the entire reason this
    fails at load rather than being skipped."""
    ruleset, path = _load(tmp_path, 'policy:\n  rules:\n    - pattern: "calendar_delete_event"\n      tier: 3\n      exceptions:\n        - when: {owner: me}\n          tier: 1\n')

    assert str(path) in ruleset.error
    assert "exceptions[0]" in ruleset.error
    assert "calendar_delete_event" in ruleset.error
    assert "change the rule's tier" in ruleset.error, "the message must say what to do instead"


def test_a_raising_exception_still_works(tmp_path):
    """CONTROL. A gate that rejects everything is safe and useless."""
    ruleset, _ = _load(tmp_path, 'policy:\n  rules:\n    - pattern: "browser_*"\n      tier: 1\n      exceptions:\n        - when: {action: submit}\n          tier: 3\n')

    assert not ruleset.unreadable
    assert classify("browser_do", {"action": "submit"}, ruleset).tier is Tier.TIER_3
    assert classify("browser_do", {"action": "read"}, ruleset).tier is Tier.TIER_1


def test_overlapping_patterns_take_the_higher_tier(tmp_path):
    """Same direction: ambiguity resolves toward asking."""
    ruleset, _ = _load(tmp_path, 'policy:\n  rules:\n    - pattern: "cal_*"\n      tier: 1\n    - pattern: "cal_delete"\n      tier: 3\n')

    assert classify("cal_delete", {}, ruleset).tier is Tier.TIER_3


def test_a_bad_rule_does_not_widen_what_is_permitted(tmp_path):
    """The failure that matters: a broken file must never make a Tier 3 tool
    Tier 1."""
    path = tmp_path / "policy.yaml"
    path.write_text('policy:\n  rules:\n    - pattern: "danger_*"\n      tier: 3\n')
    loader = ConfigLoader(path=path)
    loader.load()

    path.write_text('policy:\n  rules:\n    - pattern: "danger_*"\n      tier: 3\n      exceptions:\n        - when: {a: b}\n          tier: 1\n')
    after = loader.load()

    assert classify("danger_delete", {"a": "b"}, after).tier is Tier.TIER_3
