"""A disclosure nobody reads is a disclosure that failed.

FOUND IN REAL USE. A user asked for a one-paragraph summary to be written to a
file, and the disclosure reproduced THE ENTIRE FILE after the user had just
read that same paragraph. The notice line names the tools; each record's
details (`sentence()`, shown on click in the web chat) name the specifics
without repeating the payload.
"""

from __future__ import annotations

from app.policy.disclose import DisclosureLedger

LONG = "Based on current public information, " * 20


def test_a_long_argument_is_described_rather_than_repeated():
    ledger = DisclosureLedger()
    record = ledger.record(tool_name="write_file", arguments={"path": "/mnt/user-data/outputs/notes.txt", "content": LONG}, result="ok")
    assert LONG not in record.sentence() and LONG not in ledger.apply("Saved the notes.")
    assert "content=<" in record.sentence() and "chars>" in record.sentence()


def test_short_arguments_stay_verbatim():
    """CONTROL. Eliding everything would pass the test above while removing
    the specifics the details exist to give."""
    record = DisclosureLedger().record(tool_name="write_file", arguments={"path": "/tmp/a.txt"}, result="ok")
    assert "path='/tmp/a.txt'" in record.sentence()


def test_resolved_targets_are_named_in_the_details():
    record = DisclosureLedger().record(tool_name="calendar_decline", arguments={"meetings": ["Standup", "Review"]}, result="ok", targets=("Standup", "Review"))
    assert record.sentence() == "calendar_decline on Standup, Review"


def test_the_notice_is_one_line():
    ledger = DisclosureLedger()
    ledger.record(tool_name="write_file", arguments={"path": "/tmp/a.txt", "content": LONG}, result="ok")
    notice = ledger.apply("Done.").split("\n\n", 1)[1]
    assert "\n" not in notice and notice == "Ran without asking: write_file"
