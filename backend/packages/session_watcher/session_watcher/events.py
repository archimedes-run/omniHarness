"""Record -> event normalization (FR-007).

Maps an interpreted record onto exactly one EventKind. A record matching no kind
produces NO event rather than a defaulted one — a defaulted PROGRESS would be an
invented observation, which Article X forbids.
"""

from __future__ import annotations

from .adapters.base import END_OF_TURN_REASONS, ParsedRecord
from .models import EventKind, SessionEvent, SummaryProvenance


def to_event(
    record: ParsedRecord,
    *,
    summary: str = "",
    provenance: SummaryProvenance = SummaryProvenance.MECHANICAL,
) -> SessionEvent | None:
    if record.kind is None:
        return None
    return SessionEvent(
        kind=record.kind,
        at=record.at,
        summary=summary or record.text[:200],
        summary_provenance=provenance,
    )


def classify(
    raw_type: str,
    *,
    is_first: bool = False,
    stop_reason: str | None = None,
) -> EventKind | None:
    """Map an observed record onto the normalized vocabulary (FR-007).

    COMPLETED comes from an OBSERVED marker — `message.stop_reason == "end_turn"`
    — not from absence of activity. That is what lets FR-006a stand as written:
    completed is a fact, stalled is an inference, and the two never collapse.

    Deliberately conservative otherwise: anything unrecognised returns None and is
    counted, never folded into PROGRESS. Silent absorption is how a parser ends up
    ignoring a third of a file while passing every fixture test.

    QUESTION is not produced here — waiting-on-user is inferred from session
    structure rather than any single record, and lands with Story 2 (T047).
    """
    if raw_type in {"error", "api-error"}:
        return EventKind.FAILED
    if raw_type == "assistant":
        if stop_reason in END_OF_TURN_REASONS:
            return EventKind.COMPLETED
        return EventKind.PROGRESS
    if raw_type == "user":
        return EventKind.STARTED if is_first else EventKind.PROGRESS
    return None
