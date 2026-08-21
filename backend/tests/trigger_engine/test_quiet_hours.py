"""T075-T076 — quiet hours (FR-013a-d, FR-014, SC-006, SC-006a-d)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.trigger_engine.destinations.base import QuietDestination
from app.trigger_engine.models import (
    Firing,
    Outcome,
    ReleaseReason,
    TriggerEvent,
    TriggerType,
)
from app.trigger_engine.politeness.quiet_hours import (
    DeferralQueue,
    QuietHours,
    should_suppress,
)
from app.trigger_engine.politeness.release import Releaser

WINDOW = QuietHours(start="22:00", end="07:30")
NIGHT = datetime(2026, 8, 21, 2, 0, tzinfo=UTC)
MORNING = datetime(2026, 8, 21, 7, 45, tzinfo=UTC)


def _firing(rid="r1", ttype=TriggerType.WATCHER, reply="Session needs you."):
    ev = TriggerEvent(type=ttype, event_id=f"e-{rid}", at=NIGHT)
    return Firing(rule_id=rid, event=ev, prompt="p", thread_id="t1", reply=reply)


# --- the window itself -------------------------------------------------------


@pytest.mark.parametrize("hour,inside", [(2, True), (23, True), (7, True), (8, False), (12, False), (21, False)])
def test_a_window_spanning_midnight_is_one_window(hour, inside) -> None:
    at = datetime(2026, 8, 21, hour, 0, tzinfo=UTC)
    assert WINDOW.contains(at) is inside


def test_a_same_day_window_works_too() -> None:
    w = QuietHours(start="13:00", end="14:00")
    assert w.contains(datetime(2026, 8, 21, 13, 30, tzinfo=UTC))
    assert not w.contains(datetime(2026, 8, 21, 15, 0, tzinfo=UTC))


def test_next_end_rolls_to_tomorrow_when_already_past() -> None:
    assert WINDOW.next_end(NIGHT).hour == 7
    assert WINDOW.next_end(MORNING).day == NIGHT.day + 1


# --- suppression and the explicit override -----------------------------------


def test_a_non_urgent_firing_inside_quiet_hours_is_suppressed() -> None:
    """SC-006."""
    suppress, reason = should_suppress(False, WINDOW, NIGHT)
    assert suppress and "quiet hours" in reason


def test_an_urgent_rule_overrides() -> None:
    assert should_suppress(True, WINDOW, NIGHT) == (False, "")


def test_nothing_is_suppressed_outside_the_window() -> None:
    assert should_suppress(False, WINDOW, MORNING) == (False, "")


def test_the_override_is_explicit_only() -> None:
    """FR-014 — no implicit escalation. The decision takes the flag and nothing
    else, so no state can quietly promote a rule."""
    import inspect

    src = inspect.getsource(should_suppress)
    for sneaky in ("state", "severity", "priority", "count", "retries"):
        assert sneaky not in src, f"quiet-hours override consults {sneaky!r}"


# --- deferral, re-check, and release -----------------------------------------


def _releaser(still_true, audited=None):
    audited = audited if audited is not None else []
    return Releaser(redact=lambda t: (t, True), still_true=still_true, audit=lambda f, n: audited.append(f)), audited


def test_a_deferred_watcher_item_still_true_is_delivered_at_release() -> None:
    """SC-006a — the session that blocked overnight is the whole point."""
    q = DeferralQueue()
    q.defer(_firing(), NIGHT, "quiet hours")
    r, _ = _releaser(lambda f: True)
    dest = QuietDestination()
    out = r.release(q.drain(), ReleaseReason.QUIET_HOURS_ENDED, dest, MORNING)
    assert out and dest.delivered


def test_a_deferred_item_that_resolved_overnight_is_not_delivered() -> None:
    """SC-006b — "a session needs you" about something fixed six hours ago
    costs a trip AND trust."""
    q = DeferralQueue()
    q.defer(_firing(), NIGHT, "quiet hours")
    r, audited = _releaser(lambda f: False)
    dest = QuietDestination()
    assert r.release(q.drain(), ReleaseReason.QUIET_HOURS_ENDED, dest, MORNING) is None
    assert dest.delivered == []
    assert audited[0].outcome is Outcome.EXPIRED


def test_a_deferred_cron_item_expires_rather_than_delivering_blind() -> None:
    """SC-006c, FR-013c — a missed briefing is worthless by morning, and
    "re-check" must never become "deliver anything we cannot disprove"."""
    q = DeferralQueue()
    q.defer(_firing(ttype=TriggerType.CRON), NIGHT, "quiet hours")
    r, audited = _releaser(lambda f: True)  # would pass a re-check if it had one
    dest = QuietDestination()
    assert r.release(q.drain(), ReleaseReason.QUIET_HOURS_ENDED, dest, MORNING) is None
    assert audited[0].outcome is Outcome.EXPIRED
    assert "no re-checkable condition" in audited[0].reason


def test_six_survivors_arrive_as_one_message() -> None:
    """SC-006d — a backlog flush arriving as six notifications at 7:30am is the
    behaviour most likely to get the feature muted."""
    q = DeferralQueue()
    for i in range(6):
        q.defer(_firing(rid=f"r{i}", reply=f"item {i}"), NIGHT, "quiet hours")
    r, _ = _releaser(lambda f: True)
    dest = QuietDestination()
    r.release(q.drain(), ReleaseReason.QUIET_HOURS_ENDED, dest, MORNING)
    assert len(dest.delivered) == 1
    for i in range(6):
        assert f"item {i}" in dest.delivered[0]


def test_an_empty_backlog_delivers_nothing_not_an_empty_message() -> None:
    r, _ = _releaser(lambda f: True)
    dest = QuietDestination()
    assert r.release([], ReleaseReason.QUIET_HOURS_ENDED, dest, MORNING) is None
    assert dest.delivered == []


def test_deferred_items_are_held_not_dropped() -> None:
    """FR-013a — deferred, not discarded. The session that blocked at 2am is
    the case the feature exists for."""
    q = DeferralQueue()
    f = _firing()
    q.defer(f, NIGHT, "quiet hours")
    assert len(q) == 1
    assert f.outcome is Outcome.SUPPRESSED and f.reason


def test_suppressed_and_queued_are_distinguishable_in_the_audit() -> None:
    """Found by the enum scan: Outcome.SUPPRESSED was never produced.

    Quiet hours and a mid-exchange hold both delayed delivery, and both recorded
    QUEUED — which loses the distinction an operator most wants when reading
    back a quiet morning: was nothing delivered because of the hour, or because
    I was mid-conversation? The spec always separated them (FR-013 "suppresses",
    FR-016 "queues"); the implementation had not.
    """
    from app.trigger_engine.politeness.interrupt import InterruptQueue

    q = DeferralQueue()
    f1 = _firing("quiet")
    q.defer(f1, NIGHT, "quiet hours 22:00-07:30")

    iq = InterruptQueue()
    f2 = _firing("busy")
    iq.hold(f2, NIGHT)

    assert f1.outcome is Outcome.SUPPRESSED
    assert f2.outcome is Outcome.QUEUED
    assert f1.outcome is not f2.outcome
