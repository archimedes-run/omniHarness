"""T078 — quiet-hours release and queue expiry are ONE mechanism (Gate 3)."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime

from app.trigger_engine.destinations.base import QuietDestination
from app.trigger_engine.models import Firing, ReleaseReason, TriggerEvent, TriggerType
from app.trigger_engine.politeness import interrupt, quiet_hours
from app.trigger_engine.politeness.release import Releaser

NOW = datetime(2026, 8, 21, 7, 45, tzinfo=UTC)


def _firing(rid="r1"):
    ev = TriggerEvent(type=TriggerType.WATCHER, event_id=rid, at=NOW)
    return Firing(rule_id=rid, event=ev, prompt="p", thread_id="t1", reply="x")


def test_both_entry_conditions_reach_the_same_function() -> None:
    """SC-007b — implemented twice, the copy that runs least often acquires
    defects nobody sees."""
    dest = QuietDestination()
    r = Releaser(redact=lambda t: (t, True), still_true=lambda f: True, audit=lambda f, n: None)
    for reason in (ReleaseReason.QUIET_HOURS_ENDED, ReleaseReason.QUEUE_EXPIRED):
        r.release([_firing()], reason, dest, NOW)
    assert len(dest.delivered) == 2  # both went through release()


def test_neither_politeness_module_delivers_on_its_own() -> None:
    """The structural assertion: quiet_hours and interrupt QUEUE and RELEASE
    decisions, they never touch a destination. Only release() delivers."""
    for mod in (quiet_hours, interrupt):
        src = inspect.getsource(mod)
        assert ".deliver(" not in src, f"{mod.__name__} delivers directly, bypassing release() — that is a second delivery path"
