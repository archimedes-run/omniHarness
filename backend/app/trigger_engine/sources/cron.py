"""Scheduled triggers (FR-002, FR-018)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..models import Rule, TriggerEvent, TriggerType
from ..scheduler import Scheduler
from .base import TriggerSource


@dataclass
class CronSource(TriggerSource):
    scheduler: Scheduler

    def poll(self, rule: Rule, now: datetime) -> list[TriggerEvent]:
        expr = rule.match.get("schedule")
        if not expr:
            return []
        instant, skipped = self.scheduler.catch_up(rule.id, expr, now)
        if instant is None:
            return []
        return [
            TriggerEvent(
                type=TriggerType.CRON,
                event_id=instant.isoformat(),
                at=instant,
                # `late_by_seconds` and `skipped` drift between evaluations and
                # are deliberately NOT fingerprint inputs; they only shape the
                # note in the delivered message (compose.late_note).
                fields={"scheduled_at": instant.isoformat(), "late_by_seconds": int((now - instant).total_seconds()), "skipped": skipped},
                # The instant itself is the only non-drifting input a schedule
                # has, and it is exactly the right one: two firings of the same
                # instant are the same event.
                fingerprint_inputs={"scheduled_at": instant.isoformat()},
            )
        ]
