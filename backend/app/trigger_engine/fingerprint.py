"""Event identity — what makes FR-017's at-most-once guarantee mean something.

The key is `(rule_id, event_id, hash(fingerprint_inputs))`. The interesting part
is not the hash, it is WHICH inputs are permitted:

    A drifting input — elapsed time, last-activity, quiet duration — makes every
    evaluation produce a "new" event, so the user gets an alert per cycle. That
    is the inverse of the repeat failure FR-017 guards against, and it is the
    WORSE of the two, because it is the version that gets the feature muted.

So the permitted inputs are enumerated per trigger type, and the enumeration is
the requirement (FR-017b) rather than a comment about one.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from ._store import JsonStore
from .models import TriggerEvent, TriggerType

logger = logging.getLogger(__name__)

#: FR-017b. Only values that change when the event genuinely changes.
PERMITTED_INPUTS: dict[TriggerType, frozenset[str]] = {
    TriggerType.WATCHER: frozenset({"question", "state", "idle_reason"}),
    TriggerType.CRON: frozenset({"scheduled_at"}),
    TriggerType.COMPLETION: frozenset({"task_id", "status"}),
    #: Feature 003. Both stable for a given occurrence. Deliberately NOT
    #: minutes_until / starts_in / is_soon: those drift on every poll, which
    #: would make each evaluation a new event and fire the pre-alert on every
    #: tick — the inverse of the repeat failure, and the worse one.
    TriggerType.CALENDAR: frozenset({"event_id", "starts_at"}),
}

#: Explicitly excluded, listed so a future contributor sees the intent rather
#: than guessing it. Any of these would drift on every evaluation.
FORBIDDEN_INPUTS = frozenset({"elapsed", "elapsed_seconds", "quiet_seconds", "last_activity_at", "now", "evaluated_at", "duration", "age"})


class FingerprintError(ValueError):
    pass


def compute(rule_id: str, event: TriggerEvent) -> str:
    permitted = PERMITTED_INPUTS.get(event.type, frozenset())
    inputs = event.fingerprint_inputs
    bad = set(inputs) & FORBIDDEN_INPUTS
    if bad:
        raise FingerprintError(f"rule {rule_id!r}: {sorted(bad)} drift on every evaluation and must not contribute to a fingerprint — including them produces an alert per cycle")
    unknown = set(inputs) - permitted
    if unknown:
        raise FingerprintError(f"rule {rule_id!r}: {sorted(unknown)} not permitted for {event.type}; permitted: {sorted(permitted)}")
    canonical = json.dumps({k: inputs[k] for k in sorted(inputs)}, sort_keys=True)
    digest = hashlib.sha256(canonical.encode()).hexdigest()[:16]
    return f"{rule_id}|{event.event_id}|{digest}"


@dataclass
class FingerprintStore:
    """Remembers which events have already fired. Durable, and reset daily."""

    path: Path
    retention: timedelta = timedelta(days=1)
    _store: JsonStore | None = None
    last_reset_at: datetime | None = None

    def __post_init__(self) -> None:
        self._store = JsonStore(path=self.path)

    def seen(self, key: str) -> bool:
        return self._store.get(key) is not None

    def record(self, key: str, now: datetime) -> None:
        self._store.set(key, now.isoformat())

    def maybe_reset(self, now: datetime) -> int:
        """Clear the store on the retention interval (FR-017c).

        A fingerprint older than the interval has no live event left to
        suppress, and unbounded growth is unacceptable in a process shared with
        the gateway.
        """
        if self.last_reset_at is None:
            self.last_reset_at = now
            return 0
        if now - self.last_reset_at < self.retention:
            return 0
        n = len(self._store.keys())
        self._store._data = {}
        self._store.save()
        self.last_reset_at = now
        if n:
            logger.debug("fingerprint retention reset: cleared %d entries", n)
        return n

    def count(self) -> int:
        return len(self._store.keys())
