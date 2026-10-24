"""An agent's schedule and recent runs, from the 002 trigger engine (Feature 006, Phase 3).

Read only, and pure: the router hands in the rules, the engine's quiet hours
and its audit log, read from the same files the engine writes.

WHICH RULES ARE AN AGENT'S. Exactly those whose `agent` names it (Feature
006-F: the firing runs AS that agent); a rule naming none is the lead agent's.
A name inside `match` is not read: the engine does not run a rule as it, so
the view must not claim it does.

NEXT RUN, the way the engine computes it: `scheduler.next_due` in the rule's own
zone, or the engine clock's (UTC) when the rule names none. The instant is the
same whatever zone a person reads it in; the panel shows it in theirs. A run
that lands in quiet hours is held until they end, unless the rule is urgent.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from app.gateway.triggers_view import FiringView, describe_firings

LEAD_AGENT = "lead_agent"


class AgentSchedule(BaseModel):
    rule_id: str
    schedule: str = Field(..., description="The cron expression, verbatim")
    timezone: str = Field(..., description="The zone the engine evaluates it in")
    timezone_named: bool = Field(..., description="False when the rule names no zone and the engine's default zone (scheduler.DEFAULT_TIMEZONE) is used")
    enabled: bool
    next_run: str | None = Field(..., description="ISO instant; None when disabled or the expression cannot be evaluated")
    held_until: str | None = Field(None, description="When the next run falls in quiet hours: when it is released")
    error: str | None = None
    name: str = Field("", description="The rule's display name")
    prompt: str = Field("", description="What the firing asks the agent")
    telegram: bool = Field(True, description="Its result is sent to Telegram (destination auto or remote)")
    show_on_home: bool = Field(True, description="Home lists its upcoming runs and results")


class AgentRunsView(BaseModel):
    agent: str
    engine_enabled: bool
    #: "none-name-this-agent": no rule runs this agent (see the module docstring).
    not_set_up_reason: str | None = None
    rules_error: str | None = None
    schedules: list[AgentSchedule]
    recent: list[FiringView]
    #: The rule file's version, sent back with a schedule edit (409 when stale).
    rules_version: str | None = None
    #: False when the engine runs the shipped defaults, which are not edited.
    writable: bool = False


def rule_agent(rule) -> str:
    named = getattr(rule, "agent", None)
    return str(named).strip().lower() if named else LEAD_AGENT


def describe_agent_runs(*, agent: str, rules: list, quiet_hours, audit: list[dict], engine_enabled: bool, rules_error: str | None = None, now: datetime | None = None, limit: int = 5) -> AgentRunsView:
    from app.trigger_engine.models import TriggerType
    from app.trigger_engine.scheduler import DEFAULT_TIMEZONE, next_due

    now = now or datetime.now(UTC)
    mine = [r for r in rules if rule_agent(r) == agent]
    schedules: list[AgentSchedule] = []
    for rule in mine:
        if rule.type != TriggerType.CRON:
            continue
        expr = str((rule.match or {}).get("schedule") or "")
        zone = (rule.match or {}).get("timezone")
        from app.gateway.agent_schedules import sends_to_telegram

        item = AgentSchedule(
            rule_id=rule.id,
            schedule=expr,
            timezone=zone or DEFAULT_TIMEZONE,
            timezone_named=bool(zone),
            enabled=rule.enabled,
            next_run=None,
            name=getattr(rule, "name", "") or "",
            prompt=rule.prompt,
            telegram=sends_to_telegram(str(rule.destination)),
            show_on_home=getattr(rule, "show_on_home", True),
        )
        if rule.enabled:
            try:
                due = next_due(expr, now, zone)
                item.next_run = due.astimezone(UTC).isoformat()
                if quiet_hours is not None and not rule.urgent and quiet_hours.contains(due):
                    item.held_until = quiet_hours.next_end(quiet_hours._local(due)).astimezone(UTC).isoformat()
            except Exception as exc:  # noqa: BLE001 — an unreadable schedule is said, not hidden
                item.error = f"{type(exc).__name__}: {exc}"
        schedules.append(item)
    schedules.sort(key=lambda s: s.next_run or "~")

    ids = {r.id for r in mine}
    recent = [f for f in describe_firings([e for e in audit if e.get("rule_id") in ids]).firings][:limit]
    return AgentRunsView(
        agent=agent,
        engine_enabled=engine_enabled,
        not_set_up_reason=None if mine else "none-name-this-agent",
        rules_error=rules_error,
        schedules=schedules,
        recent=recent,
    )
