"""T052, T053, T057 — the triggers surface's read logic (FR-017, FR-019, FR-021, FR-022)."""

from __future__ import annotations

from types import SimpleNamespace

from app.gateway.triggers_view import describe_firings, describe_rules


def _rule(rid):
    return SimpleNamespace(id=rid, type="cron", enabled=True, match={"schedule": "* * * * *"}, prompt="Brief me at {scheduled_at}.", destination="auto", urgent=False)


def test_three_rule_conditions_are_distinct() -> None:
    """FR-017, SC-009. Never evaluated; evaluated and never fired; fired."""
    view = describe_rules(
        rules=[_rule("new"), _rule("quiet"), _rule("busy")],
        evaluated={"quiet": "2026-10-19T10:00:00+00:00", "busy": "2026-10-19T10:00:00+00:00"},
        audit=[{"rule_id": "busy", "at": "2026-10-19T09:00:00+00:00", "outcome": "delivered", "batch_id": None}],
        engine_enabled=True,
    )
    activity = {r.id: r.activity for r in view.rules}
    assert activity == {"new": "never-evaluated", "quiet": "evaluated-never-fired", "busy": "fired"}


def test_a_firing_without_an_evaluation_record_reads_not_recorded_not_never() -> None:
    """FR-022: it fired, so it was evaluated — before evaluation times were kept."""
    view = describe_rules(rules=[_rule("old")], evaluated={}, audit=[{"rule_id": "old", "at": "2026-08-01T09:00:00+00:00", "outcome": "delivered"}], engine_enabled=True)
    assert view.rules[0].last_evaluated == "not-recorded"


def test_a_row_without_a_batch_key_reads_not_recorded_not_alone() -> None:
    """FR-022: absent and null are different facts, and the read keeps them apart."""
    view = describe_firings(
        [
            {"rule_id": "old", "event_id": "e1", "at": "2026-08-01T09:00:00", "outcome": "delivered", "reason": ""},
            {"rule_id": "new", "event_id": "e2", "at": "2026-10-19T09:00:00", "outcome": "delivered", "reason": "", "batch_id": None},
        ]
    )
    batch = {f.rule_id: f.batch for f in view.firings}
    assert batch == {"old": "not-recorded", "new": "alone"}


def test_reasons_pass_through_verbatim() -> None:
    """FR-019. A status word would lose exactly what an operator needs."""
    reason = "attempt 2 of 3: GatewayCallFailed: the agent run ended 'error': RuntimeError: model unavailable; retrying on the next cycle"
    [f] = describe_firings([{"rule_id": "r", "event_id": "e", "at": "t", "outcome": "failed", "reason": reason, "batch_id": None}]).firings
    assert f.reason == reason
