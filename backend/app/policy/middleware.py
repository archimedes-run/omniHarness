"""The policy layer, at the single tool-dispatch chokepoint (FR-001, FR-002).

An AgentMiddleware occupying `wrap_tool_call`. Four of five agent-construction
sites reach the shared middleware base, and the fifth is closed rather than
accommodated (FR-003) — a gate covering only the convergent four would have its
scope boundary exactly where the bypass lives.

Refusal is expressed by NOT calling the handler and returning a result in its
place. That is what makes this a gate rather than a notification.

ARTICLE I, DELIBERATELY. Unlike Features 001 and 002 this component runs
in-process in the dispatch path rather than behind the gateway API. An
out-of-process check would have to decide what happens when it is unreachable,
and every answer is either "the gateway stops working when a sidecar is down" —
worse than the risk — or "proceed unchecked", which is not a gate. The coupling
IS the guarantee, and it is recorded in plan.md's Complexity Tracking rather
than hidden.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from langchain.agents.middleware import AgentMiddleware

from .classify import classify
from .config import ConfigLoader
from .disclose import DisclosureLedger
from .models import Outcome, PendingAction, Tier, default_expiry
from .pending import PendingStore, targets_still_match

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class PolicyMiddleware(AgentMiddleware):
    """Classify, then act according to the tier.

    Tier 1  execute silently
    Tier 2  execute, and guarantee the reply discloses it
    Tier 3  do not execute; state the plan and wait
    """

    loader: ConfigLoader
    pending: PendingStore
    ledger: DisclosureLedger
    #: Resolves the specific items a call will affect, so a plan can name them
    #: rather than describing a category (FR-021, FR-029). Injected because
    #: target resolution is worker-specific.
    resolve_targets: Any = None
    audit: Any = None
    actor: str = "default"
    now: Any = _now

    def __post_init__(self) -> None:
        super().__init__()

    # -- the chokepoint ----------------------------------------------------

    def wrap_tool_call(self, request, handler):
        decision = self._classify(request)

        if decision.tier is Tier.TIER_1:
            return handler(request)

        if decision.tier is Tier.TIER_2:
            result = handler(request)
            self.ledger.record(
                tool_name=decision.tool_name,
                arguments=self._arguments(request),
                result=result,
            )
            return result

        return self._require_confirmation(request, decision)

    async def awrap_tool_call(self, request, handler):
        decision = self._classify(request)

        if decision.tier is Tier.TIER_1:
            return await handler(request)

        if decision.tier is Tier.TIER_2:
            result = await handler(request)
            self.ledger.record(tool_name=decision.tool_name, arguments=self._arguments(request), result=result)
            return result

        return self._require_confirmation(request, decision)

    # -- internals ---------------------------------------------------------

    def _classify(self, request):
        return classify(self._tool_name(request), self._arguments(request), self.loader.load())

    @staticmethod
    def _tool_name(request) -> str:
        call = getattr(request, "tool_call", None) or {}
        return call.get("name") or getattr(getattr(request, "tool", None), "name", "") or ""

    @staticmethod
    def _arguments(request) -> dict:
        call = getattr(request, "tool_call", None) or {}
        return call.get("args") or {}

    def _require_confirmation(self, request, decision):
        """Tier 3: state the plan, record it durably, and do not execute."""
        tool_name = decision.tool_name
        arguments = self._arguments(request)
        targets = list(self.resolve_targets(tool_name, arguments)) if self.resolve_targets else [f"{tool_name}({arguments})"]
        ruleset = self.loader.load()
        now = self.now()

        action = PendingAction(
            plan_text=self._plan_text(tool_name, targets),
            tool_name=tool_name,
            arguments=arguments,
            targets=targets,
            tier_at_statement=decision.tier,
            expires_at=default_expiry(now, ruleset.expires_after_seconds),
            thread_id=self._thread_id(request),
            requester=self._requester(request),
        )
        self.pending.save(action)
        logger.info("policy: %s requires confirmation (%s)", tool_name, action.id)
        return action.plan_text

    @staticmethod
    def _plan_text(tool_name: str, targets: list[str]) -> str:
        """FR-021: name the SPECIFIC items, not the category.

        "Delete some meetings" cannot be confirmed meaningfully — the user would
        be authorising a description, and confirming a description authorises
        whatever it later turns out to mean.
        """
        lines = [f"Before I do this, please confirm. I intend to use **{tool_name}** on exactly these {len(targets)} item(s):", ""]
        lines += [f"  - {target}" for target in targets]
        return "\n".join(lines)

    @staticmethod
    def _thread_id(request) -> str | None:
        context = getattr(getattr(request, "runtime", None), "context", None) or {}
        return context.get("thread_id")

    @staticmethod
    def _requester(request) -> str:
        context = getattr(getattr(request, "runtime", None), "context", None) or {}
        return context.get("agent_name") or "lead_agent"

    # -- execution after confirmation --------------------------------------

    def execute_confirmed(self, action: PendingAction, run_tool, current_targets: list[str] | None = None) -> Any:
        """Run a confirmed action, re-checking its targets first (FR-029).

        The claim is taken by the caller; this is what happens after it wins.
        """
        if current_targets is not None and not targets_still_match(action, current_targets):
            self.pending.resolve(
                action,
                Outcome.TARGETS_DRIFTED,
                f"the {len(action.targets)} item(s) confirmed are no longer the {len(current_targets)} present",
            )
            return None

        result = run_tool(action.tool_name, action.arguments)
        self.pending.resolve(action, Outcome.EXECUTED)
        if self.audit is not None:
            self.audit.record_tier3(action=action, actor=self.actor, now=self.now())
        return result
