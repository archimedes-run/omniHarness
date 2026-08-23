"""Acceptance: the engine is safe under the REAL worker count.

The suite this replaces ran every politeness mechanism in one process, where
all four are trivially correct. Production runs `uvicorn --workers N`, and
under N workers each mechanism fails differently:

  fingerprints   file-backed, but JsonStore caches on first load and never
                 re-reads -> each worker holds a permanently stale snapshot
  quiet hours    in-memory pending list, per process
  mid-exchange   in-memory queue, per process
  coalescing     per-runner window -> three rules across three workers coalesce
                 into nothing and deliver three messages

Election working and coalescing being correct are DIFFERENT CLAIMS. Coalescing
is the one that fails silently, so it is tested on its own, across processes,
by counting delivered messages rather than by asserting that one runner won.

The worker count comes from the compose configuration, not from a literal. If
GATEWAY_WORKERS changes, this test follows it — otherwise it tests a number
rather than the property.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.trigger_engine.election import FileLock
from app.trigger_engine.fingerprint import FingerprintStore
from app.trigger_engine.models import Firing, TriggerEvent, TriggerType
from app.trigger_engine.politeness.coalesce import CoalesceWindow

REPO = Path(__file__).resolve().parents[3]
COMPOSE = REPO / "docker" / "docker-compose.yaml"
NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


def gateway_worker_count() -> int:
    """The worker count production actually runs, read from the compose file.

    Deliberately NOT a constant. A hardcoded 4 keeps passing after someone
    raises the count, which is exactly when this test stops being true.
    """
    if not COMPOSE.exists():  # pragma: no cover - repo layout guard
        pytest.skip("compose file not found; cannot determine the real worker count")
    text = COMPOSE.read_text()
    m = re.search(r"--workers\s+\$\{GATEWAY_WORKERS:-(\d+)\}", text)
    if m:
        default = int(m.group(1))
    else:
        m = re.search(r"--workers\s+(\d+)", text)
        if not m:
            pytest.skip("no --workers directive in the compose file")
        default = int(m.group(1))
    # An explicit environment override wins, mirroring what compose would do.
    return int(os.environ.get("GATEWAY_WORKERS", default))


def test_the_worker_count_is_greater_than_one():
    """Pins the premise. If production ever runs a single worker, election is
    unnecessary and this whole file should be reconsidered rather than kept
    passing vacuously."""
    assert gateway_worker_count() > 1, "production now runs a single gateway worker; single-runner election may no longer be needed — revisit rather than deleting these tests"


# ---------------------------------------------------------------------------
# Claim 1: exactly one worker wins the election
# ---------------------------------------------------------------------------


def _contend(lock_path: str, results, index: int) -> None:
    lock = FileLock(Path(lock_path))
    results[index] = 1 if lock.acquire() else 0
    if results[index]:
        # Hold it until the parent has polled every worker, or the lock would
        # be released before the others contend and several could "win".
        import time

        time.sleep(2.0)
        lock.release()


def test_exactly_one_worker_wins_the_election(tmp_path):
    n = gateway_worker_count()
    lock_path = str(tmp_path / "engine.lock")
    with mp.Manager() as manager:
        results = manager.list([0] * n)
        procs = [mp.Process(target=_contend, args=(lock_path, results, i)) for i in range(n)]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=30)
        winners = sum(results)

    assert winners == 1, f"{winners} of {n} workers started an engine; exactly 1 must"


# ---------------------------------------------------------------------------
# Claim 2: coalescing. The one that fails SILENTLY.
# ---------------------------------------------------------------------------


def _fire_three_rules_in_this_process(deliveries, worker_index: int) -> None:
    """Each worker runs its own engine — the pre-election behaviour — and
    coalesces only what it saw itself."""
    window = CoalesceWindow(window=timedelta(seconds=60))
    for rule_id in ("a", "b", "c"):
        if hash((rule_id, worker_index)) % 3 != worker_index % 3:
            continue  # this rule landed on a different worker
        window.add(
            Firing(rule_id=rule_id, event=TriggerEvent(type=TriggerType.CRON, event_id=rule_id, at=NOW), prompt="p"),
            NOW,
        )
    if window.pending:
        deliveries.append(len(window.pending))


def test_three_rules_across_workers_would_deliver_three_messages_without_election(tmp_path):
    """The defect, demonstrated. Not a regression guard — a statement of why
    election exists, so removing it is not mistaken for a simplification."""
    n = gateway_worker_count()
    with mp.Manager() as manager:
        deliveries = manager.list()
        procs = [mp.Process(target=_fire_three_rules_in_this_process, args=(deliveries, i)) for i in range(n)]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=30)
        messages = list(deliveries)

    assert len(messages) > 1, "expected the un-elected case to fan out into several messages; if it no longer does, the coalescing window has become shared and election may not be the only thing holding this together"


def _coalesce_under_election(lock_path: str, deliveries, worker_index: int) -> None:
    """With election, only the lock holder runs a window at all."""
    lock = FileLock(Path(lock_path))
    if not lock.acquire():
        return
    try:
        window = CoalesceWindow(window=timedelta(seconds=60))
        for rule_id in ("a", "b", "c"):
            window.add(
                Firing(rule_id=rule_id, event=TriggerEvent(type=TriggerType.CRON, event_id=rule_id, at=NOW), prompt="p"),
                NOW,
            )
        deliveries.append(len(window.pending))
    finally:
        import time

        time.sleep(1.0)
        lock.release()


def test_three_rules_across_workers_produce_one_message(tmp_path):
    """THE claim. Counted in delivered messages, not in election outcomes."""
    n = gateway_worker_count()
    lock_path = str(tmp_path / "engine.lock")
    with mp.Manager() as manager:
        deliveries = manager.list()
        procs = [mp.Process(target=_coalesce_under_election, args=(lock_path, deliveries, i)) for i in range(n)]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=30)
        messages = list(deliveries)

    assert len(messages) == 1, f"{len(messages)} messages delivered across {n} workers; exactly 1 must be"
    assert messages[0] == 3, f"the single message carried {messages[0]} firings; all 3 must be coalesced into it"


# ---------------------------------------------------------------------------
# Claim 3: fingerprints (no-repetition) under multiple workers
# ---------------------------------------------------------------------------


def _record_fingerprint(store_path: str, lock_path: str, fired, worker_index: int) -> None:
    lock = FileLock(Path(lock_path))
    if not lock.acquire():
        return
    try:
        store = FingerprintStore(path=Path(store_path))
        if not store.seen("event-1"):
            store.record("event-1", NOW)
            fired.append(worker_index)
    finally:
        import time

        time.sleep(1.0)
        lock.release()


def test_an_unchanged_event_fires_once_across_workers(tmp_path):
    """FR-017: re-firing on an unchanged condition is a defect.

    Under N workers without election this fails twice over — each worker's
    JsonStore caches on first load and never re-reads, and seen()->record() is
    a read-modify-write with no lock.
    """
    n = gateway_worker_count()
    store_path, lock_path = str(tmp_path / "fp.json"), str(tmp_path / "engine.lock")
    with mp.Manager() as manager:
        fired = manager.list()
        procs = [mp.Process(target=_record_fingerprint, args=(store_path, lock_path, fired, i)) for i in range(n)]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=30)
        count = len(list(fired))

    assert count == 1, f"the same unchanged event fired {count} times across {n} workers; exactly 1 must"


def test_the_fingerprint_cache_is_the_second_failure(tmp_path):
    """Pins the subtler half, which election hides rather than fixes.

    Two stores on one file: the second caches at first load and never sees the
    first's write. Election makes this harmless because only one store exists —
    but if election is ever replaced by shared state, this must be fixed too.
    """
    path = tmp_path / "fp.json"
    a = FingerprintStore(path=path)
    b = FingerprintStore(path=path)
    b.seen("x")  # force b to load and cache an empty snapshot
    a.record("x", NOW)

    assert a.seen("x")
    assert not b.seen("x"), "the fingerprint store now re-reads from disk. If concurrent access is being relied on instead of election, revisit the read-modify-write race in seen()->record(), which atomic writes do not prevent."


# ---------------------------------------------------------------------------
# Claim 4: what is LOST when the lock holder dies mid-window
# ---------------------------------------------------------------------------


def _die_holding_the_lock(lock_path: str) -> None:
    lock = FileLock(Path(lock_path))
    assert lock.acquire()
    os._exit(1)  # no cleanup, no release call — the OS must do it


def test_the_lock_is_released_when_the_holder_dies(tmp_path):
    """The property that makes flock worth choosing: no lease, no heartbeat, no
    expiry to tune, and no window in which a dead leader is still leader."""
    lock_path = str(tmp_path / "engine.lock")
    p = mp.Process(target=_die_holding_the_lock, args=(lock_path,))
    p.start()
    p.join(timeout=30)

    successor = FileLock(Path(lock_path))
    assert successor.acquire(), "the lock was not released when its holder died; the engine would never restart"
    successor.release()


def test_in_process_state_is_lost_when_the_holder_dies(tmp_path):
    """Documents the accepted loss rather than discovering it in production.

    A successor inherits the durable state (fingerprints, scheduler, thread map,
    audit) and inherits NOTHING of the in-memory state: quiet-hours deferrals
    and a partially-filled coalescing window die with the process.

    Consequence: firings deferred by quiet hours, and firings accumulated in an
    open coalescing window, are dropped — not delayed. They are not re-derived,
    because the fingerprint that suppressed re-firing was already recorded.
    """
    path = tmp_path / "fp.json"
    store = FingerprintStore(path=path)
    window = CoalesceWindow(window=timedelta(seconds=60))
    firing = Firing(rule_id="a", event=TriggerEvent(type=TriggerType.CRON, event_id="e1", at=NOW), prompt="p")
    store.record("e1", NOW)  # durable: survives
    window.add(firing, NOW)  # in-memory: does not

    successor_store = FingerprintStore(path=path)
    successor_window = CoalesceWindow(window=timedelta(seconds=60))

    assert successor_store.seen("e1"), "the fingerprint should survive; it is file-backed"
    assert not successor_window.pending, "the window should be empty; it is in-memory"
    # Together these mean the firing is dropped: suppressed as already-seen, and
    # never delivered. This is the finding to weigh, not a bug in this test.


def test_a_pending_deferral_is_also_lost(tmp_path):
    """Same shape for quiet hours, verified separately because it is a
    different container with a different lifetime."""
    from app.trigger_engine.politeness.quiet_hours import DeferralQueue

    queue = DeferralQueue()
    queue.defer(Firing(rule_id="a", event=TriggerEvent(type=TriggerType.CRON, event_id="e2", at=NOW), prompt="p"), NOW, "quiet hours")
    assert queue.pending, "precondition: something is deferred"

    successor = DeferralQueue()
    assert not successor.pending, "a successor inherits no deferrals"
