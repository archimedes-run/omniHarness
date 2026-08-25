"""FR-040 — the coverage check is biased toward APPENDING.

Stating the direction is a requirement, because without it the check gets tuned
the wrong way: duplicates are the visible failure and omissions the invisible
one, so anyone adjusting it feels pressure toward not-appending.

THE OPERATIONAL DEFINITION of "uncertain" (T055): a Tier 2 execution counts as
already disclosed ONLY when the reply names the tool's effect AND the specific
resolved target. Anything less is uncertain, and uncertain appends.

Without a stated boundary the bias cannot be tested, and an untestable
acceptance criterion on a disclosure guarantee is the failure shape this project
keeps finding.
"""

from __future__ import annotations

import pytest

from app.policy.disclose import DisclosureLedger

TOOL = "calendar_create_hold"
TARGET = "Tue 3pm with Darcy"


def _ledger():
    ledger = DisclosureLedger()
    ledger.record(TOOL, {"slot": TARGET}, "ok", targets=(TARGET,))
    return ledger


def _appended(reply: str) -> bool:
    ledger = _ledger()
    return ledger.apply(reply) != reply


# ---------------------------------------------------------------------------
# The boundary, stated as cases
# ---------------------------------------------------------------------------


def test_naming_both_the_tool_and_the_target_counts_as_disclosed():
    assert not _appended(f"I ran {TOOL} to hold {TARGET}.")


@pytest.mark.parametrize(
    "label,reply",
    [
        ("tool only", f"I ran {TOOL}."),
        ("target only", f"I held {TARGET} for you."),
        ("neither", "All set!"),
        ("vague", "I took care of that."),
        ("empty", ""),
        ("denial", "I didn't change anything."),
        ("near miss on the target", f"I ran {TOOL} to hold Tuesday afternoon."),
    ],
)
def test_anything_less_than_both_appends(label, reply):
    """Each of these is 'uncertain' by the stated definition, and uncertain
    appends. The near-miss case is the important one: a reply that gestures at
    the right thing without naming it is exactly where a similarity-scoring
    check would drift toward silence."""
    assert _appended(reply), f"{label}: no disclosure was appended"


def test_the_bias_direction_is_toward_appending_not_away():
    """Counts the cases: of the eight replies above, only the one naming both is
    treated as covered. A check tuned the other way would pass several."""
    replies = [
        f"I ran {TOOL} to hold {TARGET}.",
        f"I ran {TOOL}.",
        f"I held {TARGET} for you.",
        "All set!",
        "I took care of that.",
        "",
        "I didn't change anything.",
        f"I ran {TOOL} to hold Tuesday afternoon.",
    ]
    appended = [r for r in replies if _appended(r)]

    assert len(appended) == 7, f"expected 7 of 8 to append; got {len(appended)}"


# ---------------------------------------------------------------------------
# Several actions in one turn
# ---------------------------------------------------------------------------


def test_a_partially_disclosing_reply_gets_the_rest_appended():
    """The realistic failure: the model mentions what it remembers."""
    ledger = DisclosureLedger()
    ledger.record("calendar_create_hold", {}, "ok", targets=("Tue 3pm",))
    ledger.record("calendar_move", {}, "ok", targets=("Review 2pm",))

    out = ledger.apply("I ran calendar_create_hold for Tue 3pm.")

    assert "calendar_move" in out
    assert "Review 2pm" in out
    assert out.count("calendar_create_hold") == 1, "the already-disclosed action must not be repeated"


def test_disclosing_none_of_three_appends_all_three():
    ledger = DisclosureLedger()
    for i in range(3):
        ledger.record(f"tool_{i}", {}, "ok", targets=(f"item {i}",))

    out = ledger.apply("Done.")

    for i in range(3):
        assert f"tool_{i}" in out and f"item {i}" in out


def test_nothing_recorded_means_nothing_appended():
    """A Tier 1-only turn must not grow a disclosure section."""
    assert DisclosureLedger().apply("Here are your events.") == "Here are your events."


def test_a_record_with_no_targets_needs_only_the_tool_named():
    """Where there is no resolved target, the tool IS the whole of the effect —
    demanding a target that does not exist would append forever."""
    ledger = DisclosureLedger()
    ledger.record("sync_now", {}, "ok")

    assert ledger.apply("I ran sync_now.") == "I ran sync_now."
    assert ledger.apply("Done.") != "Done."
