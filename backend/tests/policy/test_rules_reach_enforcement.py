"""A rule LOADED FROM THE FILE governs a real decision (T042, Article XI).

THE STRUCTURAL DIFFERENCE THIS DEFENDS AGAINST: every other test in this
directory constructs a `ClassificationRule` — or a `RuleSet` — by hand and hands
it to `classify()`. Production does not. Production reads a YAML file, parses
it, and passes the result to a middleware. Nothing in a hand-constructed test
exercises the seam between those two.

That is the fourth instance in Article XI's own table, and it is not
hypothetical here. Feature 002 had two classes both named `QuietHours` — one
parsed from config, one enforcing suppression — and NOTHING converted between
them. What the user wrote under `quiet_hours:` never reached the code enforcing
it, and every test passed, because each constructed the enforcing type directly.

This test starts from a file on disk and ends at a middleware decision.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.policy.config import ConfigLoader
from app.policy.disclose import DisclosureLedger
from app.policy.middleware import PolicyMiddleware
from app.policy.models import Tier
from app.policy.pending import PendingStore

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)

RULES_ON_DISK = """
policy:
  rules:
    - pattern: "notes_read"
      tier: 1
    - pattern: "notes_append"
      tier: 2
    - pattern: "notes_delete"
      tier: 3
  confirmation:
    expires_after_seconds: 3600
"""


@pytest.fixture
def middleware(tmp_path):
    rules = tmp_path / "policy.yaml"
    rules.write_text(RULES_ON_DISK)  # a FILE, not a constructed object
    return PolicyMiddleware(
        loader=ConfigLoader(path=rules),
        pending=PendingStore(directory=tmp_path / "pending"),
        ledger=DisclosureLedger(),
        resolve_targets=lambda name, args: [args.get("note", "note-1")],
        now=lambda: NOW,
    )


def _request(name, args=None):
    return SimpleNamespace(
        tool_call={"name": name, "args": args or {}, "id": "tc1", "type": "tool_call"},
        tool=SimpleNamespace(name=name),
        state={"messages": []},
        runtime=SimpleNamespace(context={"thread_id": "t1"}),
    )


def test_a_tier_1_rule_from_the_file_lets_the_call_through(middleware):
    ran = []

    result = middleware.wrap_tool_call(_request("notes_read"), lambda r: ran.append(r) or "read-result")

    assert ran, "a Tier 1 rule loaded from disk did not permit the call"
    assert result == "read-result"


def test_a_tier_3_rule_from_the_file_stops_the_call(middleware):
    """The claim that matters. The file said tier 3; the middleware refused."""
    ran = []

    result = middleware.wrap_tool_call(_request("notes_delete", {"note": "quarterly plan"}), lambda r: ran.append(r) or "deleted")

    assert not ran, "a Tier 3 rule loaded from disk did NOT stop the call — the file and the enforcement have diverged"
    assert "confirm" in result.lower()
    assert "quarterly plan" in result, "the stated plan must name the specific target from the resolved arguments"


def test_a_tier_2_rule_from_the_file_runs_and_is_recorded(middleware):
    ran = []

    middleware.wrap_tool_call(_request("notes_append", {"note": "todo"}), lambda r: ran.append(r) or "appended")

    assert ran, "a Tier 2 rule loaded from disk must execute"
    assert len(middleware.ledger.records) == 1, "and must be recorded for disclosure"


def test_editing_the_file_changes_the_decision(middleware, tmp_path):
    """The seam, exercised in the direction that matters.

    If the middleware held a snapshot taken at construction, this would keep
    permitting the call — which is exactly how a config that 'is applied'
    quietly stops being.
    """
    assert middleware.wrap_tool_call(_request("notes_read"), lambda r: "ok") == "ok"

    (tmp_path / "policy.yaml").write_text('policy:\n  rules:\n    - pattern: "notes_read"\n      tier: 3\n')
    ran = []
    middleware.wrap_tool_call(_request("notes_read"), lambda r: ran.append(r) or "ok")

    assert not ran, "the middleware is not reading the file it was given — it is using a stale snapshot"


def test_the_expiry_comes_from_the_file_too(middleware, tmp_path):
    """Not only the rules. A setting that parses and is then ignored is the
    QuietHours shape exactly."""
    middleware.wrap_tool_call(_request("notes_delete", {"note": "x"}), lambda r: "deleted")

    action = middleware.pending.open_actions(NOW)[0]
    assert (action.expires_at - NOW).total_seconds() == 3600, "expires_after_seconds was parsed and then not used"


def test_an_unknown_tool_is_tier_3_through_the_middleware(middleware):
    """FR-009 end to end, not just in the classifier."""
    ran = []

    middleware.wrap_tool_call(_request("some_tool_with_no_rule"), lambda r: ran.append(r) or "ran")

    assert not ran


def test_a_file_that_cannot_be_read_stops_everything(tmp_path):
    """The safe direction, verified through the middleware rather than assumed."""
    middleware = PolicyMiddleware(
        loader=ConfigLoader(path=tmp_path / "absent.yaml"),
        pending=PendingStore(directory=tmp_path / "pending"),
        ledger=DisclosureLedger(),
        now=lambda: NOW,
    )
    ran = []

    middleware.wrap_tool_call(_request("notes_read"), lambda r: ran.append(r) or "ok")

    assert not ran, "with no readable rules every tool must be Tier 3"


def test_the_tiers_are_the_ones_in_the_file_not_defaults(middleware):
    """Guards the failure where a parse succeeds and produces defaults."""
    ruleset = middleware.loader.load()
    from app.policy.classify import classify

    assert classify("notes_read", {}, ruleset).tier is Tier.TIER_1
    assert classify("notes_append", {}, ruleset).tier is Tier.TIER_2
    assert classify("notes_delete", {}, ruleset).tier is Tier.TIER_3
    assert len(ruleset.rules) == 3, "three rules were written; a different count means the file was not what was read"
