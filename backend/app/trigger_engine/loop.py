"""The driving loop (FR-018, FR-027, T061).

Sleeps until the next due moment rather than ticking. One timer, O(1) work while
idle — a tick loop burns CPU to learn nothing, which Article VI forbids.

Owns the periodic sweeps too (fingerprint reset, scheduler pruning, stale thread
mappings), because they share the same wake-up and there is no reason to have a
second timer for them.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .config import ConfigLoader
from .engine import SupervisedEngine
from .fingerprint import FingerprintStore
from .models import Rule, TriggerType
from .presence import PresenceSignal
from .runner import RuleRunner
from .scheduler import Scheduler
from .threads import RuleThreadMap

logger = logging.getLogger(__name__)

#: How often the loop wakes when no rule is scheduled. Event-driven rules still
#: need a pulse; this is it. A stated default.
IDLE_PULSE = timedelta(seconds=60)
SWEEP_INTERVAL = timedelta(hours=1)


@dataclass
class TriggerLoop:
    loader: ConfigLoader
    runner: RuleRunner
    engine: SupervisedEngine
    scheduler: Scheduler
    fingerprints: FingerprintStore
    threads: RuleThreadMap
    presence: PresenceSignal
    now: Callable[[], datetime]
    recent_runs: Callable[[], list[dict]] | None = None
    last_sweep_at: datetime | None = None
    _stop: asyncio.Event = field(default_factory=asyncio.Event)

    def next_wakeup(self, now: datetime) -> datetime:
        """Earliest of: the next scheduled instant, or the idle pulse."""
        cfg = self.loader.config
        schedules = [(r.id, r.match.get("schedule", "")) for r in cfg.rules if r.enabled and r.type is TriggerType.CRON]
        due = self.scheduler.next_wakeup(schedules, now) if schedules else None
        pulse = now + IDLE_PULSE
        candidates = [pulse] + ([due] if due else [])
        # Wake when quiet hours end, so a deferred backlog is released promptly
        # rather than waiting for whatever happens to be scheduled next.
        if self.runner.quiet is not None and self.runner.quiet.contains(now):
            candidates.append(self.runner.quiet.next_end(now))
        return min(candidates)

    async def cycle(self) -> dict[str, bool]:
        """One pass: reload config, refresh presence, evaluate, sweep."""
        now = self.now()
        cfg = self.loader.load()  # hot reload; invalid keeps the previous
        if self.recent_runs is not None:
            self.presence.observe_runs(self.recent_runs())

        async def _run(rule: Rule, at: datetime) -> None:
            fired = await self.runner.run(rule, at)
            if rule.type is TriggerType.CRON:
                for f in fired:
                    self.scheduler.mark_fired(rule.id, f.event.at, at)

        self.engine.evaluate = _run
        results = await self.engine.evaluate_all(list(cfg.rules), now)

        # The three release entry conditions, all reaching the one release()
        # path. Gate 4 caught these being implemented and never called — quiet
        # hours would have deferred firings that nothing ever released.
        for rule in cfg.rules:
            if not rule.enabled:
                continue
            self.runner.release_deferred(rule, now)
            self.runner.release_queued(rule, now)
            self.runner.flush_window(now, rule)

        self._maybe_sweep(now)
        return results

    def _maybe_sweep(self, now: datetime) -> None:
        """Retention, on the same wake-up rather than a second timer."""
        if self.last_sweep_at is not None and now - self.last_sweep_at < SWEEP_INTERVAL:
            return
        self.last_sweep_at = now
        self.fingerprints.maybe_reset(now)
        self.scheduler.prune(now - timedelta(days=7))
        live = {r.id for r in self.loader.config.rules}
        for rule_id in self.threads.known_rules():
            if rule_id not in live:
                # The rule is gone; its thread mapping is dead weight.
                self.threads.forget(rule_id)

    async def run_forever(self) -> None:
        while not self._stop.is_set():
            try:
                await self.cycle()
            except Exception:  # noqa: BLE001 — the loop outlives any one cycle
                logger.exception("trigger cycle failed; continuing")
            delay = max(0.0, (self.next_wakeup(self.now()) - self.now()).total_seconds())
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except TimeoutError:
                pass

    def stop(self) -> None:
        self._stop.set()
