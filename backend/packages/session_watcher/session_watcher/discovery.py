"""Recency window and sticky membership (FR-001, FR-005a-c).

Two rules that look similar and are not:

  * the WINDOW bounds what gets read at startup (FR-005d/e), and
  * STICKINESS bounds what stays listed once we have seen it (FR-005c).

Re-testing a live session against the window on every query is the bug this
module exists to prevent: a long-running session that goes quiet during a slow
build would age out mid-run and vanish from the roll-up while still alive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .adapters.base import SessionAdapter, SessionRef

DEFAULT_WINDOW = timedelta(hours=24)


@dataclass
class DiscoveryConfig:
    window: timedelta = DEFAULT_WINDOW


@dataclass
class Discovery:
    """Discovers sessions and remembers the ones it has seen alive."""

    adapter: SessionAdapter
    config: DiscoveryConfig = field(default_factory=DiscoveryConfig)
    _sticky: set[str] = field(default_factory=set)

    def sweep(self, *, now: datetime | None = None) -> list[SessionRef]:
        """One discovery pass. Sessions found here become sticky (FR-005b)."""
        refs = self.adapter.discover(self.config.window, now=now)
        for ref in refs:
            self._sticky.add(ref.session_id)
        return refs

    def is_sticky(self, session_id: str) -> bool:
        return session_id in self._sticky

    def release(self, session_id: str) -> None:
        """Drop stickiness once a session is terminal or retention resets it.

        Called by the registry, never by a query path — that separation is what
        keeps membership from being silently re-decided on read.
        """
        self._sticky.discard(session_id)

    @property
    def sticky_ids(self) -> frozenset[str]:
        return frozenset(self._sticky)
