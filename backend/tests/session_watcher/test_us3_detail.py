"""T058-T059 — User Story 3: one session in detail (FR-012, FR-013, FR-017)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from session_watcher.adapters.base import ParsedRecord, SessionRef
from session_watcher.models import EventKind, IdleReason, Session, SessionState
from session_watcher.registry import SessionRegistry
from session_watcher.reply import compose_status
from session_watcher.server import WatcherService
from session_watcher.state import StateConfig, resolve

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
CFG = StateConfig(inactivity=timedelta(minutes=5))


def _rec(minutes_ago, *, raw_type="assistant", stop_reason=None, text="did a thing"):
    return ParsedRecord(
        session_id="s1",
        at=NOW - timedelta(minutes=minutes_ago),
        kind=EventKind.PROGRESS,
        project="darcy-repo",
        text=text,
        raw_type=raw_type,
        stop_reason=stop_reason,
    )


def _svc(sessions) -> WatcherService:
    svc = WatcherService(root=None)  # type: ignore[arg-type]
    svc.registry = SessionRegistry()
    svc.registry.replace_all(sessions, NOW)
    return svc


def _session(sid="s1", project="darcy-repo", state=SessionState.WORKING, reason=None, started=180, quiet=2):
    return Session(
        session_id=sid,
        project=project,
        state=state,
        idle_reason=reason,
        started_at=NOW - timedelta(minutes=started),
        last_activity_at=NOW - timedelta(minutes=quiet),
        last_message="Ran the suite.",
    )


def test_detail_reports_elapsed_and_recent_activity() -> None:
    ref = SessionRef(
        session_id="s1",
        project="darcy-repo",
        path=None,
        records=[
            _rec(90, raw_type="user", text="run the tests"),
            _rec(60, text="Starting."),
            _rec(3, stop_reason="end_turn", text="All 41 tests passed."),
        ],
    )
    s = resolve(ref, now=NOW, config=CFG)
    out = _svc([s]).session_status("darcy-repo", now=NOW)
    assert out["found"] is True
    d = out["session"]
    assert d["elapsed_seconds"] == 90 * 60
    assert d["state"] == "idle" and d["idle_reason"] == "completed"
    assert d["recent_events"], "detail must carry ordered recent activity (FR-013)"
    ats = [e["at"] for e in d["recent_events"]]
    assert ats == sorted(ats), "events must be ordered"
    assert all(e["summary_provenance"] in ("mechanical", "model") for e in d["recent_events"])


def test_lookup_by_session_id_and_by_project() -> None:
    svc = _svc([_session(sid="abc123", project="darcy-repo@main")])
    assert svc.session_status("abc123", now=NOW)["found"] is True
    assert svc.session_status("darcy-repo@main", now=NOW)["found"] is True
    assert svc.session_status("darcy-repo", now=NOW)["found"] is True


def test_unknown_project_says_not_found_rather_than_guessing() -> None:
    """FR-012 — never substitute a similar session."""
    svc = _svc([_session(project="darcy-repo@main")])
    out = svc.session_status("darcy-repoo", now=NOW)
    assert out["found"] is False
    assert out["session"] is None
    assert "don't have a session matching that" in compose_status(out)


def test_ambiguous_project_asks_rather_than_picking() -> None:
    """FR-017 — two matches means ask."""
    svc = _svc(
        [
            _session(sid="a", project="Entangle@main"),
            _session(sid="b", project="Entangle@v2"),
        ]
    )
    out = svc.session_status("Entangle", now=NOW)
    assert out["ambiguous"] is True
    assert out["found"] is False
    assert len(out["candidates"]) == 2
    text = compose_status(out)
    assert "which did you mean" in text.lower()
    assert "Entangle@main" in text and "Entangle@v2" in text


def test_ambiguity_disappears_once_the_reference_is_exact() -> None:
    svc = _svc(
        [
            _session(sid="a", project="Entangle@main"),
            _session(sid="b", project="Entangle@v2"),
        ]
    )
    out = svc.session_status("Entangle@v2", now=NOW)
    assert out["found"] is True
    assert out["session"]["session_id"] == "b"


def test_stalled_detail_keeps_the_hedge() -> None:
    svc = _svc([_session(state=SessionState.IDLE, reason=IdleReason.STALLED, quiet=30)])
    text = compose_status(svc.session_status("darcy-repo", now=NOW))
    assert "may have stalled or been killed" in text
    assert "finished" not in text


def test_detail_on_a_stale_registry_leads_with_the_caveat() -> None:
    svc = _svc([_session()])
    later = NOW + timedelta(minutes=20)
    text = compose_status(svc.session_status("darcy-repo", now=later))
    assert text.index("haven't seen") < text.index("darcy-repo")
