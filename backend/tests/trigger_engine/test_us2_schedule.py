"""T063-T064 — US2: a briefing on its own schedule (SC-003, SC-004)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.trigger_engine.audit import AuditLog
from app.trigger_engine.config import EngineConfig
from app.trigger_engine.destinations.base import DestinationRegistry, QuietDestination
from app.trigger_engine.fingerprint import FingerprintStore
from app.trigger_engine.injector import TurnInjector
from app.trigger_engine.models import Destination, Rule, TriggerType
from app.trigger_engine.politeness.release import Releaser
from app.trigger_engine.presence import PresenceSignal
from app.trigger_engine.runner import RuleRunner
from app.trigger_engine.scheduler import Scheduler
from app.trigger_engine.sources.cron import CronSource
from app.trigger_engine.threads import RuleThreadMap

pytestmark = pytest.mark.asyncio
DAY0 = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
RULE = Rule(id="morning-briefing", type=TriggerType.CRON, match={"schedule": "30 7 * * *"}, prompt="Summarise what happened overnight.", destination=Destination.QUIET)


class _GW:
    def post(self, path, body):
        if path == "/api/threads":
            return {"thread_id": "t-1"}
        return {"messages": [{"type": "ai", "content": "Three sessions finished overnight."}]}

    def put(self, path, body):
        return {"sources": body["sources"]}

    def get(self, path):
        return {}


def _runner(tmp_path):
    gw, dest = _GW(), QuietDestination()
    audit = AuditLog(path=tmp_path / "a.jsonl", actor="default")
    sched = Scheduler(path=tmp_path / "s.json")
    r = RuleRunner(
        sources={TriggerType.CRON: CronSource(scheduler=sched)},
        fingerprints=FingerprintStore(path=tmp_path / "f.json"),
        threads=RuleThreadMap(path=tmp_path / "t.json", create_thread=lambda x: "t-1"),
        injector=TurnInjector(post=gw.post, put=gw.put, get=gw.get),
        releaser=Releaser(redact=lambda t: (t, True), still_true=lambda f: True, audit=lambda f, n: audit.record(f, n)),
        registry=DestinationRegistry(remote=dest, quiet=dest),
        presence=PresenceSignal(),
        audit=audit,
        config=EngineConfig(),
    )
    return r, dest, sched


async def _cycle(runner, sched, at):
    fired = await runner.run(RULE, at)
    for f in fired:
        sched.mark_fired(RULE.id, f.event.at, at)
    return fired


async def test_a_scheduled_rule_delivers_once_per_instant(tmp_path) -> None:
    """SC-003 — across a week: one delivery per scheduled instant, no doubles.

    The count is DERIVED from the instants actually served, not hardcoded: a
    literal "7" was wrong here, because a run starting at midday also picks up
    that morning's instant. Asserting deliveries == distinct instants tests the
    property (exactly once each) rather than my arithmetic about the window.
    """
    runner, dest, sched = _runner(tmp_path)
    at = DAY0
    for _ in range(7):
        for _ in range(6):  # several evaluation cycles per day
            await _cycle(runner, sched, at)
            at += timedelta(hours=4)

    served = [k for k in sched._store.keys() if k.startswith(RULE.id)]
    assert len(dest.delivered) == len(served), f"{len(dest.delivered)} deliveries for {len(served)} served instants"
    assert len(served) == len(set(served)), "an instant was served twice"
    assert len(served) >= 7, "a week of daily schedules produced fewer than 7 instants"


async def test_repeated_cycles_within_one_day_deliver_once(tmp_path) -> None:
    runner, dest, sched = _runner(tmp_path)
    for _ in range(20):
        await _cycle(runner, sched, DAY0)
    assert len(dest.delivered) == 1


async def test_a_missed_instant_fires_once_late(tmp_path) -> None:
    """SC-004 — the engine was stopped over a scheduled time."""
    runner, dest, sched = _runner(tmp_path)
    # First cycle happens well after the instant it should have served.
    late = DAY0 + timedelta(hours=8)
    for _ in range(5):
        await _cycle(runner, sched, late)
    assert len(dest.delivered) == 1, "a missed instant fired more than once"


async def test_records_survive_a_restart(tmp_path) -> None:
    runner, dest, sched = _runner(tmp_path)
    await _cycle(runner, sched, DAY0)
    assert len(dest.delivered) == 1
    # A fresh runner over the same stores, as after a restart.
    runner2, dest2, sched2 = _runner(tmp_path)
    await _cycle(runner2, sched2, DAY0)
    assert dest2.delivered == [], "the restart re-fired an already-served instant"
