"""Core entities for the trigger engine (data-model.md)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class TriggerType(StrEnum):
    CRON = "cron"
    WATCHER = "watcher"
    COMPLETION = "completion"
    #: Reserved so adding it later is a new source rather than a schema
    #: migration. Rejected at load with an explicit not-implemented error.
    CALENDAR = "calendar"


class Destination(StrEnum):
    REMOTE = "remote"
    QUIET = "quiet"
    AUTO = "auto"
    #: Registers against the same port in the voice feature (FR-020).
    LOCAL = "local"


class Outcome(StrEnum):
    DELIVERED = "delivered"
    SUPPRESSED = "suppressed"
    QUEUED = "queued"
    EXPIRED = "expired"
    FAILED = "failed"


class ReleaseReason(StrEnum):
    """Why release() was entered. Three entry conditions, one mechanism."""

    IMMEDIATE = "immediate"
    QUIET_HOURS_ENDED = "quiet-hours-ended"
    QUEUE_EXPIRED = "queue-expired"


@dataclass(frozen=True)
class Rule:
    id: str
    type: TriggerType
    match: dict
    prompt: str
    destination: Destination = Destination.AUTO
    urgent: bool = False
    enabled: bool = True


@dataclass(frozen=True)
class TriggerEvent:
    type: TriggerType
    #: Natural key — scheduled instant, session id, task id.
    event_id: str
    at: datetime
    #: Available to prompt interpolation.
    fields: dict = field(default_factory=dict)
    #: ONLY non-drifting values. See fingerprint.py for why this is separate
    #: from `fields`: a drifting input makes every evaluation yield a "new"
    #: event, which is the inverse of the repeat failure and the worse one.
    fingerprint_inputs: dict = field(default_factory=dict)


@dataclass
class Firing:
    rule_id: str
    event: TriggerEvent
    prompt: str
    thread_id: str | None = None
    reply: str | None = None
    outcome: Outcome | None = None
    reason: str = ""

    def resolve(self, outcome: Outcome, reason: str = "") -> Firing:
        """Set the outcome. Every non-DELIVERED outcome MUST carry a reason.

        A firing that vanished without one is indistinguishable from a firing
        that never happened — the same class of defect as an empty registry
        reading as "no sessions running".
        """
        if outcome is not Outcome.DELIVERED and not reason:
            raise ValueError(f"outcome {outcome} requires a reason (FR-012)")
        self.outcome = outcome
        self.reason = reason
        return self
