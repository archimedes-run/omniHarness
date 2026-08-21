"""T049 — the engine must not be able to take the gateway with it.

Feature 001 got this boundary free from process separation. Sharing the
gateway's process removes it, so these assert the isolation that replaces it
(FR-030..FR-033, SC-010, SC-017, SC-018).
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta

import pytest

from app.trigger_engine.engine import BACKOFF_AFTER, SupervisedEngine
from app.trigger_engine.models import Rule, TriggerType

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
pytestmark = pytest.mark.asyncio


def _rule(rid: str) -> Rule:
    return Rule(id=rid, type=TriggerType.WATCHER, match={"event": "waiting-on-user"}, prompt="p")


async def test_a_crashing_rule_does_not_escape() -> None:
    """FR-030 — evaluate_one NEVER raises. An exception escaping here would
    reach whatever drives the loop, which in this process is the assistant."""

    async def boom(rule, now):
        raise RuntimeError("rule exploded")

    eng = SupervisedEngine(evaluate=boom)
    assert await eng.evaluate_one(_rule("bad"), NOW) is False
    assert "rule exploded" in eng.health_for("bad").last_error


async def test_a_crashing_rule_does_not_stop_the_others() -> None:
    """SC-010, FR-025."""
    ran: list[str] = []

    async def maybe(rule, now):
        if rule.id == "bad":
            raise RuntimeError("boom")
        ran.append(rule.id)

    eng = SupervisedEngine(evaluate=maybe)
    results = await eng.evaluate_all([_rule("a"), _rule("bad"), _rule("c")], NOW)
    assert sorted(ran) == ["a", "c"]
    assert results == {"a": True, "bad": False, "c": True}


async def test_a_hanging_rule_is_bounded_and_reported() -> None:
    """FR-032, SC-018 — a rule that never returns must not hold anything."""

    async def hang(rule, now):
        await asyncio.sleep(3600)

    eng = SupervisedEngine(evaluate=hang, rule_timeout=timedelta(milliseconds=50))
    started = time.perf_counter()
    assert await eng.evaluate_one(_rule("slow"), NOW) is False
    assert time.perf_counter() - started < 2.0, "the hang was not bounded"
    assert "exceeded" in eng.health_for("slow").last_error


async def test_a_hanging_rule_does_not_delay_the_others() -> None:
    """FR-031 — the property that keeps ordinary requests responsive."""

    async def mixed(rule, now):
        if rule.id == "slow":
            await asyncio.sleep(3600)

    eng = SupervisedEngine(evaluate=mixed, rule_timeout=timedelta(milliseconds=50))
    started = time.perf_counter()
    results = await eng.evaluate_all([_rule("slow"), _rule("fast")], NOW)
    elapsed = time.perf_counter() - started
    assert results["fast"] is True
    assert elapsed < 2.0, f"the fast rule waited {elapsed:.2f}s behind the hanging one"


async def test_repeated_failure_backs_off_rather_than_retrying_forever() -> None:
    """FR-026 — reported and slowed, never silently retried at full rate."""

    async def boom(rule, now):
        raise RuntimeError("still broken")

    eng = SupervisedEngine(evaluate=boom)
    r = _rule("flaky")
    for _ in range(BACKOFF_AFTER):
        await eng.evaluate_one(r, NOW)
    h = eng.health_for("flaky")
    assert h.consecutive_failures >= BACKOFF_AFTER
    assert h.is_muted(NOW), "a repeatedly failing rule was not backed off"
    assert not h.is_muted(NOW + timedelta(hours=2)), "backoff never expires"


async def test_recovery_clears_the_failure_record() -> None:
    state = {"fail": True}

    async def flaky(rule, now):
        if state["fail"]:
            raise RuntimeError("x")

    eng = SupervisedEngine(evaluate=flaky)
    await eng.evaluate_one(_rule("r"), NOW)
    assert eng.health_for("r").consecutive_failures == 1
    state["fail"] = False
    await eng.evaluate_one(_rule("r"), NOW)
    assert eng.health_for("r").consecutive_failures == 0


async def test_cancellation_is_not_treated_as_a_rule_failure() -> None:
    """Shutdown must not mark every rule broken on the way out."""

    async def cancelled(rule, now):
        raise asyncio.CancelledError

    eng = SupervisedEngine(evaluate=cancelled)
    with pytest.raises(asyncio.CancelledError):
        await eng.evaluate_one(_rule("r"), NOW)
    assert eng.health_for("r").consecutive_failures == 0


async def test_disabled_rules_are_not_evaluated() -> None:
    ran: list[str] = []

    async def note(rule, now):
        ran.append(rule.id)

    eng = SupervisedEngine(evaluate=note)
    off = Rule(id="off", type=TriggerType.WATCHER, match={"event": "x"}, prompt="p", enabled=False)
    await eng.evaluate_all([_rule("on"), off], NOW)
    assert ran == ["on"]
