"""Home's reads from outside the gateway (Feature 006): READ-ONLY, each one
reporting whether it could be read.

  * Google Calendar: the next 7 days of events, through the user's existing
    Composio connection (GOOGLECALENDAR_EVENTS_LIST).
  * GitHub: pull requests merged today and open ones with failing checks,
    through the user's existing Composio connection (search only).
  * The session watcher: sessions that finished or stopped on the user today.

Every source answers with a state: "ok" (read), "not-set-up" (no connection,
nothing to read), or "unavailable" (connected and could not be read: can't
tell). A source never turns a failure into an empty list.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel

SourceState = Literal["ok", "unavailable", "off", "not-set-up"]
Known = Literal["observed", "reported", "inferred"]

#: Bounds one outside read, so Home never waits on a slow provider.
READ_TIMEOUT_S = 6.0
CALENDAR_DAYS = 7
CALENDAR_LIMIT = 8


class CalendarEvent(BaseModel):
    title: str
    #: ISO: a time with its offset, or a date for an all-day event.
    start: str
    all_day: bool = False


class CalendarView(BaseModel):
    state: Literal["ok", "not-set-up", "unavailable"]
    #: Why it is not set up or could not be read.
    detail: str | None = None
    events: list[CalendarEvent] = []


class SourceItem(BaseModel):
    """One thing that happened, from an outside source."""

    at: str
    source: Literal["session", "github"]
    text: str
    known: Known
    url: str | None = None


async def _connection(app_state: Any, user_id: str, toolkit: str) -> tuple[Any, str] | tuple[None, str]:
    """(client, connected_account_id), or (None, why) when there is none."""
    repo = getattr(app_state, "composio_connection_repo", None)
    if repo is None:
        return None, "connections need a database"
    rows = await repo.list_by_user(user_id=user_id)
    row = next((r for r in rows if str(r.get("toolkit", "")).upper() == toolkit and r.get("status") == "active" and r.get("composio_connection_id")), None)
    if row is None:
        return None, "not-set-up"
    client = getattr(app_state, "composio_client", None)
    if client is None:
        return None, "the connection is there but the gateway has no Composio key to read it"
    return client, row["composio_connection_id"]


def _dicts_with(data: Any, key: str) -> list[dict] | None:
    """The first list of objects carrying `key`, wherever Composio nests it."""
    if isinstance(data, list):
        if data and all(isinstance(d, dict) for d in data) and any(key in d for d in data):
            return data
        if not data:
            return []
        return None
    if isinstance(data, dict):
        for name in ("items", "events", "response_data", "data", "details"):
            if name in data:
                found = _dicts_with(data[name], key)
                if found is not None:
                    return found
    return None


def parse_calendar(data: Any) -> list[CalendarEvent] | None:
    """Events from GOOGLECALENDAR_EVENTS_LIST's answer; None when it is not
    recognisable (then it is "can't tell", never "no events")."""
    items = _dicts_with(data, "start")
    if items is None:
        return None
    out = []
    for e in items:
        if e.get("status") == "cancelled":
            continue
        start = e.get("start") or {}
        when = start.get("dateTime") or start.get("date")
        if not when:
            continue
        out.append(CalendarEvent(title=str(e.get("summary") or "(no title)")[:200], start=str(when), all_day="dateTime" not in start))
    out.sort(key=lambda ev: ev.start)
    return out[:CALENDAR_LIMIT]


async def calendar_events(app_state: Any, user_id: str, now: datetime) -> CalendarView:
    from app.gateway.composio_client import ComposioError, execute_read_tool

    client, account = await _connection(app_state, user_id, "GOOGLECALENDAR")
    if client is None:
        return CalendarView(state="not-set-up") if account == "not-set-up" else CalendarView(state="unavailable", detail=account)
    args = {"calendarId": "primary", "timeMin": now.isoformat(), "timeMax": (now + timedelta(days=CALENDAR_DAYS)).isoformat(), "singleEvents": True, "orderBy": "startTime", "maxResults": 25}
    try:
        data = await asyncio.wait_for(execute_read_tool(client, slug="GOOGLECALENDAR_EVENTS_LIST", connected_account_id=account, user_id=user_id, arguments=args), READ_TIMEOUT_S)
    except (ComposioError, TimeoutError, OSError) as exc:
        return CalendarView(state="unavailable", detail=f"Google Calendar did not answer: {exc}"[:300])
    except Exception as exc:  # noqa: BLE001 — any failure is "can't tell"
        return CalendarView(state="unavailable", detail=f"Google Calendar could not be read: {type(exc).__name__}")
    events = parse_calendar(data)
    if events is None:
        return CalendarView(state="unavailable", detail="Google Calendar answered in a shape Home does not recognise")
    return CalendarView(state="ok", events=events)


async def github_items(app_state: Any, user_id: str, since: datetime) -> tuple[list[SourceItem] | None, SourceState]:
    """PRs merged since `since`, and open PRs with failing checks updated since
    then, authored by the connected account. Reported: GitHub says so."""
    from app.gateway.composio_client import execute_read_tool

    client, account = await _connection(app_state, user_id, "GITHUB")
    if client is None:
        return (None, "not-set-up") if account == "not-set-up" else (None, "unavailable")
    day = since.date().isoformat()
    queries = (
        ("merged", f"is:pr is:merged author:@me merged:>={day}"),
        ("failing", f"is:pr is:open author:@me status:failure updated:>={day}"),
    )
    out: list[SourceItem] = []
    for kind, q in queries:
        try:
            data = await asyncio.wait_for(execute_read_tool(client, slug="GITHUB_SEARCH_ISSUES_AND_PULL_REQUESTS", connected_account_id=account, user_id=user_id, arguments={"q": q, "per_page": 10}), READ_TIMEOUT_S)
        except Exception:  # noqa: BLE001 — any failure is "can't tell"
            return None, "unavailable"
        items = _dicts_with(data, "number")
        if items is None:
            return None, "unavailable"
        for it in items:
            repo = str(it.get("repository_url", "")).rsplit("/repos/", 1)[-1] or "a repository"
            title = " ".join(str(it.get("title", "")).split())[:120]
            if kind == "merged":
                at = (it.get("pull_request") or {}).get("merged_at") or it.get("closed_at") or it.get("updated_at") or ""
                text = f"PR #{it.get('number')} merged in {repo}: {title}"
            else:
                at = it.get("updated_at") or ""
                text = f"PR #{it.get('number')} in {repo} has failing checks: {title}"
            # The link is BUILT from the repository and number fetched, never
            # taken from the payload (display_safe.github_pr_link).
            from app.gateway.display_safe import github_pr_link

            out.append(SourceItem(at=str(at), source="github", text=text, known="reported", url=github_pr_link(repo, it.get("number"))))
    return out, "ok"


_SESSION_TEXT = {"completed": "Session finished", "waiting-on-user": "Session stopped, waiting on you", "failed": "Session failed", "stalled": "Session may have stalled"}


async def session_items(since: datetime) -> tuple[list[SourceItem] | None, SourceState]:
    """Sessions that finished, failed or stopped on the user since `since`, in
    the watcher's own words of how it knows (observed / inferred)."""
    from app.gateway.sessions_view import describe_sessions
    from app.gateway.watcher_client import WatcherClient, WatcherDisabled, WatcherNotConfigured, WatcherUnavailable

    try:
        payload = await WatcherClient(timeout=2.0).list_sessions()
    except (WatcherNotConfigured, WatcherDisabled):
        return None, "not-set-up"
    except WatcherUnavailable:
        return None, "unavailable"
    view = describe_sessions(payload)
    if view.sessions is None:
        return None, "unavailable"
    out = []
    for s in view.sessions:
        text = _SESSION_TEXT.get(s.display_state)
        if text is None or not s.last_activity_at:
            continue
        try:
            at = datetime.fromisoformat(s.last_activity_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if at < since:
            continue
        known: Known = "observed" if s.epistemic == "observed" else "inferred"
        label = getattr(s, "agent_label", None)
        out.append(SourceItem(at=s.last_activity_at, source="session", text=f"{text}: {s.project}" + (f" ({label})" if label else ""), known=known))
    return out, "ok"
