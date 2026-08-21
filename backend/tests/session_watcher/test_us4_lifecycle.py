"""T061-T063 — User Story 4: correctness as sessions come and go (FR-004, FR-005, FR-024)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from session_watcher.adapters.claude_code import ClaudeCodeAdapter
from session_watcher.discovery import Discovery, DiscoveryConfig
from session_watcher.models import IdleReason, Session, SessionState
from session_watcher.record_source import RecordSource
from session_watcher.registry import SessionRegistry
from session_watcher.reply import compose_rollup
from session_watcher.state import StateConfig, resolve
from session_watcher.watcher import Reconciler, WatchConfig

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
CFG = StateConfig(inactivity=timedelta(minutes=5))
WIN = timedelta(hours=24)


def _session(sid, state, reason=None, quiet=1):
    return Session(
        session_id=sid,
        project=f"proj-{sid}",
        state=state,
        idle_reason=reason,
        started_at=NOW - timedelta(hours=2),
        last_activity_at=NOW - timedelta(minutes=quiet),
    )


def test_kill_complete_start_cycle_without_restart() -> None:
    """SC-003 — all three reflected in the next answer, no watcher restart."""
    reg = SessionRegistry()
    reg.replace_all(
        [
            _session("killed", SessionState.WORKING),
            _session("finishing", SessionState.WORKING),
        ],
        NOW,
    )

    later = NOW + timedelta(minutes=10)
    reg.merge(
        [
            _session("killed", SessionState.IDLE, IdleReason.STALLED, quiet=30),
            _session("finishing", SessionState.IDLE, IdleReason.COMPLETED, quiet=8),
            _session("fresh", SessionState.WORKING),
        ],
        later,
    )

    by = {s.session_id: s for s in reg.all_sessions()}
    assert set(by) == {"killed", "finishing", "fresh"}
    assert by["killed"].idle_reason is IdleReason.STALLED
    assert by["finishing"].idle_reason is IdleReason.COMPLETED
    assert by["fresh"].state is SessionState.WORKING


def test_killed_session_is_described_as_possibly_killed_not_finished() -> None:
    """SC-004a — the two must not converge as sessions end."""
    reg = SessionRegistry()
    reg.replace_all([_session("killed", SessionState.IDLE, IdleReason.STALLED, quiet=30)], NOW)
    text = compose_rollup(
        {
            "observable": True,
            "observability": "live",
            "staleness_seconds": 0,
            "sessions": [
                {
                    "session_id": "killed",
                    "project": "proj-killed",
                    "state": "idle",
                    "idle_reason": "stalled",
                    "quiet_seconds": 1800,
                    "elapsed_seconds": 7200,
                    "summary": "",
                    "summary_provenance": "mechanical",
                    "relay_suppressed": False,
                }
            ],
        }
    )
    assert "may have stalled or been killed" in text
    assert "finished" not in text


def test_completed_session_is_retained_not_dropped_when_it_ages_out() -> None:
    """A vanished session reads as 'never existed' — a wronger claim than 'finished'."""
    reg = SessionRegistry()
    reg.replace_all([_session("done", SessionState.IDLE, IdleReason.COMPLETED, quiet=10)], NOW)
    reg.merge([], NOW + timedelta(minutes=1))  # no longer discovered
    assert "done" in reg.sessions
    assert reg.sessions["done"].idle_reason is IdleReason.COMPLETED


def test_non_terminal_sessions_do_not_linger_after_a_sweep_drops_them() -> None:
    """Only TERMINAL state earns retention; a stalled session may yet resume."""
    reg = SessionRegistry()
    reg.replace_all([_session("maybe", SessionState.IDLE, IdleReason.STALLED, quiet=30)], NOW)
    reg.merge([], NOW + timedelta(minutes=1))
    assert "maybe" not in reg.sessions


def test_new_session_appears_without_restart(tmp_session_dir, make_record, ago) -> None:
    """FR-005 — discovered live."""
    root = tmp_session_dir([make_record(at=ago(1), session_id="first")], session_id="first")
    src = RecordSource(root=root)
    disc = Discovery(ClaudeCodeAdapter(src), DiscoveryConfig(window=WIN))
    disc.started_at = datetime.now(UTC) - timedelta(minutes=5)
    assert {r.session_id for r in disc.sweep()} == {"first"}

    tmp_session_dir([make_record(at=ago(0), session_id="second")], session_id="second")
    assert {r.session_id for r in disc.sweep()} == {"first", "second"}


def test_preexisting_midrun_session_is_discovered_not_ignored(tmp_session_dir, make_record, ago) -> None:
    """FR-005b — a session already running when we start must be found."""
    root = tmp_session_dir([make_record(at=ago(30), session_id="preexisting")], session_id="preexisting")
    disc = Discovery(ClaudeCodeAdapter(RecordSource(root=root)), DiscoveryConfig(window=WIN))
    assert {r.session_id for r in disc.sweep()} == {"preexisting"}


def test_sleep_wake_reconciles_without_user_action() -> None:
    """SC-006 — no event ever arrives across the gap; the interval covers it."""
    r = Reconciler(config=WatchConfig(reconcile_interval_s=30))
    r.note_swept(NOW)
    wake = NOW + timedelta(hours=8)
    assert r.detect_gap(wake) is not None
    assert r.due(wake), "a slept-through gap must trigger a sweep"
    r.note_swept(wake)
    assert not r.due(wake + timedelta(seconds=5))


def test_state_reflects_reality_after_wake(tmp_session_dir, make_record, ago) -> None:
    root = tmp_session_dir([make_record(at=ago(600), session_id="slept")], session_id="slept")
    refs = Discovery(ClaudeCodeAdapter(RecordSource(root=root)), DiscoveryConfig(window=timedelta(days=2))).sweep()
    s = resolve(refs[0], now=datetime.now(UTC), config=CFG)
    assert s.state is SessionState.IDLE
    assert s.idle_reason is IdleReason.STALLED
