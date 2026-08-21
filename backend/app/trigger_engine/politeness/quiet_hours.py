"""Quiet hours (FR-013, FR-013a-d, FR-014).

A suppressed firing is DEFERRED, not dropped: the session that blocked at 2am is
the case the feature exists for. At release each deferred item's condition is
re-checked, and items whose type has no re-checkable condition EXPIRE rather
than delivering unverified — otherwise "re-check" degrades into "deliver
anything we cannot disprove".

Release goes through the same coalescing path as everything else. A backlog
arriving as six separate notifications at 7:30am is the single behaviour most
likely to get the feature muted.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from ..models import Firing, Outcome

logger = logging.getLogger(__name__)


def _parse_hhmm(value: str) -> time:
    hh, _, mm = value.partition(":")
    return time(int(hh), int(mm or 0))


@dataclass
class QuietHours:
    start: str = "22:00"
    end: str = "07:30"
    enabled: bool = True

    def contains(self, at: datetime) -> bool:
        """True when `at` falls inside the window, which may span midnight."""
        if not self.enabled:
            return False
        s, e = _parse_hhmm(self.start), _parse_hhmm(self.end)
        now = at.timetz().replace(tzinfo=None)
        if s <= e:
            return s <= now < e
        # Spans midnight: 22:00–07:30 is one window, not two.
        return now >= s or now < e

    def next_end(self, at: datetime) -> datetime:
        e = _parse_hhmm(self.end)
        candidate = at.replace(hour=e.hour, minute=e.minute, second=0, microsecond=0)
        if candidate <= at:
            candidate += timedelta(days=1)
        return candidate


@dataclass
class DeferralQueue:
    """Holds firings suppressed by quiet hours until the window ends."""

    pending: list[Firing] = field(default_factory=list)

    def defer(self, firing: Firing, now: datetime, reason: str) -> None:
        # SUPPRESSED, not QUEUED. The spec distinguishes them and so should the
        # audit log: FR-013 says quiet hours "suppresses delivery", FR-016 says
        # a mid-exchange turn "queues until that exchange completes". Using one
        # outcome for both loses the reason an operator most wants when reading
        # back a quiet morning — was nothing delivered because of the hour, or
        # because I was mid-conversation?
        firing.resolve(Outcome.SUPPRESSED, reason)
        self.pending.append(firing)

    def drain(self) -> list[Firing]:
        out, self.pending = self.pending, []
        return out

    def __len__(self) -> int:
        return len(self.pending)


def should_suppress(firing_urgent: bool, window: QuietHours, now: datetime) -> tuple[bool, str]:
    """(suppress, reason). Urgency is per-rule and explicit — FR-014 forbids
    any implicit escalation, so this takes the flag and nothing else."""
    if not window.contains(now):
        return False, ""
    if firing_urgent:
        return False, ""
    return True, f"quiet hours {window.start}-{window.end}"
