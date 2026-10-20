"""Composio actions for the toolkits connected on this installation have explicit rules (007).

Since 007 a tool no rule names is refused. GMAIL, GITHUB, GOOGLECALENDAR and
GOOGLEDRIVE have ACTIVE Composio connections on the live stack, so an action of
theirs without a rule would silently stop working for the agent.

The action list is the one the installed SDK ships (composio-core, pinned in
uv.lock): composio/client/enums/action.pyi. Read from disk, never from
Composio's API.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from github_connector_policy import SENSITIVE_WORDS, github_tier, is_sensitive, regenerate, rules_in_file, sdk_actions  # noqa: E402

SHIPPED_RULES = Path(__file__).resolve().parents[2] / "app" / "policy" / "default_rules.yaml"
TOOLKITS = ("GMAIL", "GITHUB", "GOOGLECALENDAR", "GOOGLEDRIVE")


ACTIONS = {toolkit: sdk_actions(toolkit) for toolkit in TOOLKITS}


def _tool(toolkit: str, action: str) -> str:
    """As connector_tools names it: server `connector-<slug>`, adapter prefix `<server>_`."""
    return f"connector-{toolkit.lower()}_{action}"


@pytest.fixture(scope="module")
def shipped():
    from app.policy.config import ConfigLoader

    ruleset = ConfigLoader(path=SHIPPED_RULES).load()
    assert not ruleset.unreadable, ruleset.error
    return ruleset


def test_the_sdk_list_was_found():
    # A moved or renamed stub would make every assertion below vacuous.
    assert len(ACTIONS["GITHUB"]) > 900 and len(ACTIONS["GMAIL"]) >= 15
    assert len(ACTIONS["GOOGLECALENDAR"]) >= 10 and len(ACTIONS["GOOGLEDRIVE"]) >= 10


#: Sending email is absent, not gated (FR-012): these stay refused.
SENDS = frozenset({"connector-gmail_GMAIL_SEND_EMAIL", "connector-gmail_GMAIL_REPLY_TO_THREAD"})


@pytest.mark.parametrize("tool", [_tool(tk, a) for tk in TOOLKITS for a in ACTIONS[tk] if _tool(tk, a) not in SENDS])
def test_every_connected_toolkit_action_has_an_explicit_rule(shipped, tool):
    from app.policy.classify import classify

    decision = classify(tool, {}, shipped)
    assert not decision.refused and decision.deciding_rule is not None, f"{tool} has no rule: it would be refused"


@pytest.mark.parametrize("action", ACTIONS["GITHUB"])
def test_github_tier_follows_the_verb_and_sensitive_reads_ask(shipped, action):
    from app.policy.classify import classify

    decision = classify(_tool("GITHUB", action), {}, shipped)
    assert decision.deciding_rule is not None and decision.deciding_rule.pattern == _tool("GITHUB", action)
    assert int(decision.tier) == github_tier(action)


@pytest.mark.parametrize("action", [a for a in ACTIONS["GITHUB"] if is_sensitive(a)])
def test_a_github_action_naming_a_sensitive_word_asks_first(shipped, action):
    """Any action naming SECRET, KEY, TOKEN, CREDENTIAL, WEBHOOK, ADMIN,
    PERMISSION or VARIABLE (SENSITIVE_WORDS) is Tier 3, read or not."""
    from app.policy.classify import classify
    from app.policy.models import Tier

    assert classify(_tool("GITHUB", action), {}, shipped).tier is Tier.TIER_3


def test_the_sensitive_words_catch_what_they_should():
    assert "VARIABLE" in SENSITIVE_WORDS
    for action in (
        "GITHUB_GET_A_REPOSITORY_SECRET",
        "GITHUB_LIST_DEPLOY_KEYS",
        "GITHUB_LIST_REPO_ACCESS_BY_TOKEN",
        "GITHUB_LIST_REPOSITORY_WEBHOOKS",
        "GITHUB_GET_AN_ENVIRONMENT_VARIABLE",
        "GITHUB_GET_AN_ORGANIZATION_VARIABLE",
        "GITHUB_GET_A_REPOSITORY_VARIABLE",
        "GITHUB_LIST_ENVIRONMENT_VARIABLES",
        "GITHUB_LIST_ORGANIZATION_VARIABLES",
        "GITHUB_LIST_REPOSITORY_VARIABLES",
        "GITHUB_LIST_REPOSITORY_ORGANIZATION_VARIABLES",
        "GITHUB_LIST_SELECTED_REPOSITORIES_FOR_AN_ORGANIZATION_VARIABLE",
    ):
        assert action in ACTIONS["GITHUB"], f"{action} is not in the SDK list"
        assert github_tier(action) == 3, action
    assert github_tier("GITHUB_LIST_COMMITS") == 1
    assert sum(1 for a in ACTIONS["GITHUB"] if github_tier(a) == 1) > 300


def test_the_rules_file_is_what_the_generator_writes():
    """The GitHub lines in default_rules.yaml are exactly the generated ones,
    so the word list cannot drift from the file."""
    text = SHIPPED_RULES.read_text(encoding="utf-8")
    assert regenerate(text, ACTIONS["GITHUB"]) == text, "run tests/policy/github_connector_policy.py"
    assert [a for a, _ in rules_in_file(text)] == ACTIONS["GITHUB"]


def test_drive_download_is_disclosed_not_silent(shipped):
    """No local evidence says it returns content without writing a file."""
    from app.policy.classify import classify
    from app.policy.models import Tier

    assert classify("connector-googledrive_GOOGLEDRIVE_DOWNLOAD_FILE", {}, shipped).tier is Tier.TIER_2


@pytest.mark.parametrize(
    "tool",
    [
        "connector-googledrive_GOOGLEDRIVE_ADD_FILE_SHARING_PREFERENCE",
        "connector-googledrive_GOOGLEDRIVE_DELETE_FOLDER_OR_FILE",
        "connector-googlecalendar_GOOGLECALENDAR_REMOVE_ATTENDEE",
        "connector-github_GITHUB_MERGE_A_PULL_REQUEST",
        "connector-github_GITHUB_CREATE_AN_ISSUE_COMMENT",
    ],
)
def test_sends_shares_deletes_and_merges_ask_first(shipped, tool):
    from app.policy.classify import classify
    from app.policy.models import Tier

    assert classify(tool, {}, shipped).tier is Tier.TIER_3


@pytest.mark.parametrize("tool", sorted(SENDS))
def test_sending_email_is_refused_not_gated(shipped, tool):
    from app.policy.classify import classify

    assert classify(tool, {}, shipped).refused


def test_an_action_newer_than_the_sdk_list_is_refused_not_defaulted(shipped):
    from app.policy.classify import classify

    assert classify("connector-github_GITHUB_SOME_ACTION_ADDED_NEXT_YEAR", {}, shipped).refused
