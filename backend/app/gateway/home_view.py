"""What Home shows that no other surface already serves (Feature 006, Main board).

Two pure views. Each reads nothing itself; the router hands it what it read.

  * upcoming: the next scheduled run of each enabled cron automation, computed
    with the trigger engine's own `next_due` exactly as the engine computes it
    (the rule's zone; a rule without one runs in UTC, as the engine runs it),
    soonest first, with when quiet hours hold its message; plus the calendar
    (home_sources.calendar_events).
  * moved today: what actually happened since the start of the user's day:
    changes the Project Ledger recorded (who made each one, in words),
    automation messages the engine recorded as delivered, and the outside
    sources' items (sessions, GitHub). Each says how it is known (observed /
    reported / inferred). Nothing is invented; a source that could not be read
    is said to be unreadable.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from app.gateway.display_safe import provider_link, safe_field
from app.gateway.home_sources import CalendarView, Known, SourceItem, SourceState
from app.gateway.inbox_view import describe_alerts
from app.trigger_engine.models import Rule, TriggerType
from app.trigger_engine.politeness.quiet_hours import QuietHours, should_suppress
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
    #: Set when the run falls in quiet hours and the rule is not urgent: the
    #: engine holds its message until the window ends, at this time.
    held_until: str | None = None


class UpcomingView(BaseModel):
    #: False: the trigger engine is off, so nothing is scheduled to run.
    engine_enabled: bool
    #: Set when the rule file could not be read: the list may be missing runs.
    rules_error: str | None = None
    runs: list[UpcomingRun]
    calendar: CalendarView = CalendarView(state="not-set-up")


def held_until(rule: Rule, at: datetime, quiet: QuietHours | None) -> datetime | None:
    """When quiet hours release a run at `at`, or None when it is not held.
    The engine's own rule (should_suppress); the window in its own zone."""
    if quiet is None or not should_suppress(rule.urgent, quiet, at)[0]:
        return None
    local = at.astimezone(ZoneInfo(quiet.timezone)) if quiet.timezone else at
    return quiet.next_end(local)


def describe_upcoming(rules: list[Rule], *, now: datetime, engine_enabled: bool, rules_error: str | None, quiet: QuietHours | None = None, limit: int = UPCOMING_LIMIT) -> UpcomingView:
    runs: list[tuple[datetime, UpcomingRun]] = []
    for rule in rules:
        if not rule.enabled or rule.type is not TriggerType.CRON or not getattr(rule, "show_on_home", True):
            continue
        schedule = str(rule.match.get("schedule", ""))
        tz = rule.match.get("timezone") or None
        try:
            at = next_due(schedule, now, tz)
        except Exception:  # noqa: BLE001 — a rule the parser let through but croniter cannot run is skipped, not guessed
            continue
        prompt = " ".join(rule.prompt.split())
        try:
            held = held_until(rule, at, quiet)
        except Exception:  # noqa: BLE001 — an unknown quiet-hours zone: say nothing rather than guess
            held = None
        runs.append((at, UpcomingRun(rule_id=rule.id, title=rule_title(rule.id), prompt=prompt[:140] + ("…" if len(prompt) > 140 else ""), at=at.isoformat(), schedule=schedule, timezone=tz, held_until=held.isoformat() if held else None)))
    runs.sort(key=lambda pair: pair[0])
    return UpcomingView(engine_enabled=engine_enabled, rules_error=rules_error, runs=[r for _, r in runs[:limit]])


class MovedItem(BaseModel):
    at: str
    source: Literal["ledger", "automation", "session", "github"]
    text: str
    #: Who made the change, in words ("you", "the assistant, confirmed by you").
    by: str | None = None
    #: Where to look: a project or a conversation.
    project_id: str | None = None
    thread_id: str | None = None
    #: How it is known: observed (recorded here or seen), reported (another
    #: system says so), inferred (from silence).
    known: Known = "observed"
    url: str | None = None


class MovedView(BaseModel):
    items: list[MovedItem]
    #: Per source: read ("ok"), could not be read ("unavailable"), or switched
    #: off ("off"). An unreadable source means the list may be missing events.
    sources: dict[str, SourceState]


#: An outside source's answer: its items (None when unread) and its state.
Outside = tuple[list[SourceItem] | None, SourceState]

_TASK_STATUS = {"done": "Task done", "doing": "Task started", "blocked": "Task blocked", "dropped": "Task dropped", "todo": "Task reopened"}
_BY = {"user": "you", "assistant_confirmed": "the assistant, confirmed by you", "assistant_disclosed": "the assistant, and it told you", "assistant_granted": "the assistant on its own, under a standing grant"}


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
    return MovedItem(at=str(change.get("at", "")), source="ledger", text=safe_field(text), by=_BY.get(change.get("actor", ""), None), project_id=project_id)


def _when(at: str) -> datetime:
    try:
        when = datetime.fromisoformat(at.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def describe_moved(
    *,
    changes: list[dict] | None,
    project_names: dict[str, str],
    audit: list[dict] | None,
    since: datetime,
    now: datetime,
    automations: SourceState,
    outside: dict[str, Outside] | None = None,
    hidden_rules: frozenset[str] = frozenset(),
) -> MovedView:
    """`changes` / `audit` None means that source could not be read.
    `outside`: per source name, its items (None when unread) and its state.
    `hidden_rules`: rules whose results are not shown on Home (show_on_home
    false, Feature 006-F)."""
    items: list[MovedItem] = []
    for change in changes or []:
        item = describe_change(change, project_names)
        if item is not None:
            items.append(item)
    if audit is not None:
        for alert in describe_alerts(audit, now=now).alerts:
            if alert.state != "delivered" or alert.rule_id in hidden_rules:
                continue
            if _when(alert.at) >= since:
                items.append(MovedItem(at=alert.at, source="automation", text=f"{rule_title(alert.rule_id)} delivered", thread_id=alert.thread_id))
    sources: dict[str, SourceState] = {"ledger": "unavailable" if changes is None else "ok", "automations": automations if audit is not None or automations == "off" else "unavailable"}
    for name, (found, state) in (outside or {}).items():
        sources[name] = state
        for it in found or []:
            if _when(it.at) >= since:
                # Live only if it is provably the provider's own link.
                items.append(MovedItem(at=it.at, source=it.source, text=safe_field(it.text), known=it.known, url=provider_link(it.source, it.url)))
    items.sort(key=lambda i: _when(i.at), reverse=True)
    return MovedView(items=items[:MOVED_LIMIT], sources=sources)
