"""T029/T031 — Gate 2: the model is released, and nothing leaves the machine.

"Prove the model got released" is fiddlier than the other two gates, which is
exactly why it earns a real assertion rather than a comment. A weakref that is
still alive after a forced collection means something retained a strong reference
— on the instance, in a closure, in a module cache — and the daemon's idle RAM
budget (Article VI) is being violated invisibly.
"""

from __future__ import annotations

import gc
import weakref

from session_watcher.models import SummaryProvenance
from session_watcher.summarize.mechanical import MechanicalSummarizer
from session_watcher.summarize.on_demand_model import OnDemandModelSummarizer


class FakeModel:
    """Stands in for something large. Identity is what the test tracks."""

    def __init__(self) -> None:
        self.calls = 0

    def summarize(self, texts: list[str]) -> list[str]:
        self.calls += 1
        return [f"model: {t[:40]}" for t in texts]


def test_model_is_released_after_a_batch() -> None:
    """GATE 2. If this fails, something is holding the model resident."""
    created: list[weakref.ref] = []

    def loader() -> FakeModel:
        m = FakeModel()
        created.append(weakref.ref(m))
        return m

    s = OnDemandModelSummarizer(loader=loader)
    out = s.summarize(["did a thing", "did another"])
    assert [o.provenance for o in out] == [SummaryProvenance.MODEL] * 2

    gc.collect()
    assert created, "loader was never called"
    assert created[0]() is None, "the model is still reachable after the batch — something retained a strong reference; Article VI requires load -> summarize -> release"


def test_model_is_not_stored_on_the_instance() -> None:
    """A direct structural check, cheap and independent of gc behaviour."""
    s = OnDemandModelSummarizer(loader=FakeModel)
    s.summarize(["x"])
    holders = [v for v in vars(s).values() if isinstance(v, FakeModel)]
    assert not holders, f"model retained on the summarizer instance: {holders}"


def test_model_is_reloaded_per_batch_not_cached() -> None:
    """Count loader calls, not id()s.

    id() is unusable here precisely BECAUSE release works: CPython happily
    reuses the freed address for the next instance, so two distinct models can
    share an id. Counting invocations tests the property directly.
    """
    calls = 0

    def loader() -> FakeModel:
        nonlocal calls
        calls += 1
        return FakeModel()

    s = OnDemandModelSummarizer(loader=loader)
    s.summarize(["a"])
    s.summarize(["b"])
    assert calls == 2, f"model was cached across batches (loader called {calls}x)"


def test_loader_failure_degrades_to_mechanical_rather_than_crashing() -> None:
    def boom() -> FakeModel:
        raise RuntimeError("no model on this machine")

    out = OnDemandModelSummarizer(loader=boom).summarize(["ran the suite. all green."])
    assert len(out) == 1
    assert out[0].provenance is SummaryProvenance.MECHANICAL
    assert out[0].text


def test_length_mismatch_from_model_falls_back() -> None:
    class Broken:
        def summarize(self, texts):
            return ["only one"]

    out = OnDemandModelSummarizer(loader=Broken).summarize(["a", "b", "c"])
    assert len(out) == 3
    assert all(o.provenance is SummaryProvenance.MECHANICAL for o in out)


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
