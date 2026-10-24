"""Core entities for the trigger engine (data-model.md)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class TriggerType(StrEnum):
    CRON = "cron"
    WATCHER = "watcher"
    #: Parsed, but an ENABLED completion or calendar rule is rejected at load
    #: unless the engine has a source for it (config.check_sources). Neither
    #: has one in production yet: sources/completion.py and sources/calendar.py
    #: exist, and nothing supplies them a feed.
    COMPLETION = "completion"
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
    #: The exchange a firing was held behind finished. Unlike the two above,
    #: an event that already happened (cron) is DELIVERED here, not expired:
    #: the user was talking, not away, and a morning brief missed for that is
    #: a worse failure than a late one (002 clarification, 2026-10-19).
    EXCHANGE_ENDED = "exchange-ended"


@dataclass(frozen=True)
class Rule:
    id: str
    type: TriggerType
    match: dict
    prompt: str
    destination: Destination = Destination.AUTO
    urgent: bool = False
    enabled: bool = True
    #: What the person called it ("Morning brief"). Display only: the id stays
    #: the key (thread map, audit log), so a rename never moves its history.
    name: str = ""
    #: Feature 006-F: the custom agent this rule's firings run AS (its
    #: instructions, tools, skills and grants). None: the lead agent. Checked
    #: before every firing (RuleRunner.agent_exists): a missing agent fails the
    #: firing, it is never run as the lead in its place.
    agent: str | None = None
    #: Feature 006-F: whether Home lists this rule's upcoming runs and results.
    show_on_home: bool = True


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
    #: Shared by every firing delivered in ONE coalesced message (FR-021).
    #:
    #: NOT AN OUTCOME. A coalesced firing was DELIVERED — the merge changed how
    #: many messages the user received, not whether this firing succeeded. A
    #: COALESCED member of Outcome would put a false statement in the audit log,
    #: which is why the identity lives here instead.
    #:
    #: None means this firing was delivered on its own. The field's presence is
    #: therefore meaningful, and a test asserts a solo delivery leaves it unset.
    batch_id: str | None = None
    #: The composed message WITHOUT a late note, so the note can be rewritten
    #: for the moment of delivery when a firing is held.
    body: str | None = None
    #: Set by InterruptQueue.due: why a held firing is being released.
    release_reason: ReleaseReason | None = None

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
