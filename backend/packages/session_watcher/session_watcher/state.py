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
from .events import to_event, waiting_event
from .models import IdleReason, Session, SessionState

#: How many recent events a session retains for the detail reply (FR-013).
MAX_EVENTS = 20

DEFAULT_INACTIVITY = timedelta(minutes=5)
#: How long a session must sit on an unanswered assistant turn before we call it
#: possibly-blocked. Short, deliberately: see WAITING_BIAS below.
DEFAULT_WAITING_AFTER = timedelta(seconds=45)


@dataclass
class StateConfig:
    #: How long a session may be quiet before we INFER it stalled. Configurable
    #: because long builds and slow test suites legitimately go quiet (FR-006b).
    inactivity: timedelta = DEFAULT_INACTIVITY
    #: How long an unanswered assistant turn sits before we surface it as
    #: possibly-blocked.
    waiting_after: timedelta = DEFAULT_WAITING_AFTER


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
            resolved_at=now,
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
        waiting_after=config.waiting_after,
        asked_question=_asked_question(dated),
    )
    session = Session(
        session_id=ref.session_id,
        project=ref.project,
        state=state,
        idle_reason=reason,
        started_at=first.at,
        last_activity_at=last.at,
        last_message=last_text,
        sticky=True,
        resolved_at=now,
    )
    # Recent activity, newest last, bounded. Only classified records become
    # events — an unclassified record is not silently promoted to PROGRESS
    # (FR-007), so a quiet session shows few events rather than invented ones.
    for rec in sorted(dated, key=lambda r: r.at)[-MAX_EVENTS:]:
        ev = to_event(rec)
        if ev is not None:
            session.events.append(ev)
    if state is SessionState.WAITING_ON_USER:
        session.events.append(waiting_event(session, last.at))
    return session


def _classify_state(
    *,
    last_assistant,
    last_at: datetime,
    now: datetime,
    inactivity: timedelta,
    waiting_after: timedelta,
    asked_question: bool,
) -> tuple[SessionState, IdleReason | None]:
    """Resolve state. Read the ordering comments before reordering anything.

    On waiting-on-user, and why it keys on a question rather than on a pending
    tool call: the T055 spike established that a session paused on a permission
    prompt and a session running a ten-minute build produce the SAME trace — an
    assistant `tool_use` with nothing after it. Treating that shape as blocked
    would report every long build as "waiting on you", which is a false positive
    that fires constantly.

    That is not the silence the error-direction ruling warns against, because the
    pending-tool case is NOT dropped: it stays WORKING until the inactivity
    period, then becomes IDLE/STALLED — "hasn't moved in 12 minutes; may have
    stalled or been killed" — which prompts the user to go and look anyway. The
    expensive failure the ruling targets, a blocked session sitting silently all
    evening, is covered by that path.

    What IS distinguishable is a completed turn whose last words were a question
    with no reply since. That is cheap evidence and rarely wrong, so it earns the
    flag.
    """
    quiet = now - last_at
    ended_turn = last_assistant is not None and last_assistant.is_end_of_turn

    # WAITING-ON-USER, narrow and evidence-backed: the turn ENDED (observed), its
    # last words were a question, and it is recent enough that a reply is still
    # plausibly owed. Bounded by `inactivity` so an old finished session that
    # happened to end on "Anything else?" reads as finished, not as waiting
    # forever.
    if ended_turn and asked_question and waiting_after <= quiet < inactivity:
        return SessionState.WAITING_ON_USER, None

    # MARKER FIRST. An observed end-of-turn ends the turn, regardless of how long
    # ago. Checking the clock before the marker is the bug this ordering prevents.
    if ended_turn:
        return SessionState.IDLE, IdleReason.COMPLETED

    # TIME. Only in the marker's absence, and an inference — hence STALLED, not
    # COMPLETED. This is also the path that catches a session blocked on a
    # permission prompt, since that is indistinguishable from a running tool.
    if quiet >= inactivity:
        return SessionState.IDLE, IdleReason.STALLED

    return SessionState.WORKING, None


def _asked_question(dated) -> bool:
    """Did the session end on an assistant question that nobody answered?

    Weak evidence by construction — a trailing "?" is a heuristic, not a marker,
    which is exactly why FR-016a makes the reply hedge. It is still far better
    evidence than a pending tool call, which carries none at all.
    """
    if not dated:
        return False
    ordered = sorted(dated, key=lambda r: r.at)
    for rec in reversed(ordered):
        if rec.raw_type == "user":
            return False
        if rec.raw_type == "assistant":
            text = (rec.text or "").strip()
            if not text:
                return False
            tail = text.rstrip().rstrip(")]}\"'*_`")
            return tail.endswith("?")
    return False
