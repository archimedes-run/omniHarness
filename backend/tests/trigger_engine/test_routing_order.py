"""US4 through the runner: the order politeness decisions are made in.

Order is not arbitrary and is asserted, because getting it wrong is silent:
quiet hours first (a 3am message is the worst outcome, and nothing downstream
may undo that), then mid-exchange (talking over someone is the second worst),
then coalescing, then delivery.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.trigger_engine.audit import AuditLog
from app.trigger_engine.config import EngineConfig
from app.trigger_engine.destinations.base import DestinationRegistry, QuietDestination
from app.trigger_engine.fingerprint import FingerprintStore
from app.trigger_engine.injector import TurnInjector
from app.trigger_engine.models import Destination, Rule, TriggerType
from app.trigger_engine.politeness.coalesce import CoalesceWindow
from app.trigger_engine.politeness.interrupt import InterruptQueue
from app.trigger_engine.politeness.quiet_hours import DeferralQueue, QuietHours
from app.trigger_engine.politeness.release import Releaser
from app.trigger_engine.presence import PresenceSignal
from app.trigger_engine.runner import RuleRunner
from app.trigger_engine.sources.watcher import WatcherSource
from app.trigger_engine.threads import RuleThreadMap

pytestmark = pytest.mark.asyncio
NIGHT = datetime(2026, 8, 21, 2, 0, tzinfo=UTC)
DAY = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def _payload(summary="Roll it back?"):
    return {"observable": True, "sessions": [{"session_id": "s1", "project": "darcy-repo", "state": "waiting-on-user", "idle_reason": None, "summary": summary}]}


class _GW:
    def post(self, p, b):
        return {"thread_id": "t-1"} if p == "/api/threads" else {"messages": [{"type": "ai", "content": "It needs a decision."}]}

    def put(self, p, b):
        return {"sources": b["sources"]}

    def get(self, p):
        return {}


def _runner(tmp_path, *, quiet=None, busy=False, window=None, urgent=False):
    gw, dest = _GW(), QuietDestination()
    audit = AuditLog(path=tmp_path / "a.jsonl", actor="default")
    r = RuleRunner(
        sources={TriggerType.WATCHER: WatcherSource(fetch_sessions=_payload)},
        fingerprints=FingerprintStore(path=tmp_path / "f.json"),
        threads=RuleThreadMap(path=tmp_path / "t.json", create_thread=lambda x: "t-1"),
        injector=TurnInjector(post=gw.post, put=gw.put, get=gw.get),
        releaser=Releaser(redact=lambda t: (t, True), still_true=lambda f: True, audit=lambda f, n: audit.record(f, n)),
        registry=DestinationRegistry(remote=dest, quiet=dest),
        presence=PresenceSignal(),
        audit=audit,
        config=EngineConfig(),
        quiet=quiet,
        deferrals=DeferralQueue() if quiet else None,
        interrupts=InterruptQueue(max_wait=timedelta(minutes=5)),
        thread_state=(lambda t: {"status": "busy" if busy else "idle"}),
        window=window,
    )
    rule = Rule(id="blocked", type=TriggerType.WATCHER, match={"event": "waiting-on-user"}, prompt="{project}: {last_message}", destination=Destination.QUIET, urgent=urgent)
    return r, dest, audit, rule


async def test_quiet_hours_wins_over_everything_downstream(tmp_path) -> None:
    r, dest, audit, rule = _runner(tmp_path, quiet=QuietHours(), busy=False, window=CoalesceWindow())
    await r.run(rule, NIGHT)
    assert dest.delivered == []
    assert len(r.deferrals) == 1
    assert audit.entries()[0]["outcome"] == "suppressed", "quiet hours and mid-exchange must be distinguishable in the audit log"
    assert "quiet hours" in audit.entries()[0]["reason"]


async def test_an_urgent_rule_passes_quiet_hours(tmp_path) -> None:
    r, dest, _, rule = _runner(tmp_path, quiet=QuietHours(), urgent=True)
    await r.run(rule, NIGHT)
    assert len(dest.delivered) == 1


async def test_a_busy_thread_holds_the_firing(tmp_path) -> None:
    r, dest, audit, rule = _runner(tmp_path, busy=True)
    await r.run(rule, DAY)
    assert dest.delivered == []
    assert len(r.interrupts) == 1
    assert "mid-exchange" in audit.entries()[0]["reason"]


async def test_an_idle_thread_delivers(tmp_path) -> None:
    r, dest, _, rule = _runner(tmp_path, busy=False)
    await r.run(rule, DAY)
    assert len(dest.delivered) == 1


async def test_unknown_busyness_holds_rather_than_sends(tmp_path) -> None:
    """Erring toward holding costs a short delay; erring toward sending talks
    over the user. The asymmetry decides the default."""
    r, dest, _, rule = _runner(tmp_path)
    r.thread_state = lambda t: (_ for _ in ()).throw(RuntimeError("thread is already running a task"))
    await r.run(rule, DAY)
    assert dest.delivered == []
    assert len(r.interrupts) == 1


async def test_quiet_hours_release_delivers_the_backlog_as_one(tmp_path) -> None:
    r, dest, _, rule = _runner(tmp_path, quiet=QuietHours())
    await r.run(rule, NIGHT)
    assert dest.delivered == []
    out = r.release_deferred(rule, DAY)  # window has ended
    assert out and len(dest.delivered) == 1


async def test_release_does_nothing_while_still_inside_quiet_hours(tmp_path) -> None:
    r, dest, _, rule = _runner(tmp_path, quiet=QuietHours())
    await r.run(rule, NIGHT)
    assert r.release_deferred(rule, NIGHT + timedelta(minutes=30)) is None
    assert dest.delivered == []


async def test_queued_firing_releases_when_the_thread_frees(tmp_path) -> None:
    r, dest, _, rule = _runner(tmp_path, busy=True)
    await r.run(rule, DAY)
    r.thread_state = lambda t: {"status": "idle"}
    out = r.release_queued(rule, DAY + timedelta(seconds=30))
    assert out and len(dest.delivered) == 1
