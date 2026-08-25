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


# ---------------------------------------------------------------------------
# GitHub writes — the tier turns on an argument for three of them
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool",
    [
        "github_add_issue_comment",
        "github_create_pull_request_review",
        "github_create_issue",
        "github_merge_pull_request",
        "github_create_repository",
        "github_fork_repository",
    ],
)
def test_a_github_write_that_reaches_someone_asks_first(shipped, tool):
    """The dividing line is NOTIFICATION, not mutation. A comment cannot be
    unsent even though GitHub will delete it afterwards."""
    assert classify(tool, {}, shipped).tier is Tier.TIER_3


@pytest.mark.parametrize("tool", ["github_create_branch", "github_update_issue", "github_update_pull_request_branch"])
def test_a_reversible_github_write_is_disclosed_not_gated(shipped, tool):
    assert classify(tool, {}, shipped).tier is Tier.TIER_2


@pytest.mark.parametrize("tool", ["github_push_files", "github_create_or_update_file"])
@pytest.mark.parametrize(
    "branch,expected",
    [
        ("feature/x", Tier.TIER_2),
        ("refs/heads/topic", Tier.TIER_2),
        ("main", Tier.TIER_3),
        ("MAIN", Tier.TIER_3),
        ("refs/heads/master", Tier.TIER_3),
        ("production", Tier.TIER_3),
        ("", Tier.TIER_3),
        (None, Tier.TIER_3),
        (123, Tier.TIER_3),
    ],
)
def test_a_push_is_gated_by_which_branch(shipped, tool, branch, expected):
    assert classify(tool, {"branch": branch}, shipped).tier is expected


@pytest.mark.parametrize("tool", ["github_push_files", "github_create_or_update_file"])
def test_a_push_with_no_branch_argument_raises(shipped, tool):
    """Same direction as the SQL predicate: a rule naming an argument the tool
    does not have must raise, not silently permit."""
    assert classify(tool, {}, shipped).tier is Tier.TIER_3


@pytest.mark.parametrize(
    "arguments,expected",
    [
        ({"draft": True}, Tier.TIER_2),
        ({"draft": False}, Tier.TIER_3),
        ({"draft": "true"}, Tier.TIER_3),
        ({"draft": 1}, Tier.TIER_3),
        ({}, Tier.TIER_3),
    ],
    ids=["draft", "not-draft", "string-true", "int-one", "absent"],
)
def test_a_pull_request_is_gated_by_whether_it_is_a_draft(shipped, arguments, expected):
    """A draft notifies nobody. A non-draft requests review from real people,
    which is the same rule applied to github_create_issue.

    `string-true` and `int-one` are the interesting ones: truthiness differs
    between callers and a tier must not turn on which.
    """
    assert classify("github_create_pull_request", arguments, shipped).tier is expected
