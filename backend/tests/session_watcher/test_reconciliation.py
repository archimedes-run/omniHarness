"""T040 — sleep/wake and missed events (FR-024, FR-022, SC-006).

watchdog is the fast path, not the source of truth. These tests cover the cases
where events never arrive at all: FSEvents coalescing under load, and a laptop
that slept through the whole window.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from session_watcher.watcher import Reconciler, WatchConfig

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
CFG = WatchConfig(reconcile_interval_s=30, debounce_s=0.5)


def test_first_sweep_is_always_due() -> None:
    assert Reconciler(config=CFG).due(NOW)


def test_change_event_triggers_a_sweep_after_debounce() -> None:
    r = Reconciler(config=CFG)
    r.note_swept(NOW)
    r.note_change()
    assert not r.due(NOW + timedelta(milliseconds=100))
    assert r.due(NOW + timedelta(seconds=1))


def test_sweep_happens_without_any_event_at_all() -> None:
    """THE property that makes a dropped event survivable.

    No note_change() is ever called here — as when FSEvents coalesces events away
    or the machine was asleep. The unconditional interval re-establishes truth.
    """
    r = Reconciler(config=CFG)
    r.note_swept(NOW)
    assert not r.due(NOW + timedelta(seconds=10))
    assert r.due(NOW + timedelta(seconds=31))


def test_sleep_wake_gap_is_detected() -> None:
    r = Reconciler(config=CFG)
    r.note_swept(NOW)
    assert r.detect_gap(NOW + timedelta(seconds=60)) is None
    gap = r.detect_gap(NOW + timedelta(hours=8))
    assert gap is not None and gap > timedelta(hours=7)


def test_sweeping_clears_the_dirty_flag() -> None:
    r = Reconciler(config=CFG)
    r.note_swept(NOW)
    r.note_change()
    assert r.due(NOW + timedelta(seconds=1))
    r.note_swept(NOW + timedelta(seconds=1))
    assert not r.due(NOW + timedelta(seconds=2))


def test_no_gap_reported_before_the_first_sweep() -> None:
    assert Reconciler(config=CFG).detect_gap(NOW) is None
