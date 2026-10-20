"""The one tool-name normaliser, and that BOTH sides use it (007).

The Calendar MCP server names its tools `create-event`; the rules said
`create_event`. Registration (the tool surface's allow/deny) and rule matching
(classify) must compare names the same way, through the same function, or a
rule and a deny list can silently disagree about which tool they mean.
"""

from __future__ import annotations

from app.policy.classify import classify
from app.policy.config import RuleSet
from app.policy.models import ClassificationRule, Tier
from omniharness.config.extensions_config import McpToolSurface
from omniharness.tools.names import canonical_tool_name


def test_hyphen_underscore_and_case_are_one_name():
    assert canonical_tool_name("googlecalendar_create-event") == "googlecalendar_create_event"
    assert canonical_tool_name("googlecalendar_create_event") == "googlecalendar_create_event"
    assert canonical_tool_name("connector-gmail_GMAIL_FETCH_EMAILS") == "connector_gmail_gmail_fetch_emails"
    assert canonical_tool_name("Session-Watcher_list_coding_sessions") == "session_watcher_list_coding_sessions"


def test_the_server_prefix_is_kept_so_a_server_tool_is_not_the_sandbox_tool():
    # `filesystem_read_file` reads the host through the MCP server; `read_file`
    # reads the sandbox. Stripping the prefix would let one take the other's rule.
    assert canonical_tool_name("filesystem_read_file") != canonical_tool_name("read_file")


def test_glob_metacharacters_survive_so_patterns_normalise_the_same_way():
    assert canonical_tool_name("session-watcher_*") == "session_watcher_*"
    assert canonical_tool_name("gmail_[rl]*") == "gmail_[rl]*"


def test_rule_matching_uses_it():
    rules = RuleSet(rules=(ClassificationRule(pattern="googlecalendar_create_event", tier=Tier.TIER_2),))
    decision = classify("googlecalendar_create-event", {}, rules)
    assert decision.deciding_rule is not None and decision.tier is Tier.TIER_2
    # And from the other side: a hyphenated rule matches an underscored tool.
    rules = RuleSet(rules=(ClassificationRule(pattern="session-watcher_*", tier=Tier.TIER_1),))
    assert classify("session_watcher_get_session_status", {}, rules).tier is Tier.TIER_1


def test_registration_uses_it():
    """The allow/deny surface applied when tools load: a deny written one way
    removes the tool however the server spells it."""
    surface = McpToolSurface(deny=["send_email", "create_event"])
    assert not surface.permits("send-email")
    assert not surface.permits("SEND_EMAIL")
    assert not surface.permits("create-event")
    assert surface.permits("draft_email")
    assert not McpToolSurface(allow=["list-events"]).permits("search_events")
    assert McpToolSurface(allow=["list-events"]).permits("list_events")
