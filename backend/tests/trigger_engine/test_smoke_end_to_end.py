"""T084 — the service-level smoke test.

Gate 4 catches code nothing calls. It explicitly does NOT catch a function
called with wrong arguments, or called from a branch that never executes —
both are "wired to the wrong place" rather than "not wired", and no static
check sees them. This is the only thing that does.

It assembles the REAL objects and drives one rule the whole way, rather than
asserting on doubles. Every wiring defect in this project was found by doing
exactly this.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.trigger_engine.audit import AuditLog
from app.trigger_engine.config import ConfigLoader
from app.trigger_engine.destinations.base import DestinationRegistry, QuietDestination
from app.trigger_engine.engine import SupervisedEngine
from app.trigger_engine.fingerprint import FingerprintStore
from app.trigger_engine.injector import TurnInjector
from app.trigger_engine.loop import TriggerLoop
from app.trigger_engine.models import TriggerType
from app.trigger_engine.politeness.interrupt import InterruptQueue
from app.trigger_engine.politeness.quiet_hours import DeferralQueue, QuietHours
from app.trigger_engine.politeness.release import Releaser
from app.trigger_engine.presence import PresenceSignal
from app.trigger_engine.runner import RuleRunner
from app.trigger_engine.scheduler import Scheduler
from app.trigger_engine.sources.cron import CronSource
from app.trigger_engine.sources.watcher import WatcherSource
from app.trigger_engine.threads import RuleThreadMap

pytestmark = pytest.mark.asyncio
DAY = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


class _Gateway:
    """Records everything, so the test can assert on the CALLS, not just results."""

    def __init__(self):
        self.threads, self.tool_sets, self.runs = [], [], []

    def post(self, path, body):
        if path == "/api/threads":
            self.threads.append(body)
            return {"thread_id": f"t-{len(self.threads)}"}
        self.runs.append((path, body))
        return {"messages": [{"type": "ai", "content": "darcy-repo needs a decision on the fixture."}]}

    def put(self, path, body):
        self.tool_sets.append((path, body))
        return {"sources": body["sources"]}

    def get(self, path):
        return {"status": "idle"}


def _build(tmp_path, rules: list[dict]):
    import json

    f = tmp_path / "rules.json"
    f.write_text(json.dumps({"rules": rules}))
    gw, dest = _Gateway(), QuietDestination()
    audit = AuditLog(path=tmp_path / "audit.jsonl")
    sched = Scheduler(path=tmp_path / "sched.json")
    fps = FingerprintStore(path=tmp_path / "fp.json")
    threads = RuleThreadMap(path=tmp_path / "th.json", create_thread=lambda rid: gw.post("/api/threads", {"metadata": {"trigger_rule_id": rid}})["thread_id"])
    runner = RuleRunner(
        sources={
            TriggerType.WATCHER: WatcherSource(
                fetch_sessions=lambda: {"observable": True, "sessions": [{"session_id": "s1", "project": "darcy-repo", "state": "waiting-on-user", "idle_reason": None, "summary": "Pin the version or rewrite the fixture?"}]}
            ),
            TriggerType.CRON: CronSource(scheduler=sched),
        },
        fingerprints=fps,
        threads=threads,
        injector=TurnInjector(post=gw.post, put=gw.put, get=gw.get),
        releaser=Releaser(redact=lambda t: (t, True), still_true=lambda f: True, audit=lambda fr, n: audit.record(fr, n)),
        registry=DestinationRegistry(remote=dest, quiet=dest),
        presence=PresenceSignal(),
        audit=audit,
        config=ConfigLoader(path=f).load(),
        quiet=QuietHours(enabled=False),
        deferrals=DeferralQueue(),
        interrupts=InterruptQueue(),
        thread_state=gw.get,
        default_tools=("local:session-watcher",),
    )
    loop = TriggerLoop(
        loader=ConfigLoader(path=f),
        runner=runner,
        engine=SupervisedEngine(evaluate=lambda r, n: None),
        scheduler=sched,
        fingerprints=fps,
        threads=threads,
        presence=PresenceSignal(),
        now=lambda: DAY,
    )
    return loop, gw, dest, audit


async def test_one_full_cycle_drives_a_rule_end_to_end(tmp_path) -> None:
    """The whole chain through TriggerLoop.cycle(), not through RuleRunner."""
    loop, gw, dest, audit = _build(tmp_path, [{"id": "blocked", "type": "watcher", "match": {"event": "waiting-on-user"}, "prompt": "{project} is waiting: {last_message}", "destination": "quiet"}])

    results = await loop.cycle()
    assert results == {"blocked": True}

    # The calls, not just the outcome — this is what catches "called with the
    # wrong arguments", which Gate 4 cannot see.
    assert gw.threads, "no thread was created"
    assert gw.tool_sets and gw.tool_sets[0][1] == {"sources": ["local:session-watcher"]}
    path, body = gw.runs[0]
    assert path.endswith("/runs/wait")
    assert body["assistant_id"] == "lead_agent"
    assert body["input"]["messages"][0]["role"] == "human"
    assert body["metadata"]["turn_provenance"] == "synthetic-trigger"
    assert "darcy-repo is waiting: Pin the version" in body["input"]["messages"][0]["content"]

    assert len(dest.delivered) == 1
    assert audit.entries()[0]["outcome"] == "delivered"


async def test_a_second_cycle_delivers_nothing_new(tmp_path) -> None:
    loop, _, dest, _ = _build(tmp_path, [{"id": "blocked", "type": "watcher", "match": {"event": "waiting-on-user"}, "prompt": "{project}: {last_message}", "destination": "quiet"}])
    for _ in range(5):
        await loop.cycle()
    assert len(dest.delivered) == 1


async def test_a_cron_rule_runs_through_the_same_loop(tmp_path) -> None:
    """Source-agnostic: cron needs no pipeline of its own."""
    loop, _, dest, _ = _build(tmp_path, [{"id": "briefing", "type": "cron", "match": {"schedule": "0 7 * * *"}, "prompt": "Summarise overnight.", "destination": "quiet"}])
    await loop.cycle()
    assert len(dest.delivered) == 1
    await loop.cycle()
    assert len(dest.delivered) == 1, "the same scheduled instant fired twice"


async def test_the_loop_sleeps_rather_than_ticking(tmp_path) -> None:
    """FR-027 — the next wake-up is a computed moment, not a fixed tick."""
    loop, _, _, _ = _build(tmp_path, [{"id": "briefing", "type": "cron", "match": {"schedule": "0 7 * * *"}, "prompt": "x", "destination": "quiet"}])
    nxt = loop.next_wakeup(DAY)
    assert nxt > DAY
    assert nxt - DAY <= timedelta(minutes=1) + timedelta(seconds=1)


async def test_a_broken_rule_does_not_stop_the_cycle(tmp_path) -> None:
    loop, _, dest, _ = _build(
        tmp_path,
        [
            {"id": "good", "type": "watcher", "match": {"event": "waiting-on-user"}, "prompt": "{project}", "destination": "quiet"},
            {"id": "broken", "type": "watcher", "match": {"event": "waiting-on-user"}, "prompt": "{project}", "destination": "quiet"},
        ],
    )
    original = loop.runner.run

    async def selective(rule, now):
        if rule.id == "broken":
            raise RuntimeError("boom")
        return await original(rule, now)

    loop.runner.run = selective
    results = await loop.cycle()
    assert results["good"] is True and results["broken"] is False
    assert len(dest.delivered) == 1
