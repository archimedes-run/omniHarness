"""Presence — derived from provenance, never from host idleness (FR-022, FR-023).

FR-009 already requires synthetic turns to be structurally distinguishable from
user turns. Given that, a turn WITHOUT the marker *is* a user turn, and its
timestamp is exactly the signal FR-022 asks for. No second mechanism, and
nothing to fall out of sync with the first.

It must NOT come from operating-system idle time: the engine is expected to run
on a dedicated always-on host, whose idleness says nothing about whether the
user is present. Thread `updated_at` is equally wrong — it advances on assistant
replies, so it would report the engine's own activity as user presence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .injector import is_synthetic

DEFAULT_THRESHOLD = timedelta(minutes=5)


@dataclass
class PresenceSignal:
    """The time of the user's last inbound turn, and whether they seem present.

    Observable at runtime (FR-023) while only remote destinations exist, so
    adding the local destination later needs no rework of presence itself.
    """

    #: A stated default, not a measured one (Article X).
    threshold: timedelta = DEFAULT_THRESHOLD
    last_user_turn_at: datetime | None = None

    def observe_runs(self, runs: list[dict]) -> datetime | None:
        """Update from a list of run records, ignoring our own injected turns."""
        for run in runs:
            if is_synthetic(run):
                continue
            ts = run.get("created_at") or run.get("updated_at")
            at = _parse(ts)
            if at and (self.last_user_turn_at is None or at > self.last_user_turn_at):
                self.last_user_turn_at = at
        return self.last_user_turn_at

    def is_present(self, now: datetime) -> bool:
        if self.last_user_turn_at is None:
            return False
        return now - self.last_user_turn_at < self.threshold

    def describe(self, now: datetime) -> dict:
        """Runtime-inspectable state (FR-023)."""
        return {
            "last_user_turn_at": self.last_user_turn_at.isoformat() if self.last_user_turn_at else None,
            "threshold_seconds": int(self.threshold.total_seconds()),
            "present": self.is_present(now),
            "source": "last inbound user turn (never host idle time)",
        }


def _parse(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    from datetime import UTC

    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
