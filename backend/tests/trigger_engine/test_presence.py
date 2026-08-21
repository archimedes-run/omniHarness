"""T029 — presence from provenance, never from host idleness (FR-022, FR-023)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.trigger_engine.injector import PROVENANCE_KEY, SYNTHETIC
from app.trigger_engine.presence import PresenceSignal

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def _run(minutes_ago: float, synthetic: bool = False) -> dict:
    r = {"created_at": (NOW - timedelta(minutes=minutes_ago)).isoformat()}
    if synthetic:
        r["metadata"] = {PROVENANCE_KEY: SYNTHETIC}
    return r


def test_presence_comes_from_the_last_user_turn() -> None:
    p = PresenceSignal(threshold=timedelta(minutes=5))
    p.observe_runs([_run(30), _run(2)])
    assert p.is_present(NOW)


def test_absent_when_the_last_user_turn_is_old() -> None:
    p = PresenceSignal(threshold=timedelta(minutes=5))
    p.observe_runs([_run(30)])
    assert not p.is_present(NOW)


def test_our_own_injected_turns_are_not_user_activity() -> None:
    """THE self-referential error this design avoids.

    If the engine's own turns counted, every firing would make the user look
    present — and presence routing would be reporting the engine to itself.
    """
    p = PresenceSignal(threshold=timedelta(minutes=5))
    p.observe_runs([_run(30), _run(1, synthetic=True)])
    assert not p.is_present(NOW), "the engine's own turn was read as user presence"


def test_never_observed_is_not_present() -> None:
    assert not PresenceSignal().is_present(NOW)


def test_presence_is_inspectable_at_runtime() -> None:
    """FR-023 — observable while only remote destinations exist, so adding the
    local one later needs no rework of presence itself."""
    p = PresenceSignal(threshold=timedelta(minutes=5))
    p.observe_runs([_run(1)])
    d = p.describe(NOW)
    assert d["present"] is True
    assert d["threshold_seconds"] == 300
    assert "host idle" in d["source"]


def test_host_idleness_plays_no_part() -> None:
    """FR-022 — the engine runs on an always-on host whose idleness says
    nothing about the user. Asserted structurally: presence depends only on
    the runs it is given."""
    p = PresenceSignal(threshold=timedelta(minutes=5))
    p.observe_runs([_run(1)])
    assert p.is_present(NOW)  # engine host has been idle this whole time
