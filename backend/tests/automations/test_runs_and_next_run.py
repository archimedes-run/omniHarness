"""Feature 006: how the Automations panel words a rule's runs and next run.

Pure functions over audit records shaped exactly as AuditLog.record writes them
(one row per state change), so a held-then-delivered run is two rows.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.gateway.triggers_view import describe_rules, describe_runs, next_run
from app.trigger_engine.config import ConfigError, parse
from app.trigger_engine.models import Destination, Rule, TriggerType


def row(event_id, at, outcome, reason="", *, rule="brief", batch=None, batch_key=True, thread="t-1", event_type="cron"):
    entry = {"actor": "default", "at": at, "rule_id": rule, "event_type": event_type, "event_id": event_id, "thread_id": thread, "outcome": outcome, "reason": reason, "delivered_chars": 10}
    if batch_key:
        entry["batch_id"] = batch
    return entry


def kinds(audit, rule="brief"):
    return {r.event_id: r for r in describe_runs(audit, rule).runs}


def test_a_delivery_that_only_waited_for_the_coalescing_window_reads_delivered() -> None:
    audit = [
        row("2026-10-19T08:45:00-04:00", "2026-10-19T12:45:01+00:00", "queued", "awaiting the coalescing window"),
        row("2026-10-19T08:45:00-04:00", "2026-10-19T12:46:01+00:00", "delivered"),
    ]
    run = kinds(audit)["2026-10-19T08:45:00-04:00"]
    assert run.kind == "delivered" and run.held_because is None and run.thread_id == "t-1"
    assert run.at == "2026-10-19T08:45:00-04:00", "a cron run is dated by when it was due"


def test_held_behind_a_conversation_then_delivered() -> None:
    audit = [
        row("e1", "2026-10-16T12:45:00+00:00", "queued", "user is mid-exchange on the target thread"),
        row("e1", "2026-10-16T13:02:00+00:00", "delivered"),
    ]
    run = kinds(audit)["e1"]
    assert (run.kind, run.held_because, run.settled_at) == ("held-then-delivered", "mid-conversation", "2026-10-16T13:02:00+00:00")


def test_held_for_quiet_hours_then_delivered() -> None:
    audit = [row("e1", "2026-10-16T03:00:00+00:00", "suppressed", "quiet hours"), row("e1", "2026-10-16T11:30:00+00:00", "delivered")]
    assert kinds(audit)["e1"].held_because == "quiet-hours"


def test_delivered_with_others_names_them_once() -> None:
    audit = [
        row("e1", "2026-10-15T12:46:00+00:00", "delivered", batch="b1"),
        row("s9", "2026-10-15T12:46:00+00:00", "delivered", rule="blocked-session", batch="b1", event_type="watcher"),
    ]
    run = kinds(audit)["e1"]
    assert run.kind == "delivered-with-others"
    assert [(m.rule_id, m.event_id) for m in run.delivered_with] == [("blocked-session", "s9")]


def test_a_failure_carries_its_reason_verbatim() -> None:
    audit = [row("e1", "2026-10-14T12:45:00+00:00", "failed", "gave up after 3 attempts: model timeout")]
    run = kinds(audit)["e1"]
    assert (run.kind, run.reason) == ("failed", "gave up after 3 attempts: model timeout")


def test_an_unsettled_run_is_pending_never_delivered() -> None:
    audit = [row("e1", "2026-10-14T12:45:00+00:00", "queued", "user is mid-exchange on the target thread")]
    run = kinds(audit)["e1"]
    assert run.kind == "pending" and run.held_because == "mid-conversation"


def test_an_unknown_outcome_is_cant_tell() -> None:
    assert kinds([row("e1", "2026-10-14T12:45:00+00:00", "teleported")])["e1"].kind == "cant-tell"


def test_a_record_from_before_batch_ids_says_so() -> None:
    run = kinds([row("e1", "2026-10-14T12:45:00+00:00", "delivered", batch_key=False)])["e1"]
    assert run.kind == "delivered" and run.batch_not_recorded is True


def test_runs_are_newest_first_across_offsets_and_only_this_rules() -> None:
    audit = [
        row("2026-10-19T08:45:00-04:00", "2026-10-19T12:46:00+00:00", "delivered"),
        row("2026-10-20T08:45:00-04:00", "2026-10-20T12:46:00+00:00", "delivered"),
        row("x", "2026-10-21T12:46:00+00:00", "delivered", rule="other"),
    ]
    assert [r.event_id for r in describe_runs(audit, "brief").runs] == ["2026-10-20T08:45:00-04:00", "2026-10-19T08:45:00-04:00"]


def cron(schedule="45 8 * * 1-5", tz="America/New_York", enabled=True):
    return Rule(id="brief", type=TriggerType.CRON, match={"schedule": schedule, "timezone": tz}, prompt="p", destination=Destination.AUTO, enabled=enabled)


NOW = datetime(2026, 10, 20, 14, 0, tzinfo=UTC)  # Tuesday 10:00 in New York


def test_next_run_is_the_schedulers_instant_in_the_rules_zone() -> None:
    out = next_run(cron(), now=NOW, engine_enabled=True)
    assert out == {"next_run": "scheduled", "next_run_at": "2026-10-21T08:45:00-04:00", "deliver_at": "2026-10-21T08:45:00-04:00"}


def test_next_run_after_friday_skips_the_weekend() -> None:
    friday_noon = datetime(2026, 10, 23, 16, 0, tzinfo=UTC)
    assert next_run(cron(), now=friday_noon, engine_enabled=True)["next_run_at"] == "2026-10-26T08:45:00-04:00"


@pytest.mark.parametrize(
    "rule,engine,expect",
    [
        (cron(enabled=False), True, "off"),
        (cron(), False, "engine-off"),
        (Rule(id="w", type=TriggerType.WATCHER, match={"event": "idle"}, prompt="p"), True, "on-event"),
        (cron(schedule="not a cron"), True, "cant-tell"),
    ],
)
def test_next_run_never_guesses(rule, engine, expect) -> None:
    out = next_run(rule, now=NOW, engine_enabled=engine)
    assert out["next_run"] == expect and "next_run_at" not in out


def test_the_rules_view_carries_name_quiet_hours_and_next_run() -> None:
    cfg = parse(
        {
            "quiet_hours": {"start": "22:00", "end": "07:00", "timezone": "America/New_York"},
            "rules": [{"id": "brief", "name": "Morning brief", "type": "cron", "match": {"schedule": "45 8 * * 1-5", "timezone": "America/New_York"}, "prompt": "p"}],
        }
    )
    view = describe_rules(rules=list(cfg.rules), evaluated={}, audit=[], engine_enabled=True, quiet_hours=cfg.quiet_hours, now=NOW)
    assert view.rules[0].name == "Morning brief" and view.rules[0].next_run_at == "2026-10-21T08:45:00-04:00"
    assert view.quiet_hours is not None and (view.quiet_hours.start, view.quiet_hours.end) == ("22:00", "07:00")


def test_a_name_that_is_not_short_text_is_refused() -> None:
    with pytest.raises(ConfigError, match="name"):
        parse({"rules": [{"id": "x", "name": "n" * 81, "type": "watcher", "match": {"event": "idle"}, "prompt": "p"}]})


def _quiet(start="22:00", end="07:00", enabled=True):
    from app.trigger_engine.config import QuietHours

    return QuietHours(start=start, end=end, timezone="America/New_York", enabled=enabled)


def test_a_run_due_inside_quiet_hours_is_delivered_when_they_end() -> None:
    early = cron(schedule="30 5 * * 1-5")  # 5:30 New York, inside 22:00-07:00
    out = next_run(early, now=NOW, engine_enabled=True, quiet_hours=_quiet())
    assert out["next_run_at"] == "2026-10-21T05:30:00-04:00"
    assert out["held_for_quiet_hours"] is True and out["deliver_at"] == "2026-10-21T07:00:00-04:00"


def test_an_urgent_run_or_one_outside_quiet_hours_is_delivered_when_due() -> None:
    urgent = Rule(id="u", type=TriggerType.CRON, match={"schedule": "30 5 * * 1-5", "timezone": "America/New_York"}, prompt="p", urgent=True)
    for rule, quiet in ((urgent, _quiet()), (cron(), _quiet()), (cron(schedule="30 5 * * 1-5"), _quiet(enabled=False))):
        out = next_run(rule, now=NOW, engine_enabled=True, quiet_hours=quiet)
        assert out["deliver_at"] == out["next_run_at"] and "held_for_quiet_hours" not in out


def test_a_rule_without_a_zone_fires_in_utc_and_is_shown_in_the_users_zone() -> None:
    cfg = parse({"rules": [{"id": "z", "type": "cron", "match": {"schedule": "0 9 * * *"}, "prompt": "p"}]})
    view = describe_rules(rules=list(cfg.rules), evaluated={}, audit=[], engine_enabled=True, quiet_hours=cfg.quiet_hours, now=NOW)
    assert view.rules[0].next_run_at == "2026-10-21T09:00:00+00:00" and view.rules[0].timezone == "America/New_York"
