"""T044-T046 — User Story 1: the roll-up as the user hears it.

These assert on COMPOSED TEXT, not payloads. Every wording rule in the spec is
about what a person reads; a test that only checks a boolean field can pass while
the sentence it produces is misleading.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from session_watcher.models import IdleReason, Session, SessionState
from session_watcher.registry import Observability, RegistryConfig, SessionRegistry
from session_watcher.reply import compose_rollup, compose_status, humanize
from session_watcher.server import WatcherService

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


def _payload(sessions, *, observable=True, observability="live", staleness=0):
    return {
        "observable": observable,
        "observability": observability,
        "staleness_seconds": staleness,
        "as_of": NOW.isoformat(),
        "sessions": sessions,
    }


def _s(project, state, reason=None, quiet=120, summary="Ran the suite.", **kw):
    d = {
        "session_id": kw.get("sid", "s-" + project),
        "project": project,
        "state": state,
        "idle_reason": reason,
        "quiet_seconds": quiet,
        "elapsed_seconds": 3600,
        "summary": summary,
        "summary_provenance": "mechanical",
        "relay_suppressed": False,
    }
    d.update(kw)
    return d


# --- T044: the live roll-up -------------------------------------------------


def test_live_rollup_gives_one_line_per_session() -> None:
    text = compose_rollup(
        _payload(
            [
                _s("darcy-repo", "working", quiet=90, summary="Running the migration."),
                _s("atlas", "idle", IdleReason.COMPLETED.value, quiet=1200, summary="All 41 tests passed."),
            ]
        )
    )
    assert text.count("•") == 2
    assert "darcy-repo" in text and "atlas" in text
    assert "2 sessions:" in text


def test_working_and_completed_read_differently() -> None:
    """SC-004 — the two must not be phrased alike."""
    text = compose_rollup(
        _payload(
            [
                _s("a", "working", quiet=60),
                _s("b", "idle", IdleReason.COMPLETED.value, quiet=600),
            ]
        )
    )
    assert "working, last activity" in text
    assert "finished" in text


def test_completed_is_stated_as_fact_without_a_hedge() -> None:
    """An OBSERVED end-of-turn. Hedging a fact is its own dishonesty."""
    text = compose_rollup(_payload([_s("a", "idle", IdleReason.COMPLETED.value, quiet=600)]))
    assert "finished 10 minutes ago" in text
    for hedge in ("may have", "looks like", "might"):
        assert hedge not in text


def test_stalled_leads_with_the_hedge_not_the_claim() -> None:
    """FR-016a — inferred from silence, and the sentence must sound inferred."""
    text = compose_rollup(_payload([_s("a", "idle", IdleReason.STALLED.value, quiet=720)]))
    assert "hasn't moved in 12 minutes" in text
    assert "may have stalled or been killed" in text
    assert "finished" not in text


def test_completed_and_stalled_are_never_worded_alike() -> None:
    done = compose_rollup(_payload([_s("a", "idle", IdleReason.COMPLETED.value, quiet=600)]))
    killed = compose_rollup(_payload([_s("a", "idle", IdleReason.STALLED.value, quiet=600)]))
    assert done != killed
    assert "finished" in done and "finished" not in killed


def test_unknown_state_admits_it_plainly() -> None:
    text = compose_rollup(_payload([_s("a", "unknown", quiet=60)]))
    assert "can't tell what state it's in" in text
    assert "finished" not in text and "working" not in text


def test_suppressed_relay_says_so_and_leaks_nothing() -> None:
    text = compose_rollup(_payload([_s("a", "working", summary="AKIA-LEAK-SHOULD-NOT-APPEAR", relay_suppressed=True)]))
    assert "can't safely relay this" in text
    assert "AKIA-LEAK-SHOULD-NOT-APPEAR" not in text


# --- T045: caveat ordering --------------------------------------------------


def test_stale_rollup_leads_with_the_caveat() -> None:
    """FR-011b — a trailing caveat can be acted on before it is heard."""
    text = compose_rollup(
        _payload(
            [_s("darcy-repo", "working", quiet=60)],
            observable=False,
            observability="stale",
            staleness=1200,
        )
    )
    first = text.split("\n")[0]
    assert first.startswith("I haven't seen your sessions")
    assert "20 minutes" in first
    caveat_pos = text.index("haven't seen")
    data_pos = text.index("darcy-repo")
    assert caveat_pos < data_pos, "session data appeared before the health caveat"


def test_stale_rollup_labels_the_data_as_last_known() -> None:
    text = compose_rollup(
        _payload(
            [_s("a", "working")],
            observable=False,
            observability="stale",
            staleness=600,
        )
    )
    assert "As of then" in text
    assert "may be out of date" in text


def test_stale_status_reply_also_leads_with_the_caveat() -> None:
    text = compose_status(
        {
            "observable": False,
            "observability": "stale",
            "staleness_seconds": 900,
            "found": True,
            "ambiguous": False,
            "session": _s("darcy-repo", "working", quiet=60),
        }
    )
    assert text.index("haven't seen") < text.index("darcy-repo")


# --- T046: empty vs unobservable -------------------------------------------


def test_empty_and_observable_may_say_no_sessions_running() -> None:
    """Sayable ONLY because we actually looked."""
    assert compose_rollup(_payload([])) == "No coding sessions are running."


def test_stale_and_empty_never_says_no_sessions_running() -> None:
    """SC-004e — THE false negative. The sentence must be unreachable here."""
    text = compose_rollup(_payload([], observable=False, observability="stale", staleness=1200))
    assert "No coding sessions are running" not in text
    assert "no sessions" not in text.lower()
    assert "haven't seen your sessions" in text


def test_never_observed_never_says_no_sessions_running() -> None:
    text = compose_rollup(_payload([], observable=False, observability="never-observed", staleness=-1))
    assert "No coding sessions are running" not in text
    assert "don't know whether any are running" in text


@pytest.mark.parametrize("obs,stale", [("stale", 1200), ("never-observed", -1)])
def test_unobservable_never_makes_a_claim_about_what_is_running(obs, stale) -> None:
    text = compose_rollup(_payload([], observable=False, observability=obs, staleness=stale))
    assert "can't see" in text or "haven't seen" in text


def test_dead_watcher_with_sessions_running_is_not_reported_as_empty() -> None:
    """End to end through the registry, as SC-004e specifies."""
    reg = SessionRegistry(config=RegistryConfig(staleness_threshold_s=90))
    reg.replace_all(
        [
            Session(
                session_id="live",
                project="darcy-repo",
                state=SessionState.WORKING,
                started_at=NOW - timedelta(hours=1),
                last_activity_at=NOW - timedelta(minutes=1),
            )
        ],
        NOW,
    )
    later = NOW + timedelta(minutes=20)
    assert reg.observability(later) is Observability.STALE
    text = compose_rollup(
        {
            "observable": False,
            "observability": "stale",
            "staleness_seconds": reg.staleness_seconds(later),
            "sessions": [_s("darcy-repo", "working", quiet=1260)],
        }
    )
    assert "No coding sessions" not in text
    assert "darcy-repo" in text


# --- durations --------------------------------------------------------------


@pytest.mark.parametrize(
    "secs,expected",
    [
        (30, "less than a minute"),
        (60, "1 minute"),
        (720, "12 minutes"),
        (3600, "1 hour"),
        (86400 * 3, "3 days"),
        (-1, "an unknown time"),
    ],
)
def test_durations_are_coarse_not_falsely_precise(secs, expected) -> None:
    assert humanize(secs) == expected


def test_service_rollup_composes_without_error(tmp_path) -> None:
    svc = WatcherService(root=tmp_path / "empty")
    svc.refresh(now=NOW)
    assert compose_rollup(svc.list_sessions(now=NOW)) == "No coding sessions are running."
