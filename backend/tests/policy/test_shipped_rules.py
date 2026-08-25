"""The SHIPPED rule set (T025, FR-010, SC-010).

Not a constructed fixture — the file the product actually ships, at
`.omni-harness/policy/rules.yaml`. If that file and these expectations diverge,
the divergence is the finding.

THE CENTRAL ASSERTION HERE IS ABOUT WHAT MUST **NOT** HAPPEN. Installing the
policy middleware makes every unclassified tool Tier 3 (FR-009). If the shipped
rules do not cover Features 001 and 002, every read-only session-watcher tool
starts demanding confirmation the moment the middleware goes live — a
regression that would look like the gate working.

That window closes at T034. It is asserted here rather than assumed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.policy.classify import classify
from app.policy.config import ConfigLoader
from app.policy.models import Tier

#: The rules that SHIP — in the package, not under .omni-harness/, which is
#: runtime state and gitignored. A shipped rule set that is not in version
#: control does not ship, which is how CI found this.
RULES_FILE = Path(__file__).resolve().parents[2] / "app" / "policy" / "default_rules.yaml"


@pytest.fixture(scope="module")
def shipped():
    if not RULES_FILE.exists():
        pytest.fail(f"the shipped rule set is missing at {RULES_FILE} — with no rules, EVERY tool becomes Tier 3")
    ruleset = ConfigLoader(path=RULES_FILE).load()
    assert not ruleset.unreadable, f"the shipped rule set does not load: {ruleset.error}"
    return ruleset


# ---------------------------------------------------------------------------
# P2: read-only tools from 001 and 002 must NOT start asking
# ---------------------------------------------------------------------------

#: Every tool Features 001 and 002 expose. Read-only by construction — the
#: watcher offers no way to act on a session, and the trigger engine exposes no
#: agent-callable tools at all.
FEATURE_001_TOOLS = ["list_coding_sessions", "get_session_status", "session-watcher_list_coding_sessions"]


@pytest.mark.parametrize("tool", FEATURE_001_TOOLS)
def test_feature_001_tools_do_not_demand_confirmation(shipped, tool):
    """THE P2 ASSERTION. These were Tier 1 before this feature existed and must
    stay Tier 1 after it does.

    A user who could ask "what are my sessions doing?" silently must not
    suddenly be asked to approve it.
    """
    decision = classify(tool, {}, shipped)

    assert decision.tier is Tier.TIER_1, f"{tool} is now {decision.tier.label}. Installing the middleware would make an existing read-only capability demand confirmation — a regression that looks like the gate working. {decision.explain()}"


@pytest.mark.parametrize("tool", FEATURE_001_TOOLS)
def test_feature_001_tools_are_matched_by_a_rule_not_by_luck(shipped, tool):
    """Tier 1 by an explicit rule, not because something else happened to match.

    An unmatched tool is Tier 3, so a Tier 1 answer already implies a rule — but
    asserting the rule exists means a later pattern edit that stops matching
    fails HERE rather than surfacing as a confirmation prompt in production.
    """
    assert classify(tool, {}, shipped).deciding_rule is not None


def test_the_builtin_read_tools_stay_silent(shipped):
    for tool in ("ask_clarification", "view_image", "present_files", "tool_search"):
        assert classify(tool, {}, shipped).tier is Tier.TIER_1, f"{tool} would start asking"


#: Local reads, listings and metadata the lead agent actually has. Enumerated
#: from a built agent on 2026-08-25, not from the rules file — reading the rules
#: to decide what the rules should cover proves nothing.
LOCAL_READS = (
    "ls",
    "glob",
    "grep",
    "read_file",
    "filesystem_directory_tree",
    "filesystem_get_file_info",
    "filesystem_search_files",
    "filesystem_list_directory",
    "filesystem_read_text_file",
)


@pytest.mark.parametrize("tool", LOCAL_READS)
def test_a_local_read_never_asks(shipped, tool):
    """A confirmation prompt for a directory listing is how a person learns to
    approve without reading. Before these rules, 3 of the agent's 39 tools were
    classified and `ls` was Tier 3."""
    assert classify(tool, {}, shipped).tier is Tier.TIER_1, f"{tool} would ask before listing a directory"


#: THE CONTROL. If a glob were widened until it swallowed the world, every
#: assertion above would pass and mean nothing.
LOCAL_MUTATIONS = ("write_file", "str_replace", "filesystem_edit_file", "filesystem_create_directory")


@pytest.mark.parametrize("tool", LOCAL_MUTATIONS)
def test_a_local_write_is_not_silenced_by_the_read_rules(shipped, tool):
    assert classify(tool, {}, shipped).tier is not Tier.TIER_1, f"{tool} became silent"


def test_each_local_read_is_matched_by_a_rule_not_by_the_default(shipped):
    """Tier 1 cannot arrive by accident: the default is Tier 3, so a Tier 1
    result means a rule matched. This asserts the rule is NAMED rather than a
    broad glob that happened to fit."""
    patterns = {r.pattern for r in shipped.rules}
    for tool in ("ls", "glob", "grep", "read_file", "filesystem_directory_tree", "filesystem_get_file_info", "filesystem_search_files"):
        assert tool in patterns, f"{tool} is Tier 1 via a glob rather than its own rule"


# ---------------------------------------------------------------------------
# And the ones that SHOULD ask, do — otherwise the above passes vacuously
# ---------------------------------------------------------------------------


def test_spawning_is_tier_3(shipped):
    """Article II names spawning explicitly. Control for the tests above: if
    everything were Tier 1 they would all pass and mean nothing."""
    assert classify("task", {}, shipped).tier is Tier.TIER_3


def test_deletion_is_tier_3(shipped):
    assert classify("googlecalendar_delete_event", {}, shipped).tier is Tier.TIER_3
    assert classify("filesystem_delete_file", {}, shipped).tier is Tier.TIER_3


def test_an_unknown_tool_is_still_tier_3_under_the_shipped_rules(shipped):
    """FR-009 survives a real rule set. A file with many patterns is exactly
    where an over-broad glob could accidentally cover everything."""
    assert classify("some_tool_nobody_has_written_a_rule_for", {}, shipped).tier is Tier.TIER_3
    assert classify("evil_send_money", {}, shipped).tier is Tier.TIER_3


def test_no_pattern_is_so_broad_it_swallows_everything(shipped):
    """Guards the failure where a `*` sneaks in and silently classifies the
    world Tier 1."""
    over_broad = [r for r in shipped.rules if r.pattern in ("*", "**") or r.pattern.startswith("*")]

    assert not over_broad, f"these patterns match everything: {[r.pattern for r in over_broad]}"


# ---------------------------------------------------------------------------
# Workers (FR-014, FR-015)
# ---------------------------------------------------------------------------


def test_email_is_read_and_draft_only(shipped):
    assert classify("gmail_read_email", {}, shipped).tier is Tier.TIER_1
    assert classify("gmail_list_messages", {}, shipped).tier is Tier.TIER_1
    assert classify("gmail_create_draft", {}, shipped).tier is Tier.TIER_2


def test_no_rule_classifies_a_send_capability(shipped):
    """FR-012. Send is ABSENT from the surface, not guarded by a rule.

    A rule for it would be a category error — and, worse, would suggest the
    capability exists and is merely gated.
    """
    send_rules = [r for r in shipped.rules if "send" in r.pattern.lower()]

    assert not send_rules, f"a rule classifies a send capability, which should not be reachable at all: {[r.pattern for r in send_rules]}"


def test_calendar_tiers_match_the_requirement(shipped):
    """FR-015, exactly as written."""
    assert classify("googlecalendar_list_events", {}, shipped).tier is Tier.TIER_1
    assert classify("googlecalendar_freebusy_query", {}, shipped).tier is Tier.TIER_1
    assert classify("googlecalendar_create_event", {}, shipped).tier is Tier.TIER_2
    assert classify("googlecalendar_delete_event", {}, shipped).tier is Tier.TIER_3
    assert classify("googlecalendar_update_event", {}, shipped).tier is Tier.TIER_3
    assert classify("googlecalendar_decline_invitation", {}, shipped).tier is Tier.TIER_3


def test_a_hold_that_emails_other_people_is_tier_3(shipped):
    """The exception earns its place: creating a hold is reversible, but
    inviting people reaches inboxes the assistant cannot un-reach."""
    assert classify("googlecalendar_create_event", {}, shipped).tier is Tier.TIER_2
    assert classify("googlecalendar_create_event", {"send_updates": "all"}, shipped).tier is Tier.TIER_3


def test_the_shipped_expiry_is_the_documented_guess(shipped):
    assert shipped.expires_after_seconds == 14400
