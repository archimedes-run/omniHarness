"""Scheduling without busy-poll (FR-018, FR-027).

Compute the next due moment across all rules, sleep until it, evaluate,
recompute. One timer, O(1) work while idle — a tick loop would burn CPU to
learn nothing, which Article VI forbids.

Each scheduled instant fires AT MOST ONCE, including across restarts, sleep and
wake, and clock adjustments. A missed instant fires once, late, rather than
being skipped or fired once per tick missed — and when several were missed,
only the newest fires, with a note saying how many were skipped.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from croniter import croniter

from ._store import JsonStore

logger = logging.getLogger(__name__)


def next_due(expr: str, after: datetime) -> datetime:
    return croniter(expr, after).get_next(datetime)


def previous_due(expr: str, before: datetime) -> datetime:
    return croniter(expr, before).get_prev(datetime)


@dataclass
class Scheduler:
    """Tracks which scheduled instants have fired. Durable."""

    path: Path
    _store: JsonStore | None = None

    def __post_init__(self) -> None:
        self._store = JsonStore(path=self.path)

    @staticmethod
    def _key(rule_id: str, instant: datetime) -> str:
        # The scheduled INSTANT, not the evaluation time — that is what makes
        # de-duplication survive a clock jump.
        return f"{rule_id}@{instant.isoformat()}"

    def catch_up(self, rule_id: str, expr: str, now: datetime, *, since: datetime | None = None) -> tuple[datetime | None, int]:
        """(the most recent unfired instant, how many older ones were skipped).

        FR-018: "fires once, late". This used to return EVERY unfired instant
        in the look-back window — a */5 rule after a night's outage came back
        to 288 firings, one message each. Now only the newest is fired; the
        rest are reported as skipped, so the message can say so.

        Skipped instants never resurface: the floor is raised to the newest
        instant already fired (the watermark), so once the late firing is
        marked, everything before it is behind the line.

        `since` bounds how far back a restart looks; the default is one day.
        """
        floor = since or (now - timedelta(days=1))
        watermark = self._last_fired(rule_id)
        if watermark is not None and watermark > floor:
            floor = watermark
        unfired: list[datetime] = []
        cursor = previous_due(expr, now)
        while cursor > floor:
            if not self.has_fired(rule_id, cursor):
                unfired.append(cursor)
            cursor = previous_due(expr, cursor)
        if not unfired:
            return None, 0
        return max(unfired), len(unfired) - 1

    def _last_fired(self, rule_id: str) -> datetime | None:
        prefix = f"{rule_id}@"
        stamps = [k[len(prefix) :] for k in self._store.keys() if k.startswith(prefix)]
        return datetime.fromisoformat(max(stamps)) if stamps else None

    def next_wakeup(self, schedules: list[tuple[str, str]], now: datetime) -> datetime | None:
        """The earliest next due moment across all rules. None when none."""
        candidates = [next_due(expr, now) for _, expr in schedules if expr]
        return min(candidates) if candidates else None

    def has_fired(self, rule_id: str, instant: datetime) -> bool:
        return self._store.get(self._key(rule_id, instant)) is not None

    def mark_fired(self, rule_id: str, instant: datetime, now: datetime) -> None:
        self._store.set(self._key(rule_id, instant), now.isoformat())

    def prune(self, before: datetime) -> int:
        """Drop records for instants older than `before`."""
        data = self._store.load()
        stale = [k for k in data if k.rsplit("@", 1)[-1] < before.isoformat()]
        for k in stale:
            data.pop(k, None)
        if stale:
            self._store.save()
        return len(stale)
