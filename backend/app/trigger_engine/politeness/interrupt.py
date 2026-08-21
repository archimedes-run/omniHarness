"""Not talking over the user (FR-016, FR-016a-c).

Two signals, both PULL — nothing calls back when an exchange ends:

  * `GET /api/threads/{id}/state` reports a live status
  * a ConflictError on injection means a run is already going

Because neither is push, the bound is not a fallback for a rare case. For a
hung or abandoned run **no completion signal will ever arrive**, so the bound is
the only mechanism that will ever release the item, and it is implemented as the
primary path rather than a safety net.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..models import Firing, Outcome

logger = logging.getLogger(__name__)

#: How long a proactive turn waits behind an exchange before being released.
#:
#: A HEURISTIC, and labelled one (Article X). A user who closed their browser
#: mid-run and a user reading a reply and about to type are indistinguishable to
#: this system, so any bound here is an assumption about human behaviour rather
#: than a derived value.
DEFAULT_MAX_WAIT = timedelta(minutes=5)

BUSY_STATES = frozenset({"busy", "running"})


def is_busy(thread_state: dict) -> bool:
    return str(thread_state.get("status", "")).lower() in BUSY_STATES


def is_thread_busy_error(exc: BaseException) -> bool:
    """The race fallback, matching how the channel manager already detects it."""
    return "already running a task" in str(exc) or type(exc).__name__ == "ConflictError"


@dataclass
class InterruptQueue:
    """Holds firings behind an in-progress exchange, and releases them."""

    max_wait: timedelta = DEFAULT_MAX_WAIT
    _queued: list[tuple[Firing, datetime]] = field(default_factory=list)

    def hold(self, firing: Firing, now: datetime) -> None:
        firing.resolve(Outcome.QUEUED, "user is mid-exchange on the target thread")
        self._queued.append((firing, now))

    def due(self, now: datetime, still_busy: Callable[[str], bool]) -> list[Firing]:
        """Firings ready to release: the exchange ended, or the bound expired.

        The second clause is not a safety net. For a run that emits no
        completion signal it is the ONLY clause that will ever fire.
        """
        ready, held = [], []
        for firing, queued_at in self._queued:
            expired = now - queued_at >= self.max_wait
            free = not still_busy(firing.thread_id or "")
            if expired or free:
                if expired and not free:
                    logger.info(
                        "rule %s: releasing after %s — the exchange never signalled completion",
                        firing.rule_id,
                        self.max_wait,
                    )
                ready.append(firing)
            else:
                held.append((firing, queued_at))
        self._queued = held
        return ready

    def __len__(self) -> int:
        return len(self._queued)
