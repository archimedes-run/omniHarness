"""T077 — not talking over the user (FR-016a-c, SC-007, SC-007a-c)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.trigger_engine.destinations.base import QuietDestination
from app.trigger_engine.models import (
    Firing,
    Outcome,
    ReleaseReason,
    TriggerEvent,
    TriggerType,
)
from app.trigger_engine.politeness.interrupt import (
    InterruptQueue,
    is_busy,
    is_thread_busy_error,
)
from app.trigger_engine.politeness.release import Releaser

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def _firing(rid="r1", thread="t1", reply="Session needs you."):
    ev = TriggerEvent(type=TriggerType.WATCHER, event_id=f"e-{rid}", at=NOW)
    return Firing(rule_id=rid, event=ev, prompt="p", thread_id=thread, reply=reply)


def test_busy_is_read_from_the_thread_state() -> None:
    assert is_busy({"status": "busy"})
    assert is_busy({"status": "running"})
    assert not is_busy({"status": "idle"})
    assert not is_busy({})


def test_the_conflict_error_is_the_race_fallback() -> None:
    """Both signals are pull; the error is what catches the gap between them."""
    assert is_thread_busy_error(RuntimeError("thread is already running a task"))
    assert not is_thread_busy_error(RuntimeError("something else"))


def test_a_firing_is_held_while_the_exchange_runs() -> None:
    """SC-007."""
    q = InterruptQueue(max_wait=timedelta(minutes=5))
    f = _firing()
    q.hold(f, NOW)
    assert f.outcome is Outcome.QUEUED
    assert q.due(NOW + timedelta(seconds=30), still_busy=lambda t: True) == []


def test_it_is_released_when_the_exchange_ends() -> None:
    q = InterruptQueue(max_wait=timedelta(minutes=5))
    q.hold(_firing(), NOW)
    ready = q.due(NOW + timedelta(seconds=30), still_busy=lambda t: False)
    assert len(ready) == 1
    assert len(q) == 0


def test_the_bound_releases_an_exchange_that_never_completes() -> None:
    """SC-007a, FR-016b — for a hung run NO completion signal ever arrives, so
    this clause is the only one that will ever fire. Primary path, not a net."""
    q = InterruptQueue(max_wait=timedelta(minutes=5))
    q.hold(_firing(), NOW)
    assert q.due(NOW + timedelta(minutes=4), still_busy=lambda t: True) == []
    ready = q.due(NOW + timedelta(minutes=6), still_busy=lambda t: True)
    assert len(ready) == 1, "a hung exchange held the firing forever"


def test_an_item_is_not_released_twice() -> None:
    q = InterruptQueue(max_wait=timedelta(minutes=5))
    q.hold(_firing(), NOW)
    assert len(q.due(NOW + timedelta(minutes=6), still_busy=lambda t: True)) == 1
    assert q.due(NOW + timedelta(minutes=7), still_busy=lambda t: True) == []


def test_multiple_held_items_release_as_one_message() -> None:
    """SC-007c — through the same release path as quiet hours."""
    q = InterruptQueue(max_wait=timedelta(minutes=5))
    for i in range(3):
        q.hold(_firing(rid=f"r{i}", reply=f"item {i}"), NOW)
    ready = q.due(NOW + timedelta(minutes=6), still_busy=lambda t: True)
    dest = QuietDestination()
    r = Releaser(redact=lambda t: (t, True), still_true=lambda f: True, audit=lambda f, n: None)
    r.release(ready, ReleaseReason.QUEUE_EXPIRED, dest, NOW)
    assert len(dest.delivered) == 1
    for i in range(3):
        assert f"item {i}" in dest.delivered[0]


def test_only_the_finished_thread_releases() -> None:
    q = InterruptQueue(max_wait=timedelta(minutes=5))
    q.hold(_firing(rid="a", thread="busy-thread"), NOW)
    q.hold(_firing(rid="b", thread="free-thread"), NOW)
    ready = q.due(NOW + timedelta(seconds=30), still_busy=lambda t: t == "busy-thread")
    assert [f.rule_id for f in ready] == ["b"]
    assert len(q) == 1
