"""Core entities for the session watcher (data-model.md).

Everything here is in-memory. Nothing is persisted, and nothing in this module
ever opens a file — record access goes through RecordSource, which is the single
seam the startup bound is asserted on (Gate 3).

Stdlib dataclasses rather than pydantic: this package carries two dependencies on
purpose (Article VI), and the validation needed here is one invariant.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class SessionState(StrEnum):
    """The five states a session can be in.

    COMPLETED is deliberately absent — it is an IdleReason, not a state. That is
    the structural expression of the Q1 clarification: completed and stalled are
    both idle, and the difference between them must survive rather than collapse
    into a single "finished" bucket.
    """

    WORKING = "working"
    WAITING_ON_USER = "waiting-on-user"
    IDLE = "idle"
    FAILED = "failed"
    UNKNOWN = "unknown"


class IdleReason(StrEnum):
    """How a session became idle. The epistemic status differs, and that matters.

    COMPLETED is a fact — an end-of-turn record was observed.
    STALLED is an inference — the timeout elapsed and nothing was observed.

    FR-016a binds the wording each of these produces. Never collapse them.
    """

    COMPLETED = "completed"
    STALLED = "stalled"


class EventKind(StrEnum):
    STARTED = "started"
    PROGRESS = "progress"
    QUESTION = "question"
    COMPLETED = "completed"
    FAILED = "failed"


class SummaryProvenance(StrEnum):
    """Whether a summary came from a model or from mechanical derivation (FR-008c).

    Carried so a future consumer — one speaking summaries aloud, say — can treat
    the two differently.
    """

    MODEL = "model"
    MECHANICAL = "mechanical"


@dataclass(frozen=True)
class SessionEvent:
    kind: EventKind
    at: datetime
    summary: str = ""
    summary_provenance: SummaryProvenance = SummaryProvenance.MECHANICAL


@dataclass
class Session:
    """One observed coding-agent run. Discovered, never created by us (FR-001)."""

    session_id: str
    project: str
    state: SessionState
    started_at: datetime
    last_activity_at: datetime
    idle_reason: IdleReason | None = None
    last_message: str = ""
    sticky: bool = False
    events: list[SessionEvent] = field(default_factory=list)
    #: The clock the state was decided with. Durations in replies are measured
    #: from HERE, not from the caller's "now" — otherwise a reply can pair a state
    #: resolved at one time with an age computed at another and say something
    #: self-contradictory, e.g. "hasn't moved in less than a minute; may have
    #: stalled". Coherence by construction rather than by discipline.
    resolved_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.session_id:
            raise ValueError("session_id must be non-empty; records lacking one are skipped")
        # FR-003a: the whole point is that state and reason never drift apart, so
        # the invariant is enforced at construction rather than at the read site.
        if self.state is SessionState.IDLE and self.idle_reason is None:
            raise ValueError("an IDLE session must record whether it COMPLETED or STALLED (FR-003a)")
        if self.state is not SessionState.IDLE and self.idle_reason is not None:
            raise ValueError(f"idle_reason is only meaningful for IDLE sessions, not {self.state}")
        if self.last_activity_at < self.started_at:
            raise ValueError("last_activity_at cannot precede started_at")

    @property
    def is_terminal(self) -> bool:
        """Terminal for retention purposes (FR-005c).

        STALLED is deliberately NOT terminal: we inferred it rather than observed
        it, so the session may yet resume and must not be dropped on an inference.
        """
        if self.state is SessionState.FAILED:
            return True
        return self.state is SessionState.IDLE and self.idle_reason is IdleReason.COMPLETED

    def _clock(self, now: datetime) -> datetime:
        return self.resolved_at or now

    def elapsed_seconds(self, now: datetime) -> int:
        return max(0, int((self._clock(now) - self.started_at).total_seconds()))

    def quiet_seconds(self, now: datetime) -> int:
        """Seconds of silence, measured against the clock the state was decided with."""
        return max(0, int((self._clock(now) - self.last_activity_at).total_seconds()))
