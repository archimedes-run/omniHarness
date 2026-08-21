"""Recency window and sticky membership (FR-001, FR-005a-c).

Two rules that look similar and are not:

  * the WINDOW bounds what gets read at startup (FR-005d/e), and
  * STICKINESS bounds what stays listed once we have seen it (FR-005c).

Re-testing a live session against the window on every query is the bug this
module exists to prevent: a long-running session that goes quiet during a slow
build would age out mid-run and vanish from the roll-up while still alive.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .adapters.base import SessionAdapter, SessionRef

logger = logging.getLogger(__name__)

DEFAULT_WINDOW = timedelta(hours=24)
#: How often sticky membership and retained terminal sessions are cleared.
#: A day: long enough that a session running overnight keeps its place, short
#: enough that the registry cannot accumulate indefinitely in a long-lived
#: process. This is the "retention reset" FR-005c refers to.
DEFAULT_RETENTION_RESET = timedelta(days=1)


@dataclass
class DiscoveryConfig:
    window: timedelta = DEFAULT_WINDOW
    retention_reset: timedelta = DEFAULT_RETENTION_RESET


@dataclass
class Discovery:
    """Discovers sessions and remembers the ones it has seen alive."""

    adapter: SessionAdapter
    config: DiscoveryConfig = field(default_factory=DiscoveryConfig)
    started_at: datetime | None = None
    last_reset_at: datetime | None = None
    _sticky: set[str] = field(default_factory=set)

    def sweep(self, *, now: datetime | None = None) -> list[SessionRef]:
        """One discovery pass.

        Two filters, easily confused, doing different jobs:

          * mtime selection inside the adapter bounds what is READ (FR-005d/e).
          * the last-activity window here bounds what is LISTED (FR-005a).

        They diverge in practice: a session whose last message is three weeks old
        can still have a recent mtime, because the agent appends bookkeeping
        records to it long after the conversation ends. Filtering only on mtime
        produced a roll-up of nine sessions, eight of them finished weeks ago —
        technically inside the window and useless to read.

        Stickiness (FR-005b) is granted only to sessions seen active AFTER the
        watcher started. Merely appearing in the initial backfill is not being
        "observed active", and treating it as such would make the window
        meaningless on the first sweep.
        """
        now = now or datetime.now().astimezone()
        if self.started_at is None:
            self.started_at = now
        if self.last_reset_at is None:
            self.last_reset_at = now
        elif now - self.last_reset_at >= self.config.retention_reset:
            # The retention reset. Without it `_sticky` only ever grows: a
            # session seen active once keeps its exemption from the recency
            # window for the life of the process, and the set never shrinks.
            self.reset_retention(now)
        refs = self.adapter.discover(self.config.window, now=now)

        cutoff = now - self.config.window
        kept: list[SessionRef] = []
        for ref in refs:
            last = self._last_activity(ref)
            if last is not None and last > self.started_at:
                self._sticky.add(ref.session_id)
            if ref.session_id in self._sticky or (last is not None and last >= cutoff):
                kept.append(ref)
        return kept

    @staticmethod
    def _last_activity(ref: SessionRef) -> datetime | None:
        dated = [r.at for r in ref.records if r.at is not None]
        return max(dated) if dated else None

    def is_sticky(self, session_id: str) -> bool:
        return session_id in self._sticky

    def release(self, session_id: str) -> None:
        """Drop stickiness once a session is terminal or retention resets it.

        Called by the registry, never by a query path — that separation is what
        keeps membership from being silently re-decided on read.
        """
        self._sticky.discard(session_id)

    def reset_retention(self, now: datetime) -> set[str]:
        """Clear sticky membership and report what was dropped (FR-005c).

        Sticky membership exempts a session from the recency window so a live
        session cannot age out mid-run. That exemption has to end somewhere, or
        a session seen active once is exempt forever and the set grows without
        bound in a process meant to run for weeks.
        """
        dropped = set(self._sticky)
        self._sticky.clear()
        self.last_reset_at = now
        if dropped:
            logger.debug("retention reset: released %d sticky session(s)", len(dropped))
        return dropped

    @property
    def sticky_ids(self) -> frozenset[str]:
        return frozenset(self._sticky)
