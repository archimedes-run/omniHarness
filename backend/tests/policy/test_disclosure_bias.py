"""FR-040: the Tier 2 notice is never skipped (owner decision, spec 009 review
H1/H2: the notice is the server's, always).

The earlier coverage check skipped a record when the reply named the tool and
its target. That let a model-written sentence stand in for the system's notice,
and the sentence could later be removed (the trailing-offer removal) or be
wrong. Now NO reply text counts: every recorded action is in the server's
line, whatever the model wrote. These are the old boundary cases, all of which
now append, including the one that used to count as covered.
"""

from __future__ import annotations

import pytest

from app.policy.disclose import NOTICE_PREFIX, DisclosureLedger

TOOL = "calendar_create_hold"
TARGET = "Tue 3pm with Darcy"


def _ledger():
    ledger = DisclosureLedger()
    ledger.record(TOOL, {"slot": TARGET}, "ok", targets=(TARGET,))
    return ledger


@pytest.mark.parametrize(
    "label,reply",
    [
        ("tool and target named (was 'covered')", f"I ran {TOOL} to hold {TARGET}."),
        ("tool only", f"I ran {TOOL}."),
        ("target only", f"I held {TARGET} for you."),
        ("neither", "All set!"),
        ("vague", "I took care of that."),
        ("empty", ""),
        ("denial", "I didn't change anything."),
        ("near miss on the target", f"I ran {TOOL} to hold Tuesday afternoon."),
    ],
)
def test_every_reply_gets_the_server_notice(label, reply):
    out = _ledger().apply(reply)
    assert out.rstrip().endswith(f"{NOTICE_PREFIX} {TOOL} ({TARGET})"), f"{label}: {out!r}"
    assert out.startswith(reply.rstrip()), f"{label}: the model's words were changed"


def test_several_actions_are_one_line_in_first_run_order_with_repeats_counted():
    ledger = DisclosureLedger()
    for tool in ("code_job", "ledger_apply", "write_file", "ledger_apply"):
        ledger.record(tool, {}, "ok")
    out = ledger.apply("Done.")
    assert out == f"Done.\n\n{NOTICE_PREFIX} code_job, ledger_apply ×2, write_file"


def test_nothing_recorded_means_nothing_appended():
    """A Tier 1-only turn must not grow a notice."""
    assert DisclosureLedger().apply("Here are your events.") == "Here are your events."
