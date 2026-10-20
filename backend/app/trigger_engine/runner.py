"""The evaluation loop — where a rule becomes a delivered message (US1).

Deliberately source-agnostic: a rule's type selects a source, and everything
after that is identical. That is what keeps completion and cron from needing
their own pipelines, and it is why FR-007's "a firing is just a turn" holds all
the way down rather than only at the injection call.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .audit import AuditLog
from .compose import compose_proactive, render_prompt, with_late_note
from .config import EngineConfig
from .fingerprint import FingerprintStore, compute
from .injector import TurnInjector
from .models import Destination, Firing, Outcome, ReleaseReason, Rule, TriggerType
from .politeness.coalesce import CoalesceWindow
from .politeness.interrupt import InterruptQueue, is_busy, is_thread_busy_error
from .politeness.quiet_hours import DeferralQueue, QuietHours, should_suppress
from .politeness.release import Releaser
from .presence import PresenceSignal
from .sources.base import SourceUnavailable, TriggerSource
from .threads import RuleThreadMap

logger = logging.getLogger(__name__)

#: Tries an event gets before it is settled as FAILED. See RuleRunner._give_up.
MAX_ATTEMPTS = 3


class EmptyReply(RuntimeError):
    """The run succeeded and said nothing a person could be sent."""


@dataclass
class RuleRunner:
    """Evaluates one rule end to end. Raises nothing the engine cannot contain."""

    sources: dict[TriggerType, TriggerSource]
    fingerprints: FingerprintStore
    threads: RuleThreadMap
    injector: TurnInjector
    releaser: Releaser
    registry: object  # DestinationRegistry
    presence: PresenceSignal
    audit: AuditLog
    config: EngineConfig
    default_tools: tuple[str, ...] = ()
    #: When present, firings accumulate here instead of delivering immediately,
    #: so several rules firing together arrive as one message (FR-015).
    window: CoalesceWindow | None = None
    quiet: QuietHours | None = None
    deferrals: DeferralQueue | None = None
    interrupts: InterruptQueue | None = None
    #: Reads a thread's live status so we do not talk over an exchange (FR-016).
    thread_state: Callable[[str], dict] | None = None
    #: Where a rule's work runs. NOT the event loop (FR-031): that work is
    #: blocking HTTP to the gateway this engine lives in, so running it inline
    #: stalls every request the worker serves for the length of an agent run —
    #: and under one uvicorn worker, stalls the very `runs/wait` it is waiting
    #: on. ONE thread, deliberately: the engine's stores are plain files and
    #: dicts written without locks, and a single thread keeps every write as
    #: sequential as it was when the work (accidentally) ran on the loop.
    #:
    #: The cost, stated: `asyncio.wait_for` in the supervised engine stops
    #: WAITING for a rule that overruns, but cannot stop the thread. A hung rule
    #: delays the rules queued behind it until its HTTP timeout, instead of
    #: hanging the gateway — which is what it did before.
    #: Failed attempts per event fingerprint, for the retry rule in `_give_up`.
    attempts: dict[str, int] = field(default_factory=dict)
    #: Records each run's full content (Feature 006 run history): called once
    #: per injected turn, succeeded or failed, with a plain dict. Optional, and
    #: never allowed to break a firing.
    record_run: Callable[[dict], None] | None = None
    worker: Executor = field(default_factory=lambda: ThreadPoolExecutor(max_workers=1, thread_name_prefix="trigger-engine"))

    async def offload(self, fn: Callable, *args):
        """Run blocking engine work on the engine's worker thread."""
        return await asyncio.get_running_loop().run_in_executor(self.worker, fn, *args)

    async def run(self, rule: Rule, now: datetime) -> list[Firing]:
        return await self.offload(self.run_blocking, rule, now)

    def run_blocking(self, rule: Rule, now: datetime) -> list[Firing]:
        """`run`, on the calling thread. Only the worker thread should call this.

        Returns the firings this call SETTLED: routed toward delivery, or given
        up on after the last retry. The loop marks a cron instant done for each.
        """
        source = self.sources.get(rule.type)
        if source is None:
            logger.debug("rule %s: no source for %s", rule.id, rule.type)
            return []

        try:
            events = source.poll(rule, now)
        except SourceUnavailable as exc:
            # NOT silence, and NOT an empty result treated as "nothing is
            # happening". The rule simply does not fire, and the reason is
            # recorded so the condition is observable (FR-029).
            logger.warning("rule %s: source unavailable: %s", rule.id, exc)
            return []

        fired: list[Firing] = []
        for event in events:
            key = compute(rule.id, event)
            if self.fingerprints.seen(key):
                continue  # FR-017: already fired for this event

            firing = Firing(rule_id=rule.id, event=event, prompt=render_prompt(rule, event))
            started = datetime.now(UTC)
            raw = ""
            try:
                firing.thread_id = self.threads.thread_for(rule.id)
                if self.default_tools:
                    self.injector.configure_tools(firing.thread_id, list(self.default_tools))
                raw = self.injector.inject(firing.thread_id, rule.id, firing.prompt)
                if not raw.strip() and rule.type is not TriggerType.WATCHER:
                    # A watcher alert still says something without a reply (its
                    # header names the session); anything else would arrive as
                    # "(the assistant returned nothing)", which is not a message.
                    raise EmptyReply("the run completed with no reply")
                firing.body = compose_proactive(rule, event, raw, late=False)
                firing.reply = with_late_note(event, firing.body)
            except Exception as exc:  # noqa: BLE001 — one firing, not the rule
                self._record(rule, firing, started, raw, error=f"{type(exc).__name__}: {exc}")
                if self._give_up(rule, firing, key, exc, now):
                    fired.append(firing)
                continue
            self._record(rule, firing, started, raw, error=None)

            # Recorded BEFORE delivery: a crash between injection and delivery
            # must not cause the same event to fire again on the next cycle.
            # A missed message is recoverable; a repeat is what gets the feature
            # muted (FR-017).
            self.fingerprints.record(key, now)

            self._route(rule, firing, now)
            fired.append(firing)
        return fired

    def _record(self, rule: Rule, firing: Firing, started: datetime, reply: str, *, error: str | None) -> None:
        if self.record_run is None:
            return
        try:
            self.record_run(
                {
                    "rule_id": rule.id,
                    "event_type": str(firing.event.type),
                    "event_id": firing.event.event_id,
                    "thread_id": firing.thread_id,
                    "started_at": started,
                    "finished_at": datetime.now(UTC),
                    "status": "failed" if error else "completed",
                    "error": error,
                    "body": {
                        "rule_id": rule.id,
                        "event": {"type": str(firing.event.type), "id": firing.event.event_id, "fields": dict(firing.event.fields)},
                        "prompt": firing.prompt,
                        "messages": list(getattr(self.injector, "last_turn", []) or []),
                        "reply": reply,
                    },
                }
            )
        except Exception:  # noqa: BLE001 — history must never break a firing
            logger.exception("rule %s: recording the run failed", rule.id)

    def _give_up(self, rule: Rule, firing: Firing, key: str, exc: Exception, now: datetime) -> bool:
        """Resolve a failed firing. Returns True when the event is settled.

        THE RETRY RULE, stated because a failed run used to be delivered as an
        empty message and then never retried: an event gets MAX_ATTEMPTS tries,
        one per cycle. Each failure is recorded FAILED with the run's own
        reason, and nothing is delivered. The event is retried only if its
        source still produces it on the next cycle — a watcher session that
        stopped waiting is not retried. After the last attempt the event is
        fingerprinted, so it never fires again, and returned as settled, so a
        cron instant is marked done rather than retried forever.

        Attempt counts are held in memory: a restart grants an event up to
        MAX_ATTEMPTS more tries. Bounded, and cheaper than another store.
        """
        n = self.attempts.get(key, 0) + 1
        reason = f"{type(exc).__name__}: {exc}"
        if n >= MAX_ATTEMPTS:
            self.attempts.pop(key, None)
            self.fingerprints.record(key, now)
            firing.resolve(Outcome.FAILED, f"gave up after {n} attempts: {reason}")
            logger.error("rule %s: gave up on %s after %d attempts: %s", rule.id, firing.event.event_id, n, reason)
        else:
            self.attempts[key] = n
            firing.resolve(Outcome.FAILED, f"attempt {n} of {MAX_ATTEMPTS}: {reason}; retrying on the next cycle")
            logger.warning("rule %s: attempt %d of %d failed: %s", rule.id, n, MAX_ATTEMPTS, reason)
        self.audit.record(firing, now)
        return n >= MAX_ATTEMPTS

    # -- politeness (Article VII) ------------------------------------------

    def _route(self, rule: Rule, firing: Firing, now: datetime) -> None:
        """Decide what happens to a composed firing.

        Order matters and is not arbitrary: quiet hours first, because a 3am
        message is the worst outcome and nothing downstream should be able to
        undo that decision; then mid-exchange, because talking over someone is
        the second worst; then coalescing; then delivery.
        """
        if self.quiet is not None and self.deferrals is not None:
            suppress, reason = should_suppress(rule.urgent, self.quiet, now)
            if suppress:
                self.deferrals.defer(firing, now, reason)
                self.audit.record(firing, now)
                return

        if self.interrupts is not None and self._is_mid_exchange(firing.thread_id):
            self.interrupts.hold(firing, now, self._hold_reason)
            self.audit.record(firing, now)
            return

        if self.window is not None:
            self.window.add(firing, now)
            firing.resolve(Outcome.QUEUED, "awaiting the coalescing window")
            self.audit.record(firing, now)
            return

        self.releaser.release([firing], ReleaseReason.IMMEDIATE, self._destination_for(rule, now), now)

    #: Why the last check said "hold" — an observed exchange, or one we could
    #: not rule out. The audit says which (Article X): live, a store error was
    #: recorded as "user is mid-exchange" when nothing had been observed.
    _hold_reason: str = "user is mid-exchange on the target thread"

    def _is_mid_exchange(self, thread_id: str | None) -> bool:
        if not thread_id or self.thread_state is None:
            return False
        self._hold_reason = "user is mid-exchange on the target thread"
        try:
            return is_busy(self.thread_state(thread_id))
        except Exception as exc:  # noqa: BLE001
            # Unknown busyness is not "free". Erring toward holding costs a
            # short delay; erring toward sending talks over the user.
            # Returning False here used to contradict the comment above: every
            # lookup failure read as "free" and the firing went straight out.
            # Held, it is released by the interrupt queue's bound (FR-016a).
            if not is_thread_busy_error(exc):
                logger.warning("thread state unavailable for %s, holding: %s", thread_id, exc)
                self._hold_reason = f"could not tell whether an exchange is in progress ({type(exc).__name__}); holding until it can, or for the queue's bound"
            return True

    def release_deferred(self, rule: Rule, now: datetime) -> str | None:
        """Quiet hours ended — one of the three entry conditions (FR-013d)."""
        if self.deferrals is None or not len(self.deferrals):
            return None
        if self.quiet is not None and self.quiet.contains(now):
            return None
        return self.releaser.release(
            self.deferrals.drain(),
            ReleaseReason.QUIET_HOURS_ENDED,
            self._destination_for(rule, now),
            now,
        )

    def release_queued(self, rule: Rule, now: datetime) -> str | None:
        """A held exchange ended or the bound expired (FR-016c)."""
        if self.interrupts is None:
            return None
        ready = self.interrupts.due(now, still_busy=lambda t: self._is_mid_exchange(t), on_expire=lambda f: self.audit.record(f, now))
        if not ready:
            return None
        for f in ready:
            if f.body is not None and f.event.type is not TriggerType.WATCHER:
                # The note is rewritten for NOW: the firing may have been on
                # time when composed and late by the time the exchange ended.
                f.reply = with_late_note(f.event, f.body, now=now, held=True)
        delivered = None
        for reason in (ReleaseReason.EXCHANGE_ENDED, ReleaseReason.QUEUE_EXPIRED):
            group = [f for f in ready if f.release_reason is reason]
            if group:
                delivered = self.releaser.release(group, reason, self._destination_for(rule, now), now) or delivered
        return delivered

    def _destination_for(self, rule: Rule, now: datetime):
        return self.registry.resolve(
            rule.destination if isinstance(rule.destination, Destination) else Destination.AUTO,
            present=self.presence.is_present(now),
        )

    def flush_window(self, now: datetime, rule: Rule) -> str | None:
        """Deliver an accumulated window as ONE message (FR-015).

        Routed through release() like everything else — this is a third entry
        condition, not a third implementation (Gate 3).
        """
        if self.window is None or not self.window.is_due(now):
            return None
        batch = self.window.drain()
        if not batch:
            return None
        return self.releaser.release(batch, ReleaseReason.IMMEDIATE, self._destination_for(rule, now), now)
