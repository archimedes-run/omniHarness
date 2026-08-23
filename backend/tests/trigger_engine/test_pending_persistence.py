"""Pending firings survive the death of the worker holding them.

Under single-runner election the deferral queue and the coalescing window live
in one worker's memory. Losing them is not a delay — it is a permanent silent
drop, because the fingerprint that suppresses re-firing is written BEFORE
delivery. A firing dying in a dead worker's window is therefore undelivered and
already marked seen, and no successor re-derives it.

These tests assert recovery, and that recovery goes through the normal release
path rather than delivering a burst.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.trigger_engine.models import Firing, Outcome, TriggerEvent, TriggerType
from app.trigger_engine.persistence import PendingStore, from_dict, to_dict
from app.trigger_engine.politeness.coalesce import CoalesceWindow
from app.trigger_engine.politeness.quiet_hours import DeferralQueue

NOW = datetime(2026, 8, 23, 23, 30, tzinfo=UTC)


def _firing(rule_id="a", event_id="e1") -> Firing:
    return Firing(
        rule_id=rule_id,
        event=TriggerEvent(type=TriggerType.CRON, event_id=event_id, at=NOW, fields={"project": "darcy"}),
        prompt="the build finished",
    )


def test_a_firing_round_trips_through_serialisation():
    original = _firing()
    original.thread_id = "t1"
    original.resolve(Outcome.SUPPRESSED, "quiet hours 22:00-07:30")

    restored = from_dict(to_dict(original))

    assert restored.rule_id == original.rule_id
    assert restored.prompt == original.prompt
    assert restored.thread_id == "t1"
    assert restored.outcome is Outcome.SUPPRESSED
    assert restored.reason == "quiet hours 22:00-07:30"
    assert restored.event.event_id == original.event.event_id
    assert restored.event.at == original.event.at
    assert restored.event.fields == {"project": "darcy"}


def test_deferrals_survive_a_successor(tmp_path):
    store = PendingStore(path=tmp_path / "pending.json")
    queue = DeferralQueue(store=store)
    queue.defer(_firing(), NOW, "quiet hours")

    successor = DeferralQueue(store=PendingStore(path=tmp_path / "pending.json"))

    assert len(successor.pending) == 1, "a successor inherited no deferrals; they were dropped"
    assert successor.pending[0].rule_id == "a"


def test_a_partially_filled_window_survives_a_successor(tmp_path):
    store = PendingStore(path=tmp_path / "pending.json")
    window = CoalesceWindow(window=timedelta(seconds=60), store=store)
    window.add(_firing("a", "e1"), NOW)
    window.add(_firing("b", "e2"), NOW)

    successor = CoalesceWindow(window=timedelta(seconds=60), store=PendingStore(path=tmp_path / "pending.json"))

    assert len(successor.pending) == 2
    assert {f.rule_id for f in successor.pending} == {"a", "b"}


def test_a_recovered_window_is_already_open(tmp_path):
    """Otherwise a successor would wait a full window from its own start before
    flushing, adding the outage to the delay."""
    store = PendingStore(path=tmp_path / "pending.json")
    window = CoalesceWindow(window=timedelta(seconds=60), store=store)
    window.add(_firing(), NOW)

    successor = CoalesceWindow(window=timedelta(seconds=60), store=PendingStore(path=tmp_path / "pending.json"))

    assert successor.opened_at is not None
    assert successor.is_due(NOW + timedelta(seconds=61)), "a recovered window never becomes due"


def test_draining_clears_the_durable_copy(tmp_path):
    """A delivered firing must not be re-delivered by the next successor."""
    store = PendingStore(path=tmp_path / "pending.json")
    queue = DeferralQueue(store=store)
    queue.defer(_firing(), NOW, "quiet hours")
    queue.drain()

    successor = DeferralQueue(store=PendingStore(path=tmp_path / "pending.json"))

    assert not successor.pending, "a drained firing came back; it would be delivered twice"


def test_recovered_items_go_through_the_release_path_not_around_it(tmp_path):
    """FR-015/FR-016: recovery restores them to the QUEUE, which the existing
    release path drains under re-check and coalescing.

    Restoring them anywhere else — or delivering them on load — would produce
    exactly the burst of stale messages that quiet hours and coalescing exist
    to prevent.
    """
    store = PendingStore(path=tmp_path / "pending.json")
    queue = DeferralQueue(store=store)
    for i in range(3):
        queue.defer(_firing(f"r{i}", f"e{i}"), NOW, "quiet hours")

    successor = DeferralQueue(store=PendingStore(path=tmp_path / "pending.json"))

    # They are pending, not delivered: nothing left the queue on load.
    assert len(successor.pending) == 3
    assert all(f.outcome is Outcome.SUPPRESSED for f in successor.pending)
    # And they leave only via drain(), which the release path calls.
    assert len(successor.drain()) == 3
    assert not successor.pending


def test_an_unreadable_entry_does_not_strand_the_others(tmp_path):
    """One corrupt record must cost one firing, not all of them."""
    import json

    path = tmp_path / "pending.json"
    good = to_dict(_firing("good", "e1"))
    path.write_text(json.dumps({"quiet_hours": [good, {"rule_id": "broken"}]}))

    recovered = PendingStore(path=path).load("quiet_hours")

    assert len(recovered) == 1
    assert recovered[0].rule_id == "good"


def test_without_a_store_the_queues_still_work(tmp_path):
    """Persistence is opt-in; the unit tests that construct queues directly
    must keep passing without one."""
    queue = DeferralQueue()
    queue.defer(_firing(), NOW, "quiet hours")
    assert len(queue.pending) == 1
    assert len(queue.drain()) == 1

    window = CoalesceWindow(window=timedelta(seconds=60))
    window.add(_firing(), NOW)
    assert len(window.drain()) == 1
