"""SC-006 — find a slot, hold it, draft an invitation, send NOTHING.

The user-visible point of the feature, and the assertion that carries it is a
negative one: nothing was sent. That is checked against the tool surface rather
than against behaviour, because a behavioural check can only show that a send
did not happen this time.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.policy.classify import classify
from app.policy.config import ConfigLoader
from app.policy.disclose import DisclosureLedger
from app.policy.middleware import PolicyMiddleware
from app.policy.models import Tier
from app.policy.pending import PendingStore

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
RULES = Path(__file__).resolve().parents[2] / "app" / "policy" / "default_rules.yaml"


@pytest.fixture
def middleware(tmp_path):
    return PolicyMiddleware(
        loader=ConfigLoader(path=RULES),
        pending=PendingStore(directory=tmp_path / "pending"),
        ledger=DisclosureLedger(),
        resolve_targets=lambda n, a: [str(a.get("summary") or a.get("q") or n)],
        now=lambda: NOW,
    )


def _request(name, args=None):
    return SimpleNamespace(
        tool_call={"name": name, "args": args or {}, "id": "tc1", "type": "tool_call"},
        tool=SimpleNamespace(name=name),
        state={"messages": []},
        runtime=SimpleNamespace(context={"thread_id": "t1"}),
    )


def test_the_whole_journey_runs_without_a_single_confirmation(middleware):
    """Find a mutual slot, hold it, draft the invitation.

    None of it is Tier 3, which is the design working: the guardrail must not
    make ordinary work feel like an interrogation.
    """
    ran = []

    middleware.wrap_tool_call(_request("googlecalendar_freebusy_query", {"q": "Tue"}), lambda r: ran.append("freebusy") or "[]")
    middleware.wrap_tool_call(_request("googlecalendar_create_event", {"summary": "Hold: Darcy sync"}), lambda r: ran.append("hold") or "created")
    middleware.wrap_tool_call(_request("gmail_create_draft", {"summary": "Invitation"}), lambda r: ran.append("draft") or "drafted")

    assert ran == ["freebusy", "hold", "draft"]
    assert not middleware.pending.open_actions(NOW), "no confirmation should have been required"


def test_the_hold_and_the_draft_are_disclosed(middleware):
    """Tier 2 — they happened, so the user is told."""
    middleware.wrap_tool_call(_request("googlecalendar_create_event", {"summary": "Hold: Darcy sync"}), lambda r: "created")
    middleware.wrap_tool_call(_request("gmail_create_draft", {"summary": "Invitation"}), lambda r: "drafted")

    out = middleware.ledger.apply("Found a slot.")

    assert "googlecalendar_create_event" in out
    assert "gmail_create_draft" in out


def test_the_freebusy_lookup_is_not_disclosed(middleware):
    """Tier 1 — silent. Disclosing reads would bury the changes in noise."""
    middleware.wrap_tool_call(_request("googlecalendar_freebusy_query", {"q": "Tue"}), lambda r: "[]")

    assert middleware.ledger.apply("Found a slot.") == "Found a slot."


def test_nothing_was_sent_because_nothing_can_send():
    """The claim SC-006 actually makes.

    Verified against the configured tool surface, not against this run's
    behaviour: a behavioural check shows only that no send happened THIS time.
    """
    config = json.loads((Path(__file__).resolve().parents[3] / "extensions_config.json").read_text())
    gmail = config["mcpServers"]["gmail"]

    denied = set(gmail["tools"]["deny"])
    assert "send_email" in denied
    assert "send_draft" in denied


def test_inviting_other_people_does_require_confirmation(middleware):
    """The boundary: a hold is reversible, an invitation reaches someone else's
    inbox and is not."""
    ran = []

    result = middleware.wrap_tool_call(
        _request("googlecalendar_create_event", {"summary": "Darcy sync", "send_updates": "all"}),
        lambda r: ran.append(r) or "created",
    )

    assert not ran
    assert "confirm" in result.lower()


def test_the_shipped_rules_are_what_drive_this(middleware):
    """This journey runs against the SHIPPED rule file, not a fixture. If the
    file changes so these tiers change, this test is where it surfaces."""
    ruleset = ConfigLoader(path=RULES).load()

    assert classify("googlecalendar_freebusy_query", {}, ruleset).tier is Tier.TIER_1
    assert classify("googlecalendar_create_event", {}, ruleset).tier is Tier.TIER_2
    assert classify("gmail_create_draft", {}, ruleset).tier is Tier.TIER_2
