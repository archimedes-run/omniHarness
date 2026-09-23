"""T029/FR-020 — "evaluated and never fired" must not look like "never evaluated".

That is the shape the calendar lead-time bug hid in: alerts fired approximately
never, and no record distinguished a rule the engine was working through from
one it had never reached.

SC-009 is the assertion these build to.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.trigger_engine.engine import SupervisedEngine
from app.trigger_engine.evaluations import EvaluationLog
from app.trigger_engine.models import Rule, TriggerType

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)


def _rule(rule_id: str, *, enabled: bool = True) -> Rule:
    return Rule(id=rule_id, type=TriggerType.CRON, match={"cron": "* * * * *"}, prompt="p", enabled=enabled)


@pytest.fixture
def log(tmp_path):
    return EvaluationLog(path=tmp_path / "evaluations.json")


def test_a_rule_never_evaluated_reads_as_never(log):
    """POSITIVE CONTROL for the absence. If this returned a timestamp, every
    assertion below would pass while meaning nothing."""
    assert log.last_evaluated_at("never-touched") is None


def test_a_rule_that_is_evaluated_is_recorded(log):
    log.record("r1", NOW)
    assert log.last_evaluated_at("r1") == NOW


def test_evaluation_is_recorded_even_when_the_rule_does_not_fire(log):
    """THE WHOLE POINT. Firing is not the condition — being looked at is."""
    engine = SupervisedEngine(evaluate=lambda rule, now: asyncio.sleep(0), on_evaluated=log.record)
    asyncio.run(engine.evaluate_all([_rule("quiet")], NOW))

    assert log.last_evaluated_at("quiet") == NOW, "a rule was evaluated and the record does not say so"


def test_a_rule_that_raises_still_counts_as_evaluated(log):
    """We asked and it failed, which is a different fact from never asking."""

    async def explodes(rule, now):
        raise ValueError("boom")

    engine = SupervisedEngine(evaluate=explodes, on_evaluated=log.record)
    asyncio.run(engine.evaluate_all([_rule("broken")], NOW))

    assert log.last_evaluated_at("broken") == NOW


def test_a_muted_rule_is_not_recorded_as_evaluated(log):
    """Muted means skipped before anything ran. Recording it would claim the
    engine looked at something it deliberately did not."""
    engine = SupervisedEngine(evaluate=lambda rule, now: asyncio.sleep(0), on_evaluated=log.record)
    engine.health_for("muted").muted_until = NOW + timedelta(hours=1)

    asyncio.run(engine.evaluate_all([_rule("muted")], NOW))

    assert log.last_evaluated_at("muted") is None


def test_the_two_states_are_distinguishable_after_many_evaluations(log):
    """SC-009, stated as the interface will ask it."""
    engine = SupervisedEngine(evaluate=lambda rule, now: asyncio.sleep(0), on_evaluated=log.record)
    for i in range(50):
        asyncio.run(engine.evaluate_all([_rule("busy")], NOW + timedelta(minutes=i)))

    busy = log.last_evaluated_at("busy")
    never = log.last_evaluated_at("dormant")

    assert busy is not None and never is None
    assert busy != never, "a rule evaluated fifty times reads the same as one never evaluated"


def test_the_record_survives_a_restart(tmp_path):
    """In-memory would have made every running rule read as never-evaluated
    after a gateway restart — the exact false impression FR-020 removes."""
    path = tmp_path / "evaluations.json"
    EvaluationLog(path=path).record("r1", NOW)

    assert EvaluationLog(path=path).last_evaluated_at("r1") == NOW
