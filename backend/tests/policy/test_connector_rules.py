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


def test_github_tiers_follow_the_verb(shipped):
    from app.policy.classify import classify

    wrong = []
    for action in ACTIONS["GITHUB"]:
        expected = 1 if action.split("_")[1] in GITHUB_READ_VERBS else 3
        decision = classify(_tool("GITHUB", action), {}, shipped)
        if int(decision.tier) != expected or decision.deciding_rule.pattern != _tool("GITHUB", action):
            wrong.append((action, int(decision.tier), expected))
    assert wrong == [], wrong[:10]


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
