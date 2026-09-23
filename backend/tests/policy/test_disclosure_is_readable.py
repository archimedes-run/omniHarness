"""A disclosure nobody reads is a disclosure that failed.

FOUND IN REAL USE. A user asked for a one-paragraph summary to be written to a
file. The write was disclosed — correctly, that was the fix — and the
disclosure reproduced THE ENTIRE FILE:

    Also, for the record:
      - I used write_file with {'description': '...', 'path': '...',
        'content': 'Based on current public information, HackMIT's official
        2026 judging criteria do not appear to be posted yet; ...'}

after the user had just read that same paragraph. FR-040 asks the disclosure to
name the effect and the specifics; it does not ask it to repeat the payload.
"""

from __future__ import annotations

import pytest

from app.policy.disclose import DisclosureLedger

LONG = "Based on current public information, " * 20


@pytest.fixture
def ledger():
    return DisclosureLedger()


def test_a_long_argument_is_described_rather_than_repeated(ledger):
    ledger.record(
        tool_name="write_file",
        arguments={"path": "/mnt/user-data/outputs/notes.txt", "content": LONG},
        result="ok",
    )
    out = ledger.apply("Saved the notes.")

    assert LONG not in out, "the disclosure reproduced the whole payload"
    assert "content=<" in out and "chars>" in out


def test_short_arguments_stay_verbatim(ledger):
    """CONTROL. Eliding everything would pass the test above while removing
    the specifics the disclosure exists to give."""
    ledger.record(tool_name="write_file", arguments={"path": "/tmp/a.txt"}, result="ok")
    out = ledger.apply("Done.")

    assert "path='/tmp/a.txt'" in out


def test_an_unresolved_scope_is_covered_by_naming_the_tool(ledger):
    """Otherwise coverage is unreachable and every Tier 2 action appends.

    `covered()` requires the reply to name every target. Handing it the
    fallback — a repr of the whole call — is something no model will reproduce,
    so the disclosure would append forever however well the assistant wrote.
    """
    ledger.record(tool_name="write_file", arguments={"path": "/tmp/a.txt"}, result="ok", targets=())
    out = ledger.apply("I used write_file to save it to /tmp/a.txt.")

    assert "for the record" not in out.lower(), "the model disclosed it and was appended to anyway"


def test_resolved_targets_must_still_be_named(ledger):
    """The bias stays where FR-040 put it. With REAL targets, a reply that
    names the tool but not the items is not coverage."""
    ledger.record(
        tool_name="calendar_decline",
        arguments={"meetings": ["Standup", "Review"]},
        result="ok",
        targets=("Standup", "Review"),
    )
    out = ledger.apply("I used calendar_decline on some things.")

    assert "for the record" in out.lower()
    assert "Standup" in out
