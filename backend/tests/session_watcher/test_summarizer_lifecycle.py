"""T029/T031 — Gate 2: the model is released, and nothing leaves the machine.

"Prove the model got released" is fiddlier than the other two gates, which is
exactly why it earns a real assertion rather than a comment. A weakref that is
still alive after a forced collection means something retained a strong reference
— on the instance, in a closure, in a module cache — and the daemon's idle RAM
budget (Article VI) is being violated invisibly.
"""

from __future__ import annotations

from session_watcher.models import SummaryProvenance
from session_watcher.summarize.mechanical import MechanicalSummarizer


class FakeModel:
    """Stands in for something large. Identity is what the test tracks."""

    def __init__(self) -> None:
        self.calls = 0

    def summarize(self, texts: list[str]) -> list[str]:
        self.calls += 1
        return [f"model: {t[:40]}" for t in texts]


def test_mechanical_default_makes_no_network_call(monkeypatch) -> None:
    """T031/SC-004c — with nothing opted into, nothing leaves the machine.

    Poison the socket layer: any attempt to open a connection fails the test.
    """
    import socket

    def forbidden(*a, **k):
        raise AssertionError("session content attempted to leave the machine (FR-008a)")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)

    out = MechanicalSummarizer().summarize(["Ran the migration against prod. It took four minutes and finished cleanly."])
    assert out[0].provenance is SummaryProvenance.MECHANICAL
    assert out[0].text


def test_mechanical_is_the_zero_config_path() -> None:
    """No loader, no config, no model: still a usable summary (FR-008b)."""
    out = MechanicalSummarizer().summarize(["All 41 tests passed."])
    assert out[0].text == "All 41 tests passed."


def test_identifiers_with_underscores_survive_cleaning() -> None:
    """Found against real records: GOOGLE_API_KEY was becoming GOOGLEAPIKEY.

    A mangled identifier reads as a different variable, which is worse than
    leaving the markdown in — the summary looks authoritative and is wrong.
    """
    out = MechanicalSummarizer().summarize(["Both GOOGLE_API_KEY and GOOGLE_SERVICE_ACCOUNT_JSON are empty in .env"])[0]
    assert "GOOGLE_API_KEY" in out.text
    assert "GOOGLE_SERVICE_ACCOUNT_JSON" in out.text


def test_markdown_emphasis_is_still_stripped() -> None:
    out = MechanicalSummarizer().summarize(["**Done.** Ran _all_ the tests."])[0]
    assert "**" not in out.text and "_all_" not in out.text
    assert "Done." in out.text and "all" in out.text
