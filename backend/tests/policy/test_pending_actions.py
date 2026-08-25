"""Durable pending actions, atomic claim, target drift, expiry."""

from __future__ import annotations

import multiprocessing as mp
from datetime import UTC, datetime, timedelta

from app.policy.models import Outcome, PendingAction, Tier
from app.policy.pending import PendingStore, targets_still_match

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


def _action(**overrides) -> PendingAction:
    base = dict(
        plan_text="I will decline 2 meetings",
        tool_name="calendar_decline",
        arguments={"ids": ["a", "b"]},
        targets=["Standup 9am", "Review 2pm"],
        tier_at_statement=Tier.TIER_3,
        expires_at=NOW + timedelta(hours=4),
    )
    base.update(overrides)
    return PendingAction(**base)


def test_a_pending_action_survives_the_process_that_created_it(tmp_path):
    """FR-028. The worker that states a plan is unlikely to be the one that
    receives the answer."""
    PendingStore(directory=tmp_path).save(_action(id="abc123abc123"))

    successor = PendingStore(directory=tmp_path).get("abc123abc123")

    assert successor is not None
    assert successor.targets == ["Standup 9am", "Review 2pm"]
    assert successor.tier_at_statement is Tier.TIER_3


def test_open_actions_excludes_resolved_and_expired(tmp_path):
    store = PendingStore(directory=tmp_path)
    store.save(_action(id="a" * 12))
    store.resolve(store.save(_action(id="b" * 12)), Outcome.DECLINED, "user said no")
    store.save(_action(id="c" * 12, expires_at=NOW - timedelta(minutes=1)))

    open_ids = {a.id for a in store.open_actions(NOW)}

    assert open_ids == {"a" * 12}


# ---------------------------------------------------------------------------
# FR-030 — the claim is atomic
# ---------------------------------------------------------------------------


def test_only_one_claim_succeeds(tmp_path):
    store = PendingStore(directory=tmp_path)
    store.save(_action(id="d" * 12))

    first = store.claim("d" * 12, "worker-1")
    second = store.claim("d" * 12, "worker-2")

    assert first is not None, "the first claim should have succeeded"
    assert first.claimed_by == "worker-1", "claim() must return the action carrying the claim it just wrote"
    assert second is None, "two workers both claimed the same action; a calendar cleanup would run twice"


def _try_claim(directory: str, action_id: str, results, index: int) -> None:
    results[index] = 1 if PendingStore(directory=__import__("pathlib").Path(directory)).claim(action_id, f"worker-{index}") is not None else 0


def test_only_one_claim_succeeds_across_processes(tmp_path):
    """The shape that matters: separate processes, as workers are.

    A single-process test cannot show this — the race needs two OS processes
    reaching the same record at the same moment.
    """
    store = PendingStore(directory=tmp_path)
    store.save(_action(id="e" * 12))

    with mp.Manager() as manager:
        results = manager.list([0] * 4)
        procs = [mp.Process(target=_try_claim, args=(str(tmp_path), "e" * 12, results, i)) for i in range(4)]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=30)
        winners = sum(results)

    assert winners == 1, f"{winners} of 4 workers claimed the same action; exactly 1 must"


# ---------------------------------------------------------------------------
# FR-029 — resolved targets, and drift
# ---------------------------------------------------------------------------


def test_targets_match_regardless_of_order():
    action = _action()

    assert targets_still_match(action, ["Review 2pm", "Standup 9am"])


def test_a_missing_target_is_drift():
    """Confirming a plan to decline two meetings must not execute against one."""
    action = _action()

    assert not targets_still_match(action, ["Standup 9am"])


def test_an_extra_target_is_drift():
    """Nor against three."""
    action = _action()

    assert not targets_still_match(action, ["Standup 9am", "Review 2pm", "New 4pm"])


def test_a_substituted_target_is_drift():
    """Same count, different items — the case a length check would miss."""
    action = _action()

    assert not targets_still_match(action, ["Standup 9am", "Something Else"])


# ---------------------------------------------------------------------------
# FR-019 / SC-020 — expiry, and distinct outcomes
# ---------------------------------------------------------------------------


def test_an_unconfirmed_action_expires_without_executing(tmp_path):
    store = PendingStore(directory=tmp_path)
    store.save(_action(id="f" * 12, expires_at=NOW - timedelta(seconds=1)))

    expired = store.expire_due(NOW)

    assert [a.id for a in expired] == ["f" * 12]
    assert store.get("f" * 12).outcome is Outcome.EXPIRED


def test_expiry_records_why_rather_than_leaving_silence(tmp_path):
    store = PendingStore(directory=tmp_path)
    store.save(_action(id="g" * 12, expires_at=NOW - timedelta(seconds=1)))
    store.expire_due(NOW)

    assert store.get("g" * 12).outcome_reason, "an expired action with no reason is indistinguishable from one that never existed"


def test_decline_expiry_and_ambiguity_are_distinct_outcomes(tmp_path):
    """SC-020. A reviewer reading back needs to know WHY nothing happened."""
    store = PendingStore(directory=tmp_path)
    declined = store.resolve(store.save(_action(id="h" * 12)), Outcome.DECLINED, "user declined")
    unrecognised = store.resolve(store.save(_action(id="i" * 12)), Outcome.UNRECOGNISED, "reply was neither")
    store.save(_action(id="j" * 12, expires_at=NOW - timedelta(seconds=1)))
    store.expire_due(NOW)

    outcomes = {declined.outcome, unrecognised.outcome, store.get("j" * 12).outcome}

    assert outcomes == {Outcome.DECLINED, Outcome.UNRECOGNISED, Outcome.EXPIRED}


def test_a_non_executed_outcome_requires_a_reason(tmp_path):
    import pytest

    with pytest.raises(ValueError, match="requires a reason"):
        _action().resolve(Outcome.DECLINED)
