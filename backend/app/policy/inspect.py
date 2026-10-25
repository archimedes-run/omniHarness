"""What the policy inspector shows (Feature 004, US4). Pure reads.

The tier check calls `explain()`, which calls `classify()` — the function live
dispatch uses (FR-025). It runs nothing: it is given no tool, no runner and no
store, so there is nothing it could execute or record.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from .config import ConfigLoader, RuleSet
from .coverage import refusal_text
from .explain import explain
from .limits import ABSENT_CAPABILITIES, describe_absent, describe_tier
from .models import Tier


class ExceptionView(BaseModel):
    tier: int
    when: dict[str, Any]
    unless: dict[str, str]


class RuleView(BaseModel):
    pattern: str
    tier: int
    exceptions: list[ExceptionView]
    source_line: int | None = None


class CannotDo(BaseModel):
    capability: str
    wording: str


class RulesInForce(BaseModel):
    source_file: str
    rules: list[RuleView]
    #: The file could not be read and no earlier rules exist: every tool is Tier 3.
    unreadable: bool
    #: The last edit was REFUSED; the rules shown are the previous ones, still
    #: in force (FR-029), and `error` says why.
    kept_previous: bool
    error: str | None = None
    threshold_targets: int
    expires_after_seconds: int
    #: What the assistant cannot do at all, and what it says instead (FR-023).
    #: Absent, not forbidden: no rule could allow these.
    cannot_do: list[CannotDo] = []


class TierCheck(BaseModel):
    tool: str
    tier: int
    #: The rule that decided it (FR-026). None only when nothing matched.
    deciding_rule: str | None
    #: True when no rule matched and the tier is the unknown-tool default
    #: (FR-027): "defaults to Tier 3" and "classified Tier 3" read the same in a
    #: tier alone and mean different things.
    from_default: bool
    raised_by: ExceptionView | None = None
    #: What will happen, in the words the assistant uses (FR-023).
    in_plain_words: str = ""
    #: Set when the name is a capability the assistant does not have at all
    #: (FR-012): no tool exists, so the tier above describes nothing real.
    absent: str | None = None
    #: No rule names this tool, so it is refused: never offered, never run
    #: (007). The tier above is then not acted on.
    refused: bool = False


class Tier3Execution(BaseModel):
    at: str
    actor: str
    tool: str
    plan_as_stated: str
    targets: list[str]
    authorised_by: str | None
    outcome: str | None = None
    #: Set by the route when the plan or a target failed redaction and is not
    #: shown (FR-031, SC-015).
    withheld: bool = False


def rules_in_force(loader: ConfigLoader) -> RulesInForce:
    ruleset = loader.load(notify=False)  # a read surface writes nothing (FR-030)
    return RulesInForce(
        source_file=ruleset.source_file or str(loader.path),
        rules=[RuleView(pattern=r.pattern, tier=int(r.tier), source_line=r.source_line, exceptions=[ExceptionView(tier=int(e.tier), when=dict(e.when), unless=dict(e.unless)) for e in r.exceptions]) for r in ruleset.rules],
        unreadable=ruleset.unreadable,
        kept_previous=loader.kept_previous,
        error=loader.last_error or (ruleset.error or None),
        threshold_targets=ruleset.threshold_targets,
        expires_after_seconds=ruleset.expires_after_seconds,
        cannot_do=[CannotDo(capability=c, wording=w) for c, w in ABSENT_CAPABILITIES.items()],
    )


def tier_check(tool: str, arguments: dict[str, Any] | None, ruleset: RuleSet) -> TierCheck:
    decision = explain(tool, arguments, ruleset)
    raised = decision.raised_by
    return TierCheck(
        tool=tool,
        tier=int(decision.tier),
        deciding_rule=decision.deciding_rule.describe() if decision.deciding_rule else None,
        from_default=decision.deciding_rule is None,
        raised_by=ExceptionView(tier=int(raised.tier), when=dict(raised.when), unless=dict(raised.unless)) if raised else None,
        in_plain_words=refusal_text(tool) if decision.refused else describe_tier(Tier(decision.tier), tool),
        absent=describe_absent(tool),
        refused=decision.refused,
    )


#: Refused plans shown with the Tier 3 history, at most (they never take a
#: place of a real entry in its window: see recent_tier3).
REFUSED_SHOWN = 20


def recent_tier3(entries: list[dict], *, limit: int = 50) -> list[Tier3Execution]:
    newest = sorted(entries, key=lambda e: e.get("at", ""), reverse=True)
    # The window counts real entries only: refused plans (nothing proposed,
    # nothing run) are shown beside them, never instead of them.
    real = [e for e in newest if e.get("kind") != "refused-plan"][:limit]
    refused = [e for e in newest if e.get("kind") == "refused-plan"][:REFUSED_SHOWN]
    out = []
    for e in sorted(real + refused, key=lambda e: e.get("at", ""), reverse=True):
        out.append(
            Tier3Execution(
                at=e.get("at", ""),
                actor=e.get("actor", ""),
                tool=e.get("tool", ""),
                plan_as_stated=e.get("plan_as_stated", ""),
                targets=list(e.get("targets") or []),
                # A grant use (Feature 006) ran with nobody confirming: say which
                # standing grant authorised it, not "nobody".
                authorised_by=(f"{e.get('agent')}'s standing grant ({', '.join(e.get('classes') or [])})" if e.get("kind") == "grant-use" else e.get("authorised_by")),
                outcome=("executed" if e.get("kind") == "grant-use" else e.get("outcome")),
            )
        )
    return out
