"""Calendar trigger source (FR-024, FR-025, FR-026).

Fires a stated interval before a calendar event.

**FR-025 REQUIRED A FINDING BEFORE BUILDING**: does this need changes to the
engine's core? The answer is TWO REGISTRATION POINTS AND NOTHING ELSE, and both
were deliberately left open for exactly this:

  1. `config.py` rejected `type: calendar` at load with an explicit
     not-implemented error, above a comment reading "reserved so adding it
     later is a new source rather than a schema migration". Removing the
     rejection is that plan being executed.
  2. `fingerprint.PERMITTED_INPUTS` is a per-type registry of which event
     fields may contribute to a fingerprint. Adding an entry is registration.

The runner, the loop, the release path, coalescing, quiet hours, the interrupt
queue and the injector are all UNCHANGED. This is a source, as the requirement
asks.

**WHY THE FINGERPRINT INPUTS ARE WHAT THEY ARE.** The no-repetition guarantee
(FR-027, FR-017) turns entirely on this. A calendar event has fields that drift
on every poll — how long until it starts, whether it is "soon" — and any of them
in a fingerprint makes each evaluation a NEW event, so the pre-alert fires on
every tick. That is the inverse of the repeat failure and the worse one.

Permitted: the event id and the occurrence start. Both are stable for a given
occurrence, and the start is what distinguishes one instance of a recurring
meeting from the next.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..models import Rule, TriggerEvent, TriggerType
from .base import SourceUnavailable, TriggerSource

logger = logging.getLogger(__name__)

#: How far ahead to look. Bounded so a calendar with a year of events does not
#: make every poll proportional to the calendar's size.
DEFAULT_HORIZON = timedelta(hours=24)


@dataclass
class CalendarSource(TriggerSource):
    """Emits one event per upcoming meeting once it is within the lead time.

    `fetch_events` returns the raw upcoming events and is injected, so this
    module has no opinion about which calendar worker provides them and no
    import of one.
    """

    fetch_events: Callable[[datetime, datetime], list[dict]]
    horizon: timedelta = DEFAULT_HORIZON

    def poll(self, rule: Rule, now: datetime) -> list[TriggerEvent]:
        lead = timedelta(seconds=int(rule.match.get("minutes_before", 5)) * 60)

        try:
            raw = self.fetch_events(now, now + self.horizon)
        except SourceUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            # FR-029's distinction: unreachable is NOT "no meetings". Reporting
            # a failed lookup as an absence would tell the user their afternoon
            # is clear when it is not.
            raise SourceUnavailable(f"calendar unreachable: {exc}") from exc

        events: list[TriggerEvent] = []
        for item in raw or []:
            start = _start_of(item)
            if start is None:
                logger.debug("skipping calendar item with no usable start: %r", item.get("id"))
                continue
            # Fire when we are INSIDE the lead window and the meeting has not
            # already begun. Written as ONE condition because the earlier
            # two-part version disagreed with itself: it required the alert
            # moment to be still in the future AND to have already passed, so
            # only the exact tick where they coincided ever fired.
            alert_at = start - lead
            if not (alert_at <= now < start <= now + self.horizon):
                continue

            events.append(
                TriggerEvent(
                    type=TriggerType.CALENDAR,
                    #: Natural key for THIS OCCURRENCE. A recurring meeting must
                    #: alert before each instance, so the id alone is not enough.
                    event_id=f"{item.get('id')}@{start.isoformat()}",
                    at=start,
                    fields={
                        "summary": item.get("summary") or "(no title)",
                        "attendees": _attendees(item),
                        "description": (item.get("description") or "")[:500],
                        "starts_at": start.isoformat(),
                        "minutes_before": int(lead.total_seconds() // 60),
                    },
                    #: ONLY non-drifting values. See the module docstring.
                    fingerprint_inputs={"event_id": str(item.get("id")), "starts_at": start.isoformat()},
                )
            )
        return events


def _start_of(item: dict) -> datetime | None:
    raw = (item.get("start") or {}).get("dateTime") if isinstance(item.get("start"), dict) else item.get("start")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def _attendees(item: dict) -> list[str]:
    out = []
    for attendee in item.get("attendees") or []:
        if isinstance(attendee, dict):
            name = attendee.get("displayName") or attendee.get("email")
            if name and not attendee.get("self"):
                out.append(name)
        elif attendee:
            out.append(str(attendee))
    return out
