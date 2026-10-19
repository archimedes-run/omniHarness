"""Text from outside the assistant passes the redactor before a surface shows it (Feature 004 FR-031, SC-015).

Session summaries, and plans whose wording and targets were drawn from email
and web pages, are content the assistant did not write. Every read surface that
shows them goes through `for_display`, the same redactor every channel uses.

It fails closed, as the redactor's contract requires: if redaction raises, the
text is WITHHELD, never shown unredacted. And the withholding is visible as
such — `withheld=True` and a sentence saying so — because a blank field would
read as "there was nothing there", the false-confidence failure Feature 001's
FR-011a exists to prevent.
"""

from __future__ import annotations

from session_watcher.redaction import Channel, RedactionError, redact

WITHHELD = "Withheld: this could not be safely redacted for display. Check it locally."


def for_display(text: str) -> tuple[str, bool]:
    """(what to show, withheld). Local channel: the page is on this machine."""
    try:
        return redact(text, Channel.LOCAL), False
    except RedactionError:
        return WITHHELD, True


def all_for_display(texts: list[str]) -> tuple[list[str], bool]:
    """Each item redacted; any item that fails is withheld on its own."""
    shown, any_withheld = [], False
    for text in texts:
        out, withheld = for_display(text)
        shown.append(out)
        any_withheld |= withheld
    return shown, any_withheld
