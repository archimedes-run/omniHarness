"""T045-T048 — trigger sources, and the unobservable/absent distinction."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.trigger_engine.fingerprint import FORBIDDEN_INPUTS, compute
from app.trigger_engine.models import Rule, TriggerType
from app.trigger_engine.scheduler import Scheduler
from app.trigger_engine.sources.base import SourceUnavailable
from app.trigger_engine.sources.completion import CompletionSource
from app.trigger_engine.sources.cron import CronSource
from app.trigger_engine.sources.watcher import WatcherSource

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def _rule(rtype=TriggerType.WATCHER, **match) -> Rule:
    return Rule(id="r1", type=rtype, match=match or {"event": "waiting-on-user"}, prompt="p")


def _payload(state="waiting-on-user", summary="Should I roll it back?", observable=True):
    return {
        "observable": observable,
        "observability": "live" if observable else "stale",
        "sessions": [
            {
                "session_id": "sess-1",
                "project": "darcy-repo@main",
                "state": state,
                "idle_reason": None,
                "summary": summary,
                # Present in the payload and deliberately NOT used as fingerprint
                # input — this is the drift trap.
                "quiet_seconds": 137,
                "elapsed_seconds": 4020,
            }
        ],
    }


def test_watcher_source_emits_matching_events() -> None:
    src = WatcherSource(fetch_sessions=lambda: _payload())
    events = src.poll(_rule(), NOW)
    assert len(events) == 1
    assert events[0].event_id == "sess-1"
    assert events[0].fields["project"] == "darcy-repo@main"


def test_watcher_source_ignores_non_matching_states() -> None:
    src = WatcherSource(fetch_sessions=lambda: _payload(state="working"))
    assert src.poll(_rule(), NOW) == []


def test_watcher_fingerprint_inputs_exclude_drifting_values() -> None:
    """FR-017b — the payload HAS quiet_seconds and elapsed_seconds; the
    fingerprint must not. Including either produces an alert per cycle."""
    src = WatcherSource(fetch_sessions=lambda: _payload())
    ev = src.poll(_rule(), NOW)[0]
    assert set(ev.fingerprint_inputs) & FORBIDDEN_INPUTS == set()
    assert "quiet_seconds" not in ev.fingerprint_inputs
    assert "elapsed_seconds" not in ev.fingerprint_inputs
    compute("r1", ev)  # would raise if a forbidden input crept in


def test_repeated_polls_of_an_unchanged_session_share_one_fingerprint() -> None:
    src = WatcherSource(fetch_sessions=lambda: _payload())
    keys = {compute("r1", src.poll(_rule(), NOW)[0]) for _ in range(20)}
    assert len(keys) == 1, "an unchanged session produced multiple identities"


def test_changed_question_changes_the_fingerprint() -> None:
    a = WatcherSource(fetch_sessions=lambda: _payload(summary="Roll back?")).poll(_rule(), NOW)[0]
    b = WatcherSource(fetch_sessions=lambda: _payload(summary="Pin it?")).poll(_rule(), NOW)[0]
    assert compute("r1", a) != compute("r1", b)


def test_unreachable_source_raises_rather_than_returning_empty() -> None:
    """FR-029, SC-013 — THE distinction.

    Returning [] would be indistinguishable from "we looked and nothing is
    happening", which is the claim Article X forbids when we could not look.
    """

    def boom():
        raise ConnectionError("watcher unreachable")

    src = WatcherSource(fetch_sessions=boom)
    with pytest.raises(SourceUnavailable):
        src.poll(_rule(), NOW)
    assert src.reachable is False
    assert "unreachable" in src.describe()["last_error"]


def test_a_stale_watcher_is_also_unobservable() -> None:
    """The watcher answering with observable=false is not 'no events'."""
    src = WatcherSource(fetch_sessions=lambda: _payload(observable=False))
    with pytest.raises(SourceUnavailable, match="observability"):
        src.poll(_rule(), NOW)


def test_reachability_is_inspectable() -> None:
    src = WatcherSource(fetch_sessions=lambda: _payload())
    src.poll(_rule(), NOW)
    assert src.describe()["reachable"] is True


def test_cron_source_emits_due_instants(tmp_path) -> None:
    s = Scheduler(path=tmp_path / "s.json")
    src = CronSource(scheduler=s)
    events = src.poll(_rule(TriggerType.CRON, schedule="0 7 * * *"), NOW)
    assert len(events) == 1
    assert events[0].fingerprint_inputs == {"scheduled_at": events[0].at.isoformat()}


def test_cron_fingerprint_is_the_instant(tmp_path) -> None:
    """Two firings of the same instant are the same event — nothing else about
    a schedule can change."""
    s = Scheduler(path=tmp_path / "s.json")
    r = _rule(TriggerType.CRON, schedule="0 7 * * *")
    a = CronSource(scheduler=s).poll(r, NOW)[0]
    b = CronSource(scheduler=s).poll(r, NOW)[0]
    assert compute("r1", a) == compute("r1", b)


def test_completion_source_filters_by_status() -> None:
    tasks = [{"task_id": "t1", "status": "succeeded", "summary": "done"}, {"task_id": "t2", "status": "failed", "summary": "boom"}]
    src = CompletionSource(fetch_completions=lambda: tasks)
    events = src.poll(_rule(TriggerType.COMPLETION, status="succeeded"), NOW)
    assert [e.event_id for e in events] == ["t1"]


def test_completion_fingerprint_excludes_duration() -> None:
    src = CompletionSource(fetch_completions=lambda: [{"task_id": "t1", "status": "succeeded", "duration": 900, "finished_at": "x"}])
    ev = src.poll(_rule(TriggerType.COMPLETION), NOW)[0]
    assert set(ev.fingerprint_inputs) == {"task_id", "status"}


def test_completion_source_unreachable_raises() -> None:
    def boom():
        raise TimeoutError("task service down")

    with pytest.raises(SourceUnavailable):
        CompletionSource(fetch_completions=boom).poll(_rule(TriggerType.COMPLETION), NOW)
