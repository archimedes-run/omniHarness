"""Session state resolution: marker first, time second (FR-006, FR-006a, FR-006b).

The ordering is a hard invariant, not an optimisation. A session that recorded an
end-of-turn must NEVER be reported as stalled just because the timeout also
elapsed — the marker is an observation and the timeout is an inference, and an
observation always wins.

Verified against a real corpus: `message.stop_reason` is present on 100% of
assistant payloads, and 17 of 22 real sessions carry an observed `end_turn`. So
COMPLETED really is a fact here rather than a hopeful reading of silence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .adapters.base import SessionRef
from .models import IdleReason, Session, SessionState

DEFAULT_INACTIVITY = timedelta(minutes=5)


@dataclass
class StateConfig:
    #: How long a session may be quiet before we INFER it stalled. Configurable
    #: because long builds and slow test suites legitimately go quiet (FR-006b).
    inactivity: timedelta = DEFAULT_INACTIVITY


def resolve(ref: SessionRef, *, now: datetime, config: StateConfig | None = None) -> Session:
    """Turn a discovered session into a Session with a resolved state."""
    config = config or StateConfig()
    dated = [r for r in ref.records if r.at is not None]

    # FR-006: records present but none interpretable -> UNKNOWN, never a
    # confident state. Distinct from STALLED: unknown means "could not
    # interpret", stalled means "interpreted and saw nothing happening".
    if not dated:
        stamp = now
        return Session(
            session_id=ref.session_id,
            project=ref.project,
            state=SessionState.UNKNOWN,
            started_at=stamp,
            last_activity_at=stamp,
        )

    first = min(dated, key=lambda r: r.at)
    last = max(dated, key=lambda r: r.at)
    assistant = [r for r in dated if r.raw_type == "assistant"]
    last_assistant = max(assistant, key=lambda r: r.at) if assistant else None
    last_text = next((r.text for r in sorted(dated, key=lambda r: r.at, reverse=True) if r.text), "")

    state, reason = _classify_state(
        last_assistant=last_assistant,
        last_at=last.at,
        now=now,
        inactivity=config.inactivity,
    )
    return Session(
        session_id=ref.session_id,
        project=ref.project,
        state=state,
        idle_reason=reason,
        started_at=first.at,
        last_activity_at=last.at,
        last_message=last_text,
        sticky=True,
    )


def _classify_state(
    *,
    last_assistant,
    last_at: datetime,
    now: datetime,
    inactivity: timedelta,
) -> tuple[SessionState, IdleReason | None]:
    # MARKER FIRST. An observed end-of-turn ends the turn, full stop — regardless
    # of how long ago it was. Checking the clock before the marker is the bug this
    # ordering exists to prevent.
    if last_assistant is not None and last_assistant.is_end_of_turn:
        return SessionState.IDLE, IdleReason.COMPLETED

    # TIME SECOND, and only in the marker's absence. This branch is an inference,
    # which is why the state carries STALLED rather than COMPLETED and why FR-016a
    # makes the assistant hedge when reporting it.
    if now - last_at >= inactivity:
        return SessionState.IDLE, IdleReason.STALLED

    # Quiet, but not yet quiet enough to infer anything. Still working.
    return SessionState.WORKING, None
