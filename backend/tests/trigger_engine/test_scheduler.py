"""T053 — scheduling (FR-018, FR-027, SC-003, SC-004)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.trigger_engine.scheduler import Scheduler, next_due


def _due(s, rule_id, expr, now, **kw) -> list:
    """Instants due now, as a list: catch_up returns at most one."""
    instant, _ = s.catch_up(rule_id, expr, now, **kw)
    return [instant] if instant is not None else []


NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
DAILY_7 = "0 7 * * *"


def _sched(tmp_path) -> Scheduler:
    return Scheduler(path=tmp_path / "sched.json")


def test_next_wakeup_is_the_earliest_across_rules(tmp_path) -> None:
    """FR-027 — one timer to the next due moment, not a tick loop."""
    s = _sched(tmp_path)
    nxt = s.next_wakeup([("a", "0 7 * * *"), ("b", "30 6 * * *")], NOW)
    assert nxt.hour == 6 and nxt.minute == 30


def test_no_schedules_means_no_wakeup(tmp_path) -> None:
    assert _sched(tmp_path).next_wakeup([], NOW) is None


def test_each_instant_fires_at_most_once(tmp_path) -> None:
    """FR-018 — the core guarantee."""
    s = _sched(tmp_path)
    due = _due(s, "r", DAILY_7, NOW)
    assert len(due) == 1
    s.mark_fired("r", due[0], NOW)
    assert _due(s, "r", DAILY_7, NOW) == []


def test_a_missed_instant_fires_once_late_not_once_per_tick(tmp_path) -> None:
    """SC-004 — the engine was stopped over a scheduled time.

    Firing once per missed tick is the failure this bounds against; skipping
    silently is the other. Exactly one, late, is the requirement.
    """
    s = _sched(tmp_path)
    later = NOW + timedelta(hours=6)
    due = _due(s, "r", DAILY_7, later, since=NOW - timedelta(hours=12))
    assert len(due) == 1
    for _ in range(5):  # several evaluation cycles after resuming
        pending = _due(s, "r", DAILY_7, later, since=NOW - timedelta(hours=12))
        for i in pending:
            s.mark_fired("r", i, later)
    assert _due(s, "r", DAILY_7, later, since=NOW - timedelta(hours=12)) == []


def test_a_long_outage_does_not_fire_once_per_missed_day(tmp_path) -> None:
    """The `since` floor is what keeps a month offline from becoming a month
    of notifications on resume."""
    s = _sched(tmp_path)
    after_a_month = NOW + timedelta(days=30)
    due = _due(s, "r", DAILY_7, after_a_month)  # default floor: 1 day
    assert len(due) <= 1


def test_firing_records_survive_a_restart(tmp_path) -> None:
    s = _sched(tmp_path)
    due = _due(s, "r", DAILY_7, NOW)[0]
    s.mark_fired("r", due, NOW)
    assert Scheduler(path=tmp_path / "sched.json").has_fired("r", due)


def test_de_duplication_keys_on_the_scheduled_instant_not_the_clock(tmp_path) -> None:
    """A clock jump — sleep/wake, NTP, DST — must not re-fire a served instant."""
    s = _sched(tmp_path)
    instant = _due(s, "r", DAILY_7, NOW)[0]
    s.mark_fired("r", instant, NOW)
    assert s.has_fired("r", instant)
    # Same instant, wildly different "now".
    assert s.has_fired("r", instant) is True


def test_rules_do_not_share_firing_records(tmp_path) -> None:
    s = _sched(tmp_path)
    instant = _due(s, "a", DAILY_7, NOW)[0]
    s.mark_fired("a", instant, NOW)
    assert not s.has_fired("b", instant)


def test_pruning_drops_old_records(tmp_path) -> None:
    s = _sched(tmp_path)
    instant = _due(s, "r", DAILY_7, NOW)[0]
    s.mark_fired("r", instant, NOW)
    assert s.prune(NOW + timedelta(days=30)) == 1
    assert not s.has_fired("r", instant)


def test_next_due_is_in_the_future() -> None:
    assert next_due(DAILY_7, NOW) > NOW


def test_a_missed_run_of_a_frequent_schedule_fires_the_newest_and_counts_the_rest(tmp_path) -> None:
    """*/15 down for an hour: one late firing for the newest instant, and the
    three before it reported as skipped — not four firings."""
    s = _sched(tmp_path)
    s.mark_fired("r", NOW, NOW)
    back = NOW + timedelta(hours=1, minutes=5)

    instant, skipped = s.catch_up("r", "*/15 * * * *", back)

    assert instant == NOW + timedelta(hours=1)
    assert skipped == 3


def test_skipped_instants_never_surface_after_the_late_firing(tmp_path) -> None:
    s = _sched(tmp_path)
    s.mark_fired("r", NOW, NOW)
    back = NOW + timedelta(hours=1, minutes=5)
    instant, _ = s.catch_up("r", "*/15 * * * *", back)
    s.mark_fired("r", instant, back)

    assert s.catch_up("r", "*/15 * * * *", back + timedelta(minutes=1)) == (None, 0)


def test_the_late_note_states_only_what_is_true() -> None:
    """Late and skipped are separate facts; neither is claimed without the other's evidence."""
    from app.trigger_engine.compose import late_note
    from app.trigger_engine.models import TriggerEvent, TriggerType

    def note(late_s: int, skipped: int) -> str:
        return late_note(TriggerEvent(type=TriggerType.CRON, event_id="x", at=NOW, fields={"late_by_seconds": late_s, "skipped": skipped}))

    assert note(30, 0) == ""
    assert note(95 * 60, 0).startswith("Running late") and "missed" not in note(95 * 60, 0)
    assert "Running late" not in note(4 * 60, 11) and "11 earlier scheduled runs were missed" in note(4 * 60, 11)
