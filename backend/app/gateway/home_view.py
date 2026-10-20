"""What Home shows that no other surface already serves (Feature 006, Main board).

Two pure views. Each reads nothing itself; the router hands it what it read.

  * upcoming: the next scheduled run of each enabled cron automation, computed
    with the trigger engine's own `next_due` (the rule's cron in the rule's
    time zone, DST handled by the zone), soonest first.
  * moved today: what actually happened since the start of the user's day:
    changes the Project Ledger recorded (who made each one, in words) and
    automation messages the engine recorded as delivered. Nothing is inferred
    or invented; a source that could not be read is said to be unreadable.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel

from app.gateway.inbox_view import describe_alerts
from app.trigger_engine.models import Rule, TriggerType
from app.trigger_engine.scheduler import next_due

#: How many upcoming runs Home lists.
UPCOMING_LIMIT = 5
#: How many of today's events Home is sent.
MOVED_LIMIT = 20


def rule_title(rule_id: str) -> str:
    """'morning-briefing' -> 'Morning briefing'. Rules have an id, not a name."""
    words = rule_id.replace("_", "-").split("-")
    text = " ".join(w for w in words if w)
    return text[:1].upper() + text[1:] if text else rule_id


class UpcomingRun(BaseModel):
    rule_id: str
    title: str
    #: The rule's prompt, shortened, so the row can say what it will do.
    prompt: str
    at: str
    schedule: str
    timezone: str | None


class UpcomingView(BaseModel):
    #: False: the trigger engine is off, so nothing is scheduled to run.
    engine_enabled: bool
    #: Set when the rule file could not be read: the list may be missing runs.
    rules_error: str | None = None
    runs: list[UpcomingRun]
    #: Calendar events need a calendar source; none is set up in the app.
    calendar: Literal["not-set-up"] = "not-set-up"


def describe_upcoming(rules: list[Rule], *, now: datetime, engine_enabled: bool, rules_error: str | None, limit: int = UPCOMING_LIMIT) -> UpcomingView:
    runs: list[tuple[datetime, UpcomingRun]] = []
    for rule in rules:
        if not rule.enabled or rule.type is not TriggerType.CRON:
            continue
        schedule = str(rule.match.get("schedule", ""))
        tz = rule.match.get("timezone") or None
        try:
            at = next_due(schedule, now, tz)
        except Exception:  # noqa: BLE001 — a rule the parser let through but croniter cannot run is skipped, not guessed
            continue
        prompt = " ".join(rule.prompt.split())
        runs.append((at, UpcomingRun(rule_id=rule.id, title=rule_title(rule.id), prompt=prompt[:140] + ("…" if len(prompt) > 140 else ""), at=at.isoformat(), schedule=schedule, timezone=tz)))
    runs.sort(key=lambda pair: pair[0])
    return UpcomingView(engine_enabled=engine_enabled, rules_error=rules_error, runs=[r for _, r in runs[:limit]])


SourceState = Literal["ok", "unavailable", "off"]


class MovedItem(BaseModel):
    at: str
    source: Literal["ledger", "automation"]
    text: str
    #: Who made the change, in words ("you", "the assistant, confirmed by you").
    by: str | None = None
    #: Where to look: a project or a conversation.
    project_id: str | None = None
    thread_id: str | None = None


class MovedView(BaseModel):
    items: list[MovedItem]
    #: Per source: read ("ok"), could not be read ("unavailable"), or switched
    #: off ("off"). An unreadable source means the list may be missing events.
    sources: dict[str, SourceState]


_TASK_STATUS = {"done": "Task done", "doing": "Task started", "blocked": "Task blocked", "dropped": "Task dropped", "todo": "Task reopened"}
_BY = {"user": "you", "assistant_confirmed": "the assistant, confirmed by you"}


def _short(text: str, n: int = 120) -> str:
    text = " ".join(str(text).split())
    return text[:n] + ("…" if len(text) > n else "")


def describe_change(change: dict, project_names: dict[str, str]) -> MovedItem | None:
    """One ledger change in words, or None for a change Home does not list."""
    before, after = change.get("before"), change.get("after")
    row = after or before or {}
    entity = change.get("entity")
    project_id = row.get("project_id") or (row.get("id") if entity == "project" else None) or (row.get("from_id") if entity == "link" and row.get("from_kind") == "project" else None)
    project = project_names.get(project_id or "", "a project")
    if entity == "project":
        name = row.get("name", "a project")
        if before is None:
            text = f"Project “{name}” created"
        elif after and before.get("status") != after.get("status"):
            text = f"Project “{name}” marked {after.get('status')}"
        else:
            text = f"Project “{name}” updated"
    elif entity == "task":
        title = _short(row.get("title", "a task"))
        if before is None:
            text = f"Task added to {project}: {title}"
        elif after and before.get("status") != after.get("status"):
            text = f"{_TASK_STATUS.get(after.get('status'), 'Task updated')} in {project}: {title}"
        else:
            text = f"Task updated in {project}: {title}"
    elif entity == "goal":
        title = _short(row.get("title", "a goal"))
        text = f"Goal set for {project}: {title}" if before is None else f"Goal updated in {project}: {title}"
    elif entity == "note":
        text = f"Decision recorded in {project}: {_short(row.get('decided', ''))}"
    elif entity == "link":
        kind = "Chat" if row.get("to_kind") == "thread" else "Link"
        text = f"{kind} linked to {project}" if before is None else f"{kind} unlinked from {project}"
    else:
        return None
    return MovedItem(at=str(change.get("at", "")), source="ledger", text=text, by=_BY.get(change.get("actor", ""), None), project_id=project_id)


def _when(at: str) -> datetime:
    try:
        when = datetime.fromisoformat(at.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def describe_moved(*, changes: list[dict] | None, project_names: dict[str, str], audit: list[dict] | None, since: datetime, now: datetime, automations: SourceState, limit: int = MOVED_LIMIT) -> MovedView:
    """`changes` / `audit` None means that source could not be read."""
    items: list[MovedItem] = []
    for change in changes or []:
        item = describe_change(change, project_names)
        if item is not None:
            items.append(item)
    if audit is not None:
        for alert in describe_alerts(audit, now=now).alerts:
            if alert.state != "delivered":
                continue
            if _when(alert.at) >= since:
                items.append(MovedItem(at=alert.at, source="automation", text=f"{rule_title(alert.rule_id)} delivered", thread_id=alert.thread_id))
    items.sort(key=lambda i: _when(i.at), reverse=True)
    return MovedView(items=items[:limit], sources={"ledger": "unavailable" if changes is None else "ok", "automations": automations if audit is not None or automations == "off" else "unavailable"})
