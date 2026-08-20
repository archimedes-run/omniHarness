"""Record -> event normalization (FR-007).

Maps an interpreted record onto exactly one EventKind. A record matching no kind
produces NO event rather than a defaulted one — a defaulted PROGRESS would be an
invented observation, which Article X forbids.
"""

from __future__ import annotations

from .adapters.base import ParsedRecord
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


def classify(raw_type: str, *, is_first: bool = False) -> EventKind | None:
    """Map an observed record type onto the normalized vocabulary.

    Deliberately conservative: anything not listed returns None and is counted as
    unclassified rather than being folded into PROGRESS. Silent absorption of
    unknown types is how a parser ends up quietly ignoring a third of the file
    while passing every fixture test.
    """
    if raw_type == "user":
        return EventKind.STARTED if is_first else EventKind.PROGRESS
    if raw_type == "assistant":
        return EventKind.PROGRESS
    if raw_type in {"error", "api-error"}:
        return EventKind.FAILED
    return None
