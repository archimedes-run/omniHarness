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

from ..models import Firing, Outcome, ReleaseReason, TriggerType

logger = logging.getLogger(__name__)

#: How long a proactive turn waits behind an exchange before being released.
#:
#: A HEURISTIC, and labelled one (Article X). A user who closed their browser
#: mid-run and a user reading a reply and about to type are indistinguishable to
#: this system, so any bound here is an assumption about human behaviour rather
#: than a derived value.
DEFAULT_MAX_WAIT = timedelta(minutes=5)
#: How long a SCHEDULED message (cron) may wait behind an exchange that has not
#: ended before it expires (FR-016d). A choice, not a measurement: a morning
#: brief two hours late is still worth reading; much later, it is not a brief.
DEFAULT_SCHEDULE_MAX_WAIT = timedelta(hours=2)
#: Event types whose condition can be re-checked, and which therefore keep the
#: short FR-016b bound. Mirrors politeness.release.RECHECKABLE.
_RECHECKABLE = frozenset({TriggerType.WATCHER})

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
    schedule_max_wait: timedelta = DEFAULT_SCHEDULE_MAX_WAIT
    _queued: list[tuple[Firing, datetime]] = field(default_factory=list)

    def hold(self, firing: Firing, now: datetime, reason: str = "user is mid-exchange on the target thread") -> None:
        firing.resolve(Outcome.QUEUED, reason)
        self._queued.append((firing, now))

    def due(self, now: datetime, still_busy: Callable[[str], bool], on_expire: Callable[[Firing], None] | None = None) -> list[Firing]:
        """Firings ready to release. Each carries `release_reason`.

        Re-checkable (watcher): released when the exchange ends, or at the
        FR-016b bound even if it has not — for a hung run no completion signal
        ever arrives, so the bound is the primary path, not a net.

        Scheduled (cron, and anything else with nothing to re-check): released
        only when the exchange ENDS, and delivered then (FR-016d). If it has not
        ended within `schedule_max_wait`, the firing expires and `on_expire` is
        told, so the expiry is audited rather than silent. It used to share the
        5-minute bound and then be expired by release() as un-recheckable — a
        brief missed because the user was chatting.
        """
        ready, held = [], []
        for firing, queued_at in self._queued:
            free = not still_busy(firing.thread_id or "")
            waited = now - queued_at
            if free:
                firing.release_reason = ReleaseReason.EXCHANGE_ENDED
                ready.append(firing)
            elif firing.event.type in _RECHECKABLE and waited >= self.max_wait:
                logger.info("rule %s: releasing after %s — the exchange never signalled completion", firing.rule_id, self.max_wait)
                firing.release_reason = ReleaseReason.QUEUE_EXPIRED
                ready.append(firing)
            elif firing.event.type not in _RECHECKABLE and waited >= self.schedule_max_wait:
                firing.resolve(Outcome.EXPIRED, f"held {self.schedule_max_wait} behind an exchange that did not end; not delivered")
                logger.info("rule %s: expired after waiting %s behind an exchange", firing.rule_id, self.schedule_max_wait)
                if on_expire is not None:
                    on_expire(firing)
            else:
                held.append((firing, queued_at))
        self._queued = held
        return ready

    def __len__(self) -> int:
        return len(self._queued)
