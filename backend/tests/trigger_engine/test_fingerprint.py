"""T015-T017 — event identity (FR-017a/b/c, SC-002/002a/002b/002c)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.trigger_engine.fingerprint import (
    FORBIDDEN_INPUTS,
    FingerprintError,
    FingerprintStore,
    compute,
)
from app.trigger_engine.models import TriggerEvent, TriggerType

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def _ev(question="Should I roll it back?", state="waiting-on-user", eid="sess-1"):
    return TriggerEvent(
        type=TriggerType.WATCHER,
        event_id=eid,
        at=NOW,
        fields={"project": "darcy-repo", "last_message": question},
        fingerprint_inputs={"question": question, "state": state},
    )


def test_same_condition_yields_the_same_fingerprint() -> None:
    assert compute("r1", _ev()) == compute("r1", _ev())


def test_changed_question_is_a_new_event() -> None:
    """SC-002a — blocked, answered, blocked again on something DIFFERENT."""
    assert compute("r1", _ev("Should I roll it back?")) != compute("r1", _ev("Pin the version?"))


def test_different_rules_do_not_share_identity() -> None:
    assert compute("r1", _ev()) != compute("r2", _ev())


@pytest.mark.parametrize("bad", sorted(FORBIDDEN_INPUTS))
def test_drifting_inputs_are_refused(bad) -> None:
    """FR-017b — the failure this refusal prevents is an alert PER CYCLE.

    That is the inverse of the repeat failure and the worse of the two, because
    it is the version that gets the feature muted.
    """
    ev = TriggerEvent(type=TriggerType.WATCHER, event_id="s", at=NOW, fingerprint_inputs={"question": "q", bad: 123})
    with pytest.raises(FingerprintError, match="drift on every evaluation"):
        compute("r1", ev)


def test_unpermitted_input_is_refused() -> None:
    ev = TriggerEvent(type=TriggerType.WATCHER, event_id="s", at=NOW, fingerprint_inputs={"question": "q", "made_up": 1})
    with pytest.raises(FingerprintError, match="not permitted"):
        compute("r1", ev)


def test_one_hundred_evaluations_of_an_unchanged_session_yield_one_firing(tmp_path) -> None:
    """SC-002b — THE assertion that no drifting value crept in.

    Run the identity check as the engine would, a hundred times, against a
    session that has not changed. Exactly one should be new.
    """
    store = FingerprintStore(path=tmp_path / "fp.json")
    fired = 0
    for _ in range(100):
        key = compute("blocked-session", _ev())
        if not store.seen(key):
            store.record(key, NOW)
            fired += 1
    assert fired == 1, f"{fired} firings for one unchanged event — a drifting input is contributing"


def test_answered_then_blocked_again_fires_a_second_time(tmp_path) -> None:
    store = FingerprintStore(path=tmp_path / "fp.json")
    fired = []
    for q in ("Should I roll it back?", "Should I roll it back?", "Pin the version instead?"):
        key = compute("r1", _ev(q))
        if not store.seen(key):
            store.record(key, NOW)
            fired.append(q)
    assert len(fired) == 2


def test_store_survives_a_restart(tmp_path) -> None:
    """Durable: a restart must not re-fire everything already delivered."""
    p = tmp_path / "fp.json"
    key = compute("r1", _ev())
    FingerprintStore(path=p).record(key, NOW)
    assert FingerprintStore(path=p).seen(key)


def test_retention_reset_clears_the_store(tmp_path) -> None:
    """SC-002c — unbounded growth is unacceptable in a shared process."""
    store = FingerprintStore(path=tmp_path / "fp.json", retention=timedelta(days=1))
    store.maybe_reset(NOW)
    for i in range(5):
        store.record(compute("r1", _ev(eid=f"s{i}")), NOW)
    assert store.count() == 5
    assert store.maybe_reset(NOW + timedelta(days=2)) == 5
    assert store.count() == 0


def test_retention_does_not_reset_early(tmp_path) -> None:
    store = FingerprintStore(path=tmp_path / "fp.json", retention=timedelta(days=1))
    store.maybe_reset(NOW)
    store.record(compute("r1", _ev()), NOW)
    assert store.maybe_reset(NOW + timedelta(hours=6)) == 0
    assert store.count() == 1
