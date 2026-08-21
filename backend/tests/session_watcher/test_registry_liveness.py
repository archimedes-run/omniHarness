"""T025 — registry liveness and the tri-state (FR-011a, FR-024a, SC-004e).

The assertion that matters most in this file is the negative one: an empty
registry from a dead watcher must never be reportable as "no sessions running".
Everything else here supports that.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from session_watcher.models import IdleReason, Session, SessionState
from session_watcher.registry import Observability, RegistryConfig, SessionRegistry

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


def _session(sid="s1", project="proj", state=SessionState.WORKING, reason=None):
    return Session(
        session_id=sid,
        project=project,
        state=state,
        idle_reason=reason,
        started_at=NOW - timedelta(hours=1),
        last_activity_at=NOW - timedelta(minutes=1),
    )


def test_never_observed_is_distinct_from_empty_and_live() -> None:
    """Three conditions, three values. This is FR-011a in one assertion."""
    reg = SessionRegistry()
    assert reg.observability(NOW) is Observability.NEVER_OBSERVED
    assert reg.is_empty

    reg.replace_all([], NOW)  # a real sweep that genuinely found nothing
    assert reg.observability(NOW) is Observability.LIVE
    assert reg.is_empty  # empty AND live — "nothing running" is now truthful


def test_stale_after_threshold() -> None:
    reg = SessionRegistry(config=RegistryConfig(staleness_threshold_s=90))
    reg.replace_all([_session()], NOW)
    assert reg.observability(NOW + timedelta(seconds=89)) is Observability.LIVE
    assert reg.observability(NOW + timedelta(seconds=91)) is Observability.STALE


def test_two_missed_heartbeats_tolerated_before_stale() -> None:
    """Defaults: beat every 30s, stale at 90s — two misses survive a hiccup."""
    reg = SessionRegistry()
    reg.replace_all([_session()], NOW)
    assert reg.observability(NOW + timedelta(seconds=60)) is Observability.LIVE


def test_dead_watcher_with_sessions_running_is_not_reportable_as_empty() -> None:
    """SC-004e — THE false negative this whole mechanism exists to prevent."""
    reg = SessionRegistry()
    reg.replace_all([_session()], NOW)
    later = NOW + timedelta(minutes=20)  # watcher died 20 minutes ago
    assert reg.observability(later) is Observability.STALE
    assert not reg.is_observable(later)
    assert reg.staleness_seconds(later) == 1200


def test_staleness_sentinel_distinguishes_never_seen_from_zero_seconds() -> None:
    """0 would read as 'perfectly fresh'. Never-observed is not fresh."""
    assert SessionRegistry().staleness_seconds(NOW) == -1


def test_replace_all_beats_and_updates_together() -> None:
    """Neither half alone is a state we want representable."""
    reg = SessionRegistry()
    reg.replace_all([_session(sid="a")], NOW)
    assert reg.last_heartbeat_at == NOW
    reg.replace_all([_session(sid="b")], NOW + timedelta(seconds=30))
    assert set(reg.sessions) == {"b"}
    assert reg.last_heartbeat_at == NOW + timedelta(seconds=30)


def test_lookup_by_id_and_by_project() -> None:
    reg = SessionRegistry()
    reg.replace_all([_session(sid="abc123", project="darcy-repo@main")], NOW)
    assert reg.get("abc123") is not None
    assert reg.get("darcy-repo@main") is not None
    assert reg.get("darcy-repo") is not None  # tolerate the branch suffix
    assert reg.get("no-such-project") is None


def test_ambiguous_project_returns_multiple_for_the_caller_to_ask_about() -> None:
    """FR-017: two matches means ask, never pick."""
    reg = SessionRegistry()
    reg.replace_all(
        [_session(sid="a", project="Entangle@main"), _session(sid="b", project="Entangle@v2")],
        NOW,
    )
    assert len(reg.match_project("Entangle")) == 2
    assert reg.get("Entangle") is None  # refuses to choose


def test_sessions_ordered_by_recency() -> None:
    reg = SessionRegistry()
    old = _session(sid="old")
    old.last_activity_at = NOW - timedelta(days=3)
    reg.replace_all([old, _session(sid="new")], NOW)
    assert [s.session_id for s in reg.all_sessions()] == ["new", "old"]


def test_completed_and_stalled_both_survive_in_the_registry() -> None:
    reg = SessionRegistry()
    reg.replace_all(
        [
            _session(sid="done", state=SessionState.IDLE, reason=IdleReason.COMPLETED),
            _session(sid="killed", state=SessionState.IDLE, reason=IdleReason.STALLED),
        ],
        NOW,
    )
    reasons = {s.session_id: s.idle_reason for s in reg.all_sessions()}
    assert reasons["done"] is IdleReason.COMPLETED
    assert reasons["killed"] is IdleReason.STALLED
