"""Entities for the permission policy engine (data-model.md)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import IntEnum, StrEnum
from typing import Any

from .predicates import PREDICATES


class Tier(IntEnum):
    """One of three levels of consequence (Article II).

    Not a severity scale — a decision about what must happen before and after a
    call. An IntEnum because the ordering is load-bearing: FR-037 permits an
    exception to move a call UP this list and never down, and "up" needs to mean
    something.

    THERE IS NO `UNCLASSIFIED` MEMBER, deliberately. A tool matching no rule
    resolves to TIER_3 (FR-009), so absence produces a tier rather than a
    missing one and no code path has to handle "unknown". A fourth member would
    reintroduce exactly the state the requirement exists to eliminate.
    """

    TIER_1 = 1  # read — execute silently
    TIER_2 = 2  # reversible write — execute, then disclose
    TIER_3 = 3  # irreversible, outbound, or spawning — state, confirm, execute

    @property
    def label(self) -> str:
        return {Tier.TIER_1: "Tier 1", Tier.TIER_2: "Tier 2", Tier.TIER_3: "Tier 3"}[self]


class Outcome(StrEnum):
    """Why a pending action ended. Distinct values, because a reviewer reading
    back needs to know WHY nothing happened (FR-036, SC-020).

    Collapsing decline, expiry and an unrecognised reply into one "not executed"
    loses the fact an operator most wants.
    """

    EXECUTED = "executed"
    DECLINED = "declined"
    EXPIRED = "expired"
    UNRECOGNISED = "unrecognised"
    TARGETS_DRIFTED = "targets-drifted"
    SUPERSEDED = "superseded"
    #: Authorised, claimed, attempted — and the tool raised. Distinct from every
    #: other member because the user DID approve and the action DID NOT happen,
    #: which no other outcome says. Added when a real gateway run left an action
    #: claimed and unresolved after a tool error: recoverable only by expiry,
    #: and invisible until then.
    FAILED = "failed"


@dataclass(frozen=True)
class RuleException:
    """An argument-conditional override. May only RAISE (FR-037)."""

    tier: Tier
    when: dict[str, Any] = field(default_factory=dict)
    source_line: int | None = None

    #: argument key -> name of a SAFETY predicate from PREDICATES. The
    #: exception applies when the predicate is not satisfied.
    unless: dict[str, str] = field(default_factory=dict)

    def matches(self, arguments: dict[str, Any]) -> bool:
        args = arguments or {}
        for key, expected in self.when.items():
            actual = args.get(key)
            if isinstance(expected, list):
                if actual not in expected:
                    return False
            elif actual != expected:
                return False

        # `unless` names a SAFETY predicate per argument. The exception applies
        # — and therefore RAISES the tier — whenever safety cannot be
        # established. A missing argument counts as unestablished, so a rule
        # naming an argument this tool does not have raises rather than falls
        # through to the lower tier. That direction is deliberate: it makes a
        # wrong argument name in a rules file safe instead of silent.
        for key, predicate_name in self.unless.items():
            predicate = PREDICATES.get(predicate_name)
            if predicate is None:  # unknown names are rejected at load
                return True
            if key not in args:
                return True
            try:
                if not predicate(args[key]):
                    return True
            except Exception:  # noqa: BLE001 — a predicate that throws has not established safety
                return True

        # A `when` exception that survived every check APPLIES: its conditions
        # all held. An `unless` exception that survived established safety on
        # every argument it names, so it does NOT apply and the rule's own tier
        # stands. Returning True here for a pure-`unless` exception raised every
        # call, including the SELECT the rule exists to let through.
        return bool(self.when)


@dataclass(frozen=True)
class ClassificationRule:
    """A user-authored mapping from a tool-name pattern to a tier."""

    pattern: str
    tier: Tier
    exceptions: tuple[RuleException, ...] = ()
    source_file: str = ""
    source_line: int | None = None

    def describe(self) -> str:
        where = f" ({self.source_file}:{self.source_line})" if self.source_line else ""
        return f'pattern "{self.pattern}"{where}'


@dataclass(frozen=True)
class PolicyDecision:
    """The result of classifying one call.

    Produced by the SAME code for live dispatch and for inspection (FR-038) —
    an inspector with its own implementation answers a different question and
    diverges silently.
    """

    tool_name: str
    tier: Tier
    deciding_rule: ClassificationRule | None
    raised_by: RuleException | None = None

    def explain(self) -> str:
        if self.deciding_rule is None:
            return f"{self.tier.label}: no rule matches '{self.tool_name}' — unknown tools are Tier 3 (FR-009)"
        base = f"{self.tier.label}: {self.deciding_rule.describe()}"
        if self.raised_by is not None:
            line = f":{self.raised_by.source_line}" if self.raised_by.source_line else ""
            return f"{base} -> raised by exception when {self.raised_by.when}{line}"
        return base


@dataclass
class PendingAction:
    """A Tier 3 call stated to the user and awaiting an answer.

    Durable and worker-independent (FR-028): the worker that states a plan is
    unlikely to be the one that receives the reply.
    """

    plan_text: str
    tool_name: str
    arguments: dict[str, Any]
    #: RESOLVED, SPECIFIC items — never the criteria that selected them
    #: (FR-029). Re-resolving at execution time would let a confirmation act on
    #: a set the user never saw.
    targets: list[str]
    tier_at_statement: Tier
    expires_at: datetime
    thread_id: str | None = None
    requester: str = "lead_agent"
    delegation_chain: tuple[str, ...] = ()
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    claimed_by: str | None = None
    outcome: Outcome | None = None
    outcome_reason: str = ""

    def is_expired(self, now: datetime) -> bool:
        return now >= self.expires_at

    def resolve(self, outcome: Outcome, reason: str = "") -> PendingAction:
        if outcome is not Outcome.EXECUTED and not reason:
            raise ValueError(f"outcome {outcome} requires a reason — a pending action that vanished without one is indistinguishable from one that never existed")
        self.outcome = outcome
        self.outcome_reason = reason
        return self


def default_expiry(now: datetime, seconds: int) -> datetime:
    return now + timedelta(seconds=seconds)
