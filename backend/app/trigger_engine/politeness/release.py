"""THE single release path (Gate 3; FR-013b, FR-013d, FR-015, FR-016c).

Three entry conditions — immediate delivery, quiet-hours release, queue expiry —
and ONE mechanism:

    re-check  ->  coalesce  ->  redact  ->  deliver

Implemented twice, the copy that runs least often acquires defects nobody sees.
So there is exactly one `release()`, and Gate 3 exists to prove no second
delivery path appears beside it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from ..models import Firing, Outcome, ReleaseReason, TriggerType
from .coalesce import merge

logger = logging.getLogger(__name__)

#: Trigger types whose condition can be re-evaluated later. A cron or completion
#: event describes something that ALREADY HAPPENED, so there is nothing live to
#: re-check — those expire rather than delivering unverified (FR-013c).
RECHECKABLE = frozenset({TriggerType.WATCHER})


@dataclass
class Releaser:
    """Delivers firings. The only thing that does."""

    redact: Callable[[str], tuple[str, bool]]
    #: Returns True when the firing's condition still holds. Only consulted for
    #: re-checkable types.
    still_true: Callable[[Firing], bool]
    audit: Callable[[Firing, datetime], None]

    def release(
        self,
        firings: list[Firing],
        reason: ReleaseReason,
        destination,
        now: datetime,
    ) -> str | None:
        """Re-check, coalesce, redact, deliver. Returns the delivered text."""
        survivors: list[Firing] = []
        for f in firings:
            if reason is ReleaseReason.IMMEDIATE:
                survivors.append(f)
                continue
            if f.event.type not in RECHECKABLE:
                # FR-013c — without this, "re-check" degrades into "deliver
                # anything we cannot disprove".
                f.resolve(Outcome.EXPIRED, f"{reason}: {f.event.type} has no re-checkable condition")
                self.audit(f, now)
                continue
            if not self.still_true(f):
                f.resolve(Outcome.EXPIRED, f"{reason}: condition no longer holds")
                self.audit(f, now)
                continue
            survivors.append(f)

        if not survivors:
            # Silence is the correct output when nothing survived; an empty
            # message would be worse than none.
            logger.debug("release(%s): nothing survived re-check", reason)
            return None

        text = merge(survivors)
        safe, ok = self.redact(text)
        if not ok:
            # FR-008b — fail closed. No human is waiting on a proactive reply,
            # so a silent pass-through would be invisible.
            for f in survivors:
                f.resolve(Outcome.FAILED, "redaction failed; delivery suppressed")
                self.audit(f, now)
            logger.warning("release(%s): redaction failed, suppressed", reason)
            return None

        destination.deliver(safe)
        for f in survivors:
            f.resolve(Outcome.DELIVERED)
            self.audit(f, now)
        return safe
