"""The evaluation loop — where a rule becomes a delivered message (US1).

Deliberately source-agnostic: a rule's type selects a source, and everything
after that is identical. That is what keeps completion and cron from needing
their own pipelines, and it is why FR-007's "a firing is just a turn" holds all
the way down rather than only at the injection call.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from .audit import AuditLog
from .compose import compose_proactive, render_prompt
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

    async def run(self, rule: Rule, now: datetime) -> list[Firing]:
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
            try:
                firing.thread_id = self.threads.thread_for(rule.id)
                if self.default_tools:
                    self.injector.configure_tools(firing.thread_id, list(self.default_tools))
                raw = self.injector.inject(firing.thread_id, rule.id, firing.prompt)
                firing.reply = compose_proactive(rule, event, raw)
            except Exception as exc:  # noqa: BLE001 — one firing, not the rule
                firing.resolve(Outcome.FAILED, f"{type(exc).__name__}: {exc}")
                self.audit.record(firing, now)
                logger.exception("rule %s: firing failed", rule.id)
                continue

            # Recorded BEFORE delivery: a crash between injection and delivery
            # must not cause the same event to fire again on the next cycle.
            # A missed message is recoverable; a repeat is what gets the feature
            # muted (FR-017).
            self.fingerprints.record(key, now)

            self._route(rule, firing, now)
            fired.append(firing)
        return fired

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
            self.interrupts.hold(firing, now)
            self.audit.record(firing, now)
            return

        if self.window is not None:
            self.window.add(firing, now)
            firing.resolve(Outcome.QUEUED, "awaiting the coalescing window")
            self.audit.record(firing, now)
            return

        self.releaser.release([firing], ReleaseReason.IMMEDIATE, self._destination_for(rule, now), now)

    def _is_mid_exchange(self, thread_id: str | None) -> bool:
        if not thread_id or self.thread_state is None:
            return False
        try:
            return is_busy(self.thread_state(thread_id))
        except Exception as exc:  # noqa: BLE001
            # Unknown busyness is not "free". Erring toward holding costs a
            # short delay; erring toward sending talks over the user.
            if is_thread_busy_error(exc):
                return True
            logger.debug("thread state unavailable for %s: %s", thread_id, exc)
            return False

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
        ready = self.interrupts.due(now, still_busy=lambda t: self._is_mid_exchange(t))
        if not ready:
            return None
        return self.releaser.release(ready, ReleaseReason.QUEUE_EXPIRED, self._destination_for(rule, now), now)

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
