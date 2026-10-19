"""What the triggers surface shows (Feature 004, US2): why a rule produced nothing.

Read at request time from the engine's own durable state — the rule file, the
evaluation log (FR-020) and the audit log — so every worker answers the same,
whichever one runs the engine.

Three rule conditions that used to look identical (FR-017, SC-009):
never evaluated · evaluated, never fired · fired.

"Not recorded" is not "never" (FR-022). A rule that has firings but no
evaluation record was evaluated before evaluation times were kept; an audit row
without a `batch_id` KEY was written before batches were. Both read as "not
recorded", never as a recorded absence.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Activity = Literal["never-evaluated", "evaluated-never-fired", "fired"]
Recorded = Literal["recorded", "never", "not-recorded"]


class RuleView(BaseModel):
    id: str
    type: str
    enabled: bool
    match: dict
    activity: Activity
    last_evaluated_at: str | None = None
    last_evaluated: Recorded
    last_fired_at: str | None = None
    last_outcome: str | None = None


class BatchMember(BaseModel):
    rule_id: str
    event_id: str


class FiringView(BaseModel):
    at: str
    rule_id: str
    event_type: str
    event_id: str
    outcome: str
    #: VERBATIM from the audit record (FR-019). Never summarised.
    reason: str
    #: alone | batched | not-recorded (FR-021, FR-022)
    batch: Literal["alone", "batched", "not-recorded"]
    batch_id: str | None = None
    #: The OTHER firings delivered in the same message, resolved here (T053).
    delivered_with: list[BatchMember] = []


class RulesView(BaseModel):
    engine_enabled: bool
    rules: list[RuleView]
    rules_error: str | None = None


class FiringsView(BaseModel):
    firings: list[FiringView]


def describe_rules(*, rules: list, evaluated: dict[str, str | None], audit: list[dict], engine_enabled: bool, rules_error: str | None = None) -> RulesView:
    """Pure. `evaluated` maps rule id -> last evaluated ISO time (absent: no record)."""
    out = []
    for rule in rules:
        mine = [e for e in audit if e.get("rule_id") == rule.id]
        last = max(mine, key=lambda e: e.get("at", "")) if mine else None
        stamp = evaluated.get(rule.id)
        if stamp:
            recorded: Recorded = "recorded"
        elif mine:
            recorded = "not-recorded"  # it fired, so it was evaluated: before FR-020 kept the time
        else:
            recorded = "never"
        if last is not None:
            activity: Activity = "fired"
        elif stamp:
            activity = "evaluated-never-fired"
        else:
            activity = "never-evaluated"
        out.append(
            RuleView(
                id=rule.id,
                type=str(rule.type),
                enabled=rule.enabled,
                match=dict(rule.match),
                activity=activity,
                last_evaluated_at=stamp,
                last_evaluated=recorded,
                last_fired_at=last.get("at") if last else None,
                last_outcome=last.get("outcome") if last else None,
            )
        )
    return RulesView(engine_enabled=engine_enabled, rules=out, rules_error=rules_error)


def describe_firings(audit: list[dict], *, limit: int = 200) -> FiringsView:
    """Pure. Newest first; each delivered firing names its batch-mates."""
    batches: dict[str, list[dict]] = {}
    for e in audit:
        if e.get("batch_id"):
            batches.setdefault(e["batch_id"], []).append(e)
    out = []
    for e in sorted(audit, key=lambda e: e.get("at", ""), reverse=True)[:limit]:
        if "batch_id" not in e:
            batch, mates = "not-recorded", []
        elif e["batch_id"] is None:
            batch, mates = "alone", []
        else:
            batch = "batched"
            mates = [BatchMember(rule_id=m["rule_id"], event_id=m["event_id"]) for m in batches[e["batch_id"]] if (m["rule_id"], m["event_id"]) != (e["rule_id"], e["event_id"])]
        out.append(
            FiringView(
                at=e.get("at", ""),
                rule_id=e.get("rule_id", ""),
                event_type=e.get("event_type", ""),
                event_id=e.get("event_id", ""),
                outcome=e.get("outcome", ""),
                reason=e.get("reason", ""),
                batch=batch,
                batch_id=e.get("batch_id"),
                delivered_with=mates,
            )
        )
    return FiringsView(firings=out)
