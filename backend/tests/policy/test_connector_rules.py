"""Composio actions for the toolkits connected on this installation have explicit rules (007).

Since 007 a tool no rule names is refused. GMAIL, GITHUB, GOOGLECALENDAR and
GOOGLEDRIVE have ACTIVE Composio connections on the live stack, so an action of
theirs without a rule would silently stop working for the agent.

The action list is the one the installed SDK ships (composio-core, pinned in
uv.lock): composio/client/enums/action.pyi. Read from disk, never from
Composio's API.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SHIPPED_RULES = Path(__file__).resolve().parents[2] / "app" / "policy" / "default_rules.yaml"
TOOLKITS = ("GMAIL", "GITHUB", "GOOGLECALENDAR", "GOOGLEDRIVE")
GITHUB_READ_VERBS = ("GET", "LIST", "SEARCH", "FETCH", "FIND")


def _sdk_actions() -> dict[str, list[str]]:
    import composio

    stub = Path(composio.__file__).parent / "client" / "enums" / "action.pyi"
    text = stub.read_text(encoding="utf-8")
    out = {}
    for toolkit in TOOLKITS:
        out[toolkit] = sorted(set(re.findall(rf"^\s+({toolkit}_[A-Z0-9_]+): \"Action\"", text, re.MULTILINE)))
    return out


ACTIONS = _sdk_actions()


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


#: A GitHub read whose name contains one of these is about ACCESS, not
#: content, and asks first (decided 2026-10-20). Whole name, any case.
GITHUB_SENSITIVE = ("SECRET", "KEY", "TOKEN", "CREDENTIAL", "WEBHOOK", "ADMIN", "PERMISSION")


def _expected_github_tier(action: str) -> int:
    if action.split("_")[1] not in GITHUB_READ_VERBS:
        return 3
    return 3 if any(word in action.upper() for word in GITHUB_SENSITIVE) else 1


@pytest.mark.parametrize("action", ACTIONS["GITHUB"])
def test_github_tier_follows_the_verb_and_sensitive_reads_ask(shipped, action):
    from app.policy.classify import classify

    decision = classify(_tool("GITHUB", action), {}, shipped)
    assert decision.deciding_rule is not None and decision.deciding_rule.pattern == _tool("GITHUB", action)
    assert int(decision.tier) == _expected_github_tier(action)


def test_the_sensitive_words_catch_what_they_should():
    assert _expected_github_tier("GITHUB_GET_A_REPOSITORY_SECRET") == 3
    assert _expected_github_tier("GITHUB_LIST_DEPLOY_KEYS") == 3
    assert _expected_github_tier("GITHUB_LIST_REPO_ACCESS_BY_TOKEN") == 3
    assert _expected_github_tier("GITHUB_LIST_REPOSITORY_WEBHOOKS") == 3
    assert _expected_github_tier("GITHUB_LIST_COMMITS") == 1
    assert sum(1 for a in ACTIONS["GITHUB"] if _expected_github_tier(a) == 1) > 300


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
