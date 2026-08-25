"""The first tool whose NAME cannot classify it (FR-037, raise-only).

`postgres_query` carries SELECT and DELETE FROM through one entry point. The
pattern here is the one every future ambiguous tool follows, so its failure
DIRECTION matters more than its cleverness: the predicate answers "is this
safe", never "is this dangerous", and everything it cannot establish raises.
"""

from __future__ import annotations

import pytest

from app.policy.classify import classify
from app.policy.config import ConfigLoader
from app.policy.models import Tier
from app.policy.registration import DEFAULT_RULES


@pytest.fixture
def shipped():
    return ConfigLoader(path=DEFAULT_RULES).load()


def test_the_rules_load(shipped):
    """POSITIVE CONTROL. An unreadable rule set makes EVERY tool Tier 3, so the
    raise assertions below would all pass while proving nothing."""
    assert not shipped.unreadable, shipped.error
    assert classify("ls", {}, shipped).tier is Tier.TIER_1, "the rule set is degraded"


@pytest.mark.parametrize("sql", ["SELECT 1", "select * from t", "  -- note\nSELECT a FROM b", "SELECT 1;"])
def test_a_plain_select_stays_tier_1(shipped, sql):
    assert classify("postgres_query", {"sql": sql}, shipped).tier is Tier.TIER_1


@pytest.mark.parametrize(
    "arguments",
    [
        {"sql": "DELETE FROM t"},
        {"sql": "UPDATE t SET a = 1"},
        {"sql": "DROP TABLE t"},
        {"sql": "SELECT 1; DROP TABLE t"},
        {"sql": "WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x"},
        {"sql": "SELECT * INTO copy FROM t"},
        {"sql": ""},
        {"sql": None},
        {"sql": 123},
        {},
        {"query": "SELECT 1"},
    ],
    ids=["delete", "update", "drop", "two-statements", "cte-delete", "select-into", "empty", "none", "not-a-string", "absent", "wrong-argument-name"],
)
def test_anything_not_established_safe_raises_to_tier_3(shipped, arguments):
    """The last two are the ones worth staring at.

    `absent` and `wrong-argument-name` are the same failure: the rules file
    names an argument the tool does not have. That must RAISE, because the
    alternative is a rule that looks like protection and silently permits every
    statement. It costs a confirmation prompt to be wrong this way, and an
    unreviewed DELETE to be wrong the other.
    """
    assert classify("postgres_query", arguments, shipped).tier is Tier.TIER_3


def test_an_unknown_predicate_is_rejected_at_load(tmp_path):
    """Rejected AT LOAD, in the direction this loader already uses.

    The error does not propagate to the caller: the whole rule set degrades to
    unreadable, which FR-009 makes mean EVERY tool is Tier 3. That is the safe
    end — a rules file naming a predicate that does not exist would otherwise
    sit there looking like protection and match nothing.
    """
    path = tmp_path / "rules.yaml"
    path.write_text('policy:\n  rules:\n    - pattern: "x"\n      tier: 1\n      exceptions:\n        - unless: {sql: no_such_predicate}\n          tier: 3\n')
    rules = ConfigLoader(path=path).load()

    assert rules.unreadable, "an unknown predicate loaded as if it were valid"
    assert "no_such_predicate" in rules.error
    assert "read_only_sql" in rules.error, "the error does not say what IS available"
    assert str(path) in rules.error, "the error does not name the file"
    assert classify("x", {}, rules).tier is Tier.TIER_3


def test_an_exception_with_neither_when_nor_unless_is_rejected(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text('policy:\n  rules:\n    - pattern: "x"\n      tier: 1\n      exceptions:\n        - tier: 3\n')
    rules = ConfigLoader(path=path).load()
    assert rules.unreadable
    assert "never apply" in rules.error


def test_the_existing_when_exceptions_still_work(shipped):
    """Control for the change to `matches`: the argument-equality form that
    Feature 003 shipped must behave exactly as before."""
    assert classify("googlecalendar_create_event", {"send_updates": "all"}, shipped).tier is Tier.TIER_3
    assert classify("googlecalendar_create_event", {}, shipped).tier is Tier.TIER_2
