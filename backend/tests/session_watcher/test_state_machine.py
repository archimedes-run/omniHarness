"""T020-T022 — completed vs stalled vs unknown (SC-004a, SC-004b, FR-006).

The distinction under test is epistemic, not cosmetic. COMPLETED is a fact we
observed; STALLED is an inference from silence; UNKNOWN is an admission we could
not read the records at all. Collapsing any two of them produces confident
statements the watcher has not earned, which Article X treats as a defect.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from session_watcher.adapters.base import ParsedRecord, SessionRef
from session_watcher.models import EventKind, IdleReason, SessionState
from session_watcher.state import StateConfig, resolve

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
CFG = StateConfig(inactivity=timedelta(minutes=5))


def _rec(minutes_ago: float, *, raw_type="assistant", stop_reason=None, text="working"):
    return ParsedRecord(
        session_id="s1",
        at=NOW - timedelta(minutes=minutes_ago),
        kind=EventKind.PROGRESS,
        project="proj",
        text=text,
        raw_type=raw_type,
        stop_reason=stop_reason,
    )


def _ref(records):
    return SessionRef(session_id="s1", project="proj", path=None, records=records)


def test_end_of_turn_marker_yields_completed() -> None:
    s = resolve(_ref([_rec(60), _rec(30, stop_reason="end_turn")]), now=NOW, config=CFG)
    assert s.state is SessionState.IDLE
    assert s.idle_reason is IdleReason.COMPLETED


def test_killed_without_marker_yields_stalled() -> None:
    """Last record is a tool_use pause that never returned — killed mid-work."""
    s = resolve(_ref([_rec(60), _rec(30, stop_reason="tool_use")]), now=NOW, config=CFG)
    assert s.state is SessionState.IDLE
    assert s.idle_reason is IdleReason.STALLED


def test_completed_and_stalled_are_never_conflated() -> None:
    done = resolve(_ref([_rec(30, stop_reason="end_turn")]), now=NOW, config=CFG)
    killed = resolve(_ref([_rec(30, stop_reason="tool_use")]), now=NOW, config=CFG)
    assert done.state is killed.state is SessionState.IDLE
    assert done.idle_reason is not killed.idle_reason


def test_marker_beats_timeout_even_when_both_apply() -> None:
    """THE ordering invariant (FR-006a): marker first, time second.

    A session that finished cleanly hours ago satisfies the timeout too. If the
    clock were checked first it would be reported as possibly-killed forever —
    downgrading an observation to an inference, which is the precise failure the
    ordering prevents.
    """
    long_done = resolve(_ref([_rec(600, stop_reason="end_turn")]), now=NOW, config=CFG)
    assert long_done.idle_reason is IdleReason.COMPLETED, "timeout overrode an observed end-of-turn marker; marker must win (FR-006a)"


def test_quiet_but_within_timeout_is_still_working() -> None:
    """SC-004b: long builds and slow suites legitimately go quiet."""
    s = resolve(_ref([_rec(2, stop_reason="tool_use")]), now=NOW, config=CFG)
    assert s.state is SessionState.WORKING
    assert s.idle_reason is None


def test_inactivity_period_is_configurable() -> None:
    """FR-006b: the default is a starting value, not a law."""
    recs = [_rec(20, stop_reason="tool_use")]
    patient = resolve(_ref(recs), now=NOW, config=StateConfig(inactivity=timedelta(hours=1)))
    impatient = resolve(_ref(recs), now=NOW, config=StateConfig(inactivity=timedelta(minutes=1)))
    assert patient.state is SessionState.WORKING
    assert impatient.idle_reason is IdleReason.STALLED


def test_uninterpretable_records_yield_unknown_not_a_confident_state() -> None:
    """FR-006: unknown means 'could not interpret', not 'nothing happened'."""
    s = resolve(_ref([]), now=NOW, config=CFG)
    assert s.state is SessionState.UNKNOWN
    assert s.idle_reason is None


def test_unknown_is_distinguishable_from_stalled() -> None:
    unknown = resolve(_ref([]), now=NOW, config=CFG)
    stalled = resolve(_ref([_rec(30, stop_reason="tool_use")]), now=NOW, config=CFG)
    assert unknown.state is SessionState.UNKNOWN
    assert stalled.state is SessionState.IDLE
    assert stalled.idle_reason is IdleReason.STALLED
    assert unknown.state is not stalled.state


def test_stalled_is_not_terminal_but_completed_is() -> None:
    """A stalled session may yet resume; dropping it on an inference would be wrong."""
    done = resolve(_ref([_rec(30, stop_reason="end_turn")]), now=NOW, config=CFG)
    stalled = resolve(_ref([_rec(30, stop_reason="tool_use")]), now=NOW, config=CFG)
    assert done.is_terminal
    assert not stalled.is_terminal


def test_last_message_prefers_most_recent_text() -> None:
    s = resolve(
        _ref([_rec(60, text="older"), _rec(30, text="newer", stop_reason="end_turn")]),
        now=NOW,
        config=CFG,
    )
    assert s.last_message == "newer"


def test_state_and_duration_cannot_disagree() -> None:
    """A reply must never pair a state decided at one clock with an age from another.

    Found by walking quickstart against real sessions (T069): the detail reply
    said "hasn't moved in less than a minute; may have stalled or been killed" —
    two claims that cannot both be true. The state had been resolved 8 hours
    forward while the age was computed at the original now.

    Durations are therefore measured from the clock the state was decided with.
    Coherence by construction, not by remembering to pass the same `now` twice.
    """
    s = resolve(_ref([_rec(30, stop_reason="tool_use")]), now=NOW, config=CFG)
    assert s.state is SessionState.IDLE and s.idle_reason is IdleReason.STALLED

    # Query with a clock BEHIND the one the state was resolved with.
    behind = NOW - timedelta(hours=8)
    assert s.quiet_seconds(behind) == 30 * 60, "duration drifted from the state's clock"

    # ...and one ahead. Still the state's own clock.
    assert s.quiet_seconds(NOW + timedelta(hours=8)) == 30 * 60


def test_stalled_session_never_reports_a_sub_threshold_quiet_time() -> None:
    """The specific contradiction, asserted directly."""
    s = resolve(_ref([_rec(30, stop_reason="tool_use")]), now=NOW, config=CFG)
    for clock in (NOW - timedelta(hours=8), NOW, NOW + timedelta(days=1)):
        if s.idle_reason is IdleReason.STALLED:
            assert s.quiet_seconds(clock) >= CFG.inactivity.total_seconds()
