"""The evaluation loop — where a rule becomes a delivered message (US1).

Deliberately source-agnostic: a rule's type selects a source, and everything
after that is identical. That is what keeps completion and cron from needing
their own pipelines, and it is why FR-007's "a firing is just a turn" holds all
the way down rather than only at the injection call.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from .audit import AuditLog
from .compose import compose_proactive, render_prompt
from .config import EngineConfig
from .fingerprint import FingerprintStore, compute
from .injector import TurnInjector
from .models import Destination, Firing, Outcome, ReleaseReason, Rule, TriggerType
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

            destination = self.registry.resolve(
                rule.destination if isinstance(rule.destination, Destination) else Destination.AUTO,
                present=self.presence.is_present(now),
            )
            self.releaser.release([firing], ReleaseReason.IMMEDIATE, destination, now)
            fired.append(firing)
        return fired
