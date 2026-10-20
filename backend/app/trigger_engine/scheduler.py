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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from croniter import croniter

from ._store import JsonStore

logger = logging.getLogger(__name__)


#: The zone a rule that names none is evaluated in: the user's (Feature 006).
#:
#: MIGRATION: before 006 such a rule ran in UTC (this function returned `t`
#: unchanged, and the engine stamps `now` in UTC). A rule written without a
#: `match.timezone` now fires at its schedule's clock time in New York, so
#: "0 9 * * *" moves from 09:00 UTC to 09:00 America/New_York. Rules that name
#: a zone keep it. To keep the old behaviour, add "timezone": "UTC" to the
#: rule's match. Fired instants are keyed in UTC (Scheduler._key), so the
#: change cannot re-fire an instant that already fired.
DEFAULT_TIMEZONE = "America/New_York"


def _local(t: datetime, tz: str | None) -> datetime:
    """`t` in the rule's zone (DEFAULT_TIMEZONE when it names none). croniter
    evaluates the expression in the zone of the datetime it is given, so
    "45 8 * * 1-5" in America/New_York is 12:45 UTC in summer and 13:45 UTC in
    winter — DST handled by the zone, not by hand-converting the schedule to
    UTC (which is wrong half the year)."""
    return t.astimezone(ZoneInfo(tz or DEFAULT_TIMEZONE))


def next_due(expr: str, after: datetime, tz: str | None = None) -> datetime:
    return croniter(expr, _local(after, tz)).get_next(datetime)


def previous_due(expr: str, before: datetime, tz: str | None = None) -> datetime:
    return croniter(expr, _local(before, tz)).get_prev(datetime)


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
        # Normalised to UTC: the same instant computed in a rule's zone and
        # read back in UTC must be ONE key (FR-018), and keys written before
        # zones existed were already UTC.
        return f"{rule_id}@{instant.astimezone(UTC).isoformat()}"

    def catch_up(self, rule_id: str, expr: str, now: datetime, *, tz: str | None = None, since: datetime | None = None) -> tuple[datetime | None, int]:
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
        cursor = previous_due(expr, now, tz)
        while cursor > floor:
            if not self.has_fired(rule_id, cursor):
                unfired.append(cursor)
            cursor = previous_due(expr, cursor, tz)
        if not unfired:
            return None, 0
        return max(unfired), len(unfired) - 1

    def _last_fired(self, rule_id: str) -> datetime | None:
        prefix = f"{rule_id}@"
        stamps = [k[len(prefix) :] for k in self._store.keys() if k.startswith(prefix)]
        return datetime.fromisoformat(max(stamps)) if stamps else None

    def next_wakeup(self, schedules: list[tuple], now: datetime) -> datetime | None:
        """The earliest next due moment across all rules. None when none.

        Each schedule is (rule_id, expr) or (rule_id, expr, timezone)."""
        candidates = [next_due(s[1], now, s[2] if len(s) > 2 else None) for s in schedules if s[1]]
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
