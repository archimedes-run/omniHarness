"""Scheduling without busy-poll (FR-018, FR-027).

Compute the next due moment across all rules, sleep until it, evaluate,
recompute. One timer, O(1) work while idle — a tick loop would burn CPU to
learn nothing, which Article VI forbids.

Each scheduled instant fires AT MOST ONCE, including across restarts, sleep and
wake, and clock adjustments. A missed instant fires once, late, rather than
being skipped or fired once per tick missed.
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

    def due_instants(self, rule_id: str, expr: str, now: datetime, *, since: datetime | None = None) -> list[datetime]:
        """Scheduled instants that have passed and not yet fired.

        `since` bounds how far back a restart looks. Without it, a rule that has
        been off for a month would fire once per missed instant on resume —
        which is the "fired once per missed tick" failure, not the "fires once,
        late" behaviour FR-018 asks for.
        """
        floor = since or (now - timedelta(days=1))
        out: list[datetime] = []
        cursor = previous_due(expr, now)
        while cursor > floor:
            if not self.has_fired(rule_id, cursor):
                out.append(cursor)
            cursor = previous_due(expr, cursor)
        return sorted(out)

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
