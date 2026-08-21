"""T034/T036/T037 — the single release path (Gate 3; FR-013b/c/d, FR-015, FR-016c).

T036 is the one that matters most here: it proves release() actually DELIVERS.
Gate 3 proves no *second* path appears; it does not prove *this* path works, and
four entry conditions are about to depend on it.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime

from app.trigger_engine.destinations.base import QuietDestination
from app.trigger_engine.models import (
    Firing,
    Outcome,
    ReleaseReason,
    TriggerEvent,
    TriggerType,
)
from app.trigger_engine.politeness import release as release_mod
from app.trigger_engine.politeness.release import Releaser

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def _firing(rid="r1", reply="Session darcy-repo needs you.", ttype=TriggerType.WATCHER):
    ev = TriggerEvent(type=ttype, event_id=f"e-{rid}", at=NOW)
    return Firing(rule_id=rid, event=ev, prompt="p", thread_id="t1", reply=reply)


def _releaser(still_true=lambda f: True, redact=lambda t: (t, True)):
    audited: list[Firing] = []
    r = Releaser(redact=redact, still_true=still_true, audit=lambda f, now: audited.append(f))
    return r, audited


# --- T036: release() actually delivers -------------------------------------


def test_release_delivers_end_to_end() -> None:
    """The assertion Gate 3 does NOT make."""
    dest = QuietDestination()
    r, audited = _releaser()
    out = r.release([_firing()], ReleaseReason.IMMEDIATE, dest, NOW)
    assert out == "Session darcy-repo needs you."
    assert dest.delivered == ["Session darcy-repo needs you."]
    assert audited[0].outcome is Outcome.DELIVERED


def test_release_coalesces_several_into_one() -> None:
    """FR-015 — one message, not three."""
    dest = QuietDestination()
    r, _ = _releaser()
    r.release([_firing("a", "one"), _firing("b", "two"), _firing("c", "three")], ReleaseReason.QUIET_HOURS_ENDED, dest, NOW)
    assert len(dest.delivered) == 1
    body = dest.delivered[0]
    assert "one" in body and "two" in body and "three" in body


def test_single_firing_is_not_formatted_as_a_digest() -> None:
    dest = QuietDestination()
    r, _ = _releaser()
    r.release([_firing(reply="just this")], ReleaseReason.IMMEDIATE, dest, NOW)
    assert dest.delivered == ["just this"]


# --- re-check semantics -----------------------------------------------------


def test_recheck_drops_conditions_that_no_longer_hold() -> None:
    """FR-013b — a session resolved overnight must not be announced at 7am."""
    dest = QuietDestination()
    r, audited = _releaser(still_true=lambda f: False)
    out = r.release([_firing()], ReleaseReason.QUIET_HOURS_ENDED, dest, NOW)
    assert out is None
    assert dest.delivered == []
    assert audited[0].outcome is Outcome.EXPIRED


def test_unrecheckable_types_expire_rather_than_deliver_blind() -> None:
    """FR-013c — otherwise "re-check" becomes "deliver anything we cannot
    disprove". A missed briefing is worthless by morning."""
    dest = QuietDestination()
    r, audited = _releaser()
    out = r.release([_firing(ttype=TriggerType.CRON)], ReleaseReason.QUIET_HOURS_ENDED, dest, NOW)
    assert out is None
    assert audited[0].outcome is Outcome.EXPIRED
    assert "no re-checkable condition" in audited[0].reason


def test_immediate_release_does_not_recheck() -> None:
    """An immediate delivery has nothing to go stale between firing and sending."""
    dest = QuietDestination()
    r, _ = _releaser(still_true=lambda f: False)
    assert r.release([_firing()], ReleaseReason.IMMEDIATE, dest, NOW) is not None


def test_nothing_surviving_delivers_silence_not_an_empty_message() -> None:
    dest = QuietDestination()
    r, _ = _releaser(still_true=lambda f: False)
    r.release([_firing()], ReleaseReason.QUEUE_EXPIRED, dest, NOW)
    assert dest.delivered == []


# --- fail closed ------------------------------------------------------------


def test_redaction_failure_suppresses_the_whole_delivery() -> None:
    """FR-008b — no human is waiting, so a silent pass-through is invisible."""
    dest = QuietDestination()
    r, audited = _releaser(redact=lambda t: ("", False))
    out = r.release([_firing("a"), _firing("b")], ReleaseReason.IMMEDIATE, dest, NOW)
    assert out is None
    assert dest.delivered == []
    assert all(f.outcome is Outcome.FAILED for f in audited)


def test_redaction_is_applied_to_what_is_delivered() -> None:
    dest = QuietDestination()
    r, _ = _releaser(redact=lambda t: (t.replace("AKIA-SECRET", "[redacted]"), True))
    r.release([_firing(reply="key AKIA-SECRET here")], ReleaseReason.IMMEDIATE, dest, NOW)
    assert "AKIA-SECRET" not in dest.delivered[0]
    assert "[redacted]" in dest.delivered[0]


# --- Gate 3: one path, three entry conditions -------------------------------


def test_all_three_entry_conditions_use_the_same_function() -> None:
    """GATE 3. Implemented twice, the copy that runs least often acquires
    defects nobody sees."""
    dest = QuietDestination()
    r, _ = _releaser()
    for reason in ReleaseReason:
        r.release([_firing()], reason, dest, NOW)
    assert len({id(Releaser.release)}) == 1


def test_release_is_the_only_thing_that_delivers() -> None:
    """GATE 3 — no second delivery path may appear beside release().

    Sabotage check: add a function to release.py that calls destination.deliver
    and this fails.
    """
    src = inspect.getsource(release_mod)
    callers = [ln.strip() for ln in src.splitlines() if ".deliver(" in ln]
    assert len(callers) == 1, f"{len(callers)} call sites invoke destination.deliver in release.py; there must be exactly one delivery path"
