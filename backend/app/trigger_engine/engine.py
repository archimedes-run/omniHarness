"""The evaluation loop, supervised (Gate 2; FR-025, FR-026, FR-030..FR-033).

Feature 001 got a crash boundary for free: the watcher is a separate process, so
its failure could not reach the assistant. This engine shares the gateway's
process, which removes that boundary. A rule that raises or blocks the shared
event loop now takes down the whole assistant unless the isolation is built
deliberately — so it is, here, rather than assumed.

Three properties, each with a test that breaks without it:

  * every rule evaluation is isolated behind an exception barrier (FR-030)
  * no rule work runs on a request-handling path (FR-031)
  * a rule that hangs is bounded, cancelled and reported (FR-032)
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .models import Rule

logger = logging.getLogger(__name__)

DEFAULT_RULE_TIMEOUT = timedelta(seconds=30)
#: After this many consecutive failures a rule is backed off rather than
#: retried at full rate (FR-026).
BACKOFF_AFTER = 3
MAX_BACKOFF = timedelta(minutes=30)


@dataclass
class RuleHealth:
    consecutive_failures: int = 0
    last_error: str = ""
    muted_until: datetime | None = None

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.last_error = ""
        self.muted_until = None

    def record_failure(self, exc: BaseException, now: datetime) -> None:
        self.consecutive_failures += 1
        self.last_error = f"{type(exc).__name__}: {exc}"
        if self.consecutive_failures >= BACKOFF_AFTER:
            # Exponential, capped. Never silent: the caller logs, and the health
            # record is inspectable.
            delay = min(MAX_BACKOFF, timedelta(seconds=60 * 2 ** (self.consecutive_failures - BACKOFF_AFTER)))
            self.muted_until = now + delay

    def is_muted(self, now: datetime) -> bool:
        return self.muted_until is not None and now < self.muted_until


@dataclass
class SupervisedEngine:
    """Evaluates rules without being able to take the gateway with it."""

    evaluate: Callable[[Rule, datetime], Awaitable[None]]
    rule_timeout: timedelta = DEFAULT_RULE_TIMEOUT
    health: dict[str, RuleHealth] = field(default_factory=dict)

    def health_for(self, rule_id: str) -> RuleHealth:
        return self.health.setdefault(rule_id, RuleHealth())

    async def evaluate_one(self, rule: Rule, now: datetime) -> bool:
        """Evaluate one rule. Returns True on success.

        NEVER raises. That is the whole point: an exception escaping here would
        reach whatever is driving the loop, which in this process is shared with
        the assistant.
        """
        h = self.health_for(rule.id)
        if h.is_muted(now):
            return False
        try:
            await asyncio.wait_for(self.evaluate(rule, now), timeout=self.rule_timeout.total_seconds())
        except TimeoutError:
            h.record_failure(TimeoutError(f"exceeded {self.rule_timeout}"), now)
            logger.warning(
                "rule %s exceeded %s and was cancelled (failure %d)",
                rule.id,
                self.rule_timeout,
                h.consecutive_failures,
            )
            return False
        except asyncio.CancelledError:
            raise  # shutdown is not a rule failure
        except Exception as exc:  # noqa: BLE001 — the barrier is the point
            h.record_failure(exc, now)
            logger.exception("rule %s raised (failure %d)", rule.id, h.consecutive_failures)
            return False
        h.record_success()
        return True

    async def evaluate_all(self, rules: list[Rule], now: datetime) -> dict[str, bool]:
        """Evaluate every enabled rule. One rule's failure affects no other.

        Deliberately gathered rather than sequential: a slow rule must not delay
        the others any more than it delays itself.
        """
        active = [r for r in rules if r.enabled]
        results = await asyncio.gather(*(self.evaluate_one(r, now) for r in active), return_exceptions=True)
        out: dict[str, bool] = {}
        for rule, res in zip(active, results, strict=True):
            # gather with return_exceptions should never yield one, since
            # evaluate_one swallows. If it does, the barrier has a hole.
            if isinstance(res, BaseException):
                logger.error("BARRIER LEAK: rule %s escaped evaluate_one: %r", rule.id, res)
                self.health_for(rule.id).record_failure(res, now)
                out[rule.id] = False
            else:
                out[rule.id] = res
        return out
