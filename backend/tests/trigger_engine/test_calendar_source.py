"""Calendar triggers (T074-T076, FR-024 to FR-027).

FR-025 required a finding BEFORE building: does this need engine changes? It
needed THREE registration points and nothing else —

    config.AVAILABLE_FIELDS       what a calendar prompt may interpolate
    config._parse_rule            the load-time rejection, replaced by a real check
    fingerprint.PERMITTED_INPUTS  which fields may fingerprint

— all per-type registries the engine already had for the other three types. The
runner, loop, release path, coalescing, quiet hours, interrupt queue and
injector are unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.trigger_engine.fingerprint import FingerprintError, compute
from app.trigger_engine.models import Rule, TriggerType
from app.trigger_engine.sources.base import SourceUnavailable
from app.trigger_engine.sources.calendar import CalendarSource

NOW = datetime(2026, 8, 25, 9, 55, tzinfo=UTC)
SOON = {"id": "evt1", "summary": "Darcy sync", "start": {"dateTime": "2026-08-25T10:00:00+00:00"}, "attendees": [{"displayName": "Darcy"}, {"email": "me@example.com", "self": True}], "description": "Q3 plan"}
LATER = {"id": "evt2", "summary": "Retro", "start": {"dateTime": "2026-08-25T18:00:00+00:00"}}


def _rule(minutes_before=5):
    return Rule(id="prep", type=TriggerType.CALENDAR, match={"minutes_before": minutes_before}, prompt="x")


def _source(events):
    return CalendarSource(fetch_events=lambda start, end: events)


def test_only_events_inside_the_lead_time_fire():
    events = _source([SOON, LATER]).poll(_rule(), NOW)

    assert [e.fields["summary"] for e in events] == ["Darcy sync"]


def test_the_lead_time_comes_from_the_rule():
    """A rule asking for 15 minutes gets 15, not a default."""
    assert not _source([SOON]).poll(_rule(minutes_before=1), NOW - timedelta(minutes=10))
    assert _source([SOON]).poll(_rule(minutes_before=30), NOW - timedelta(minutes=10))


def test_the_event_carries_who_and_what(FR_026=None):
    """FR-026 — who the meeting is with and what it is about."""
    event = _source([SOON]).poll(_rule(), NOW)[0]

    assert event.fields["summary"] == "Darcy sync"
    assert event.fields["attendees"] == ["Darcy"]
    assert "Q3 plan" in event.fields["description"]


def test_the_user_is_not_listed_as_an_attendee_of_their_own_meeting():
    """ "You have a meeting with Darcy and yourself" is wrong in a way that
    reads as carelessness."""
    assert "me@example.com" not in _source([SOON]).poll(_rule(), NOW)[0].fields["attendees"]


# ---------------------------------------------------------------------------
# FR-027 — exactly one pre-alert per occurrence
# ---------------------------------------------------------------------------


def test_repeated_evaluation_yields_the_same_fingerprint():
    """The no-repetition guarantee turns entirely on this.

    The engine suppresses a fingerprint it has seen. If polling twice produced
    different fingerprints, the pre-alert would fire on every tick.
    """
    source = _source([SOON])
    first = compute("prep", source.poll(_rule(), NOW)[0])
    second = compute("prep", source.poll(_rule(), NOW + timedelta(minutes=1))[0])

    assert first == second, "the fingerprint drifted between polls; the pre-alert would repeat every tick"


def test_a_recurring_meeting_alerts_once_per_occurrence():
    """The id alone is not enough — the same meeting next week is a new event."""
    week_later = {**SOON, "start": {"dateTime": "2026-09-01T10:00:00+00:00"}}

    this_week = compute("prep", _source([SOON]).poll(_rule(), NOW)[0])
    next_week = compute("prep", _source([week_later]).poll(_rule(), NOW + timedelta(days=7))[0])

    assert this_week != next_week, "two occurrences of a recurring meeting share a fingerprint; the second would be suppressed"


def test_drifting_fields_are_refused_by_the_fingerprint():
    """The trap this guards: 'minutes until' in a fingerprint makes every poll a
    new event, which is the inverse of the repeat failure and worse."""
    event = _source([SOON]).poll(_rule(), NOW)[0]
    event.fingerprint_inputs["elapsed"] = "5"

    with pytest.raises(FingerprintError):
        compute("prep", event)


def test_the_permitted_inputs_are_stable_ones_only():
    from app.trigger_engine.fingerprint import PERMITTED_INPUTS

    assert PERMITTED_INPUTS[TriggerType.CALENDAR] == frozenset({"event_id", "starts_at"})


# ---------------------------------------------------------------------------
# FR-029 — unreachable is not "no meetings"
# ---------------------------------------------------------------------------


def test_an_unreachable_calendar_raises_rather_than_reporting_no_events():
    """Reporting a failed lookup as an empty calendar would tell the user their
    afternoon is clear when it is not."""

    def _boom(start, end):
        raise ConnectionError("network down")

    with pytest.raises(SourceUnavailable):
        CalendarSource(fetch_events=_boom).poll(_rule(), NOW)


def test_an_empty_calendar_is_not_an_error():
    """The discriminator — otherwise the test above passes when everything
    raises."""
    assert _source([]).poll(_rule(), NOW) == []


def test_an_event_with_no_usable_start_is_skipped_not_fatal():
    """One malformed entry must cost one alert, not the whole poll."""
    events = _source([{"id": "broken"}, SOON]).poll(_rule(), NOW)

    assert [e.fields["summary"] for e in events] == ["Darcy sync"]


def test_events_already_started_do_not_fire():
    """A pre-alert for a meeting that began ten minutes ago is noise."""
    assert not _source([SOON]).poll(_rule(), NOW + timedelta(minutes=15))
