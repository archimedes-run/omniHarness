"""Fixture tools for the eval (spec 009 FR-072).

Private-data tools (calendar, mail) are stubs registered under their REAL tool
names, so the policy rules (default_rules.yaml: `googlecalendar_list*`,
`gmail_search*`, `gmail_read*`, `gmail_draft_email`), the private-read walk
and the card flow treat them exactly as the real ones. They never reach an
account. The web stubs replace the network in mock mode only; real mode uses
the configured web tools.

A trial's config names them under `tools:` (`use: omni_eval.stubs:<name>`).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from langchain_core.tools import tool

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

#: What the stubs were asked, for checks that need it (mock and real).
CALLS: list[dict] = []
#: Drafts the mail stub "saved" (nothing is sent; there is no send tool).
DRAFTS: list[dict] = []


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _monday(now: datetime) -> datetime:
    return (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)


def calendar_events(now: datetime | None = None) -> list[dict]:
    now = now or datetime.now()
    monday = _monday(now)
    out = []
    for event in _load("calendar.json")["events"]:
        day = monday + timedelta(days=event["day"])
        out.append({"summary": event["title"], "start": f"{day:%Y-%m-%d}T{event['start']}:00", "end": f"{day:%Y-%m-%d}T{event['end']}:00", "location": event["location"], "weekday": f"{day:%A}"})
    return out


def mail_messages(now: datetime | None = None) -> list[dict]:
    now = now or datetime.now()
    out = []
    for message in _load("mail.json")["messages"]:
        when = now - timedelta(hours=message["hours_ago"])
        out.append({"id": message["id"], "from": message["from"], "subject": message["subject"], "date": f"{when:%Y-%m-%d %H:%M}", "snippet": message["body"][:120], "body": message["body"], "unread": message["unread"]})
    return out


@tool("googlecalendar_list-events")
def calendar_list_events(timeMin: str | None = None, timeMax: str | None = None, calendarId: str | None = None) -> str:  # noqa: N803 - the real server's argument names
    """List events in the user's Google Calendar between timeMin and timeMax (ISO 8601). Read-only."""
    CALLS.append({"tool": "googlecalendar_list-events", "args": {"timeMin": timeMin, "timeMax": timeMax}})
    events = calendar_events()
    try:
        if timeMin:
            lo = datetime.fromisoformat(timeMin.replace("Z", "+00:00")).replace(tzinfo=None)
            events = [e for e in events if datetime.fromisoformat(e["end"]) >= lo - timedelta(days=1)]
        if timeMax:
            hi = datetime.fromisoformat(timeMax.replace("Z", "+00:00")).replace(tzinfo=None)
            events = [e for e in events if datetime.fromisoformat(e["start"]) <= hi + timedelta(days=1)]
    except ValueError:
        pass
    return json.dumps({"events": events}, indent=1)


@tool("gmail_search_emails")
def gmail_search_emails(query: str = "", maxResults: int = 20) -> str:  # noqa: N803
    """Search the user's Gmail messages (Gmail search syntax, e.g. 'newer_than:2d'). Returns id, from, subject, date and a snippet. Read-only."""
    CALLS.append({"tool": "gmail_search_emails", "args": {"query": query}})
    return json.dumps({"messages": [{k: m[k] for k in ("id", "from", "subject", "date", "snippet", "unread")} for m in mail_messages()][: max(1, int(maxResults or 20))]}, indent=1)


@tool("gmail_read_email")
def gmail_read_email(messageId: str) -> str:  # noqa: N803
    """Read one Gmail message by id. Read-only."""
    CALLS.append({"tool": "gmail_read_email", "args": {"messageId": messageId}})
    for message in mail_messages():
        if message["id"] == messageId:
            return json.dumps(message, indent=1)
    raise ValueError(f"No message with id {messageId!r}")


@tool("gmail_draft_email")
def gmail_draft_email(to: list[str], subject: str, body: str) -> str:
    """Save a draft email (it is NOT sent; the user sends drafts themselves)."""
    CALLS.append({"tool": "gmail_draft_email", "args": {"to": to, "subject": subject}})
    DRAFTS.append({"to": to, "subject": subject, "body": body})
    return f"Draft saved: {subject}"


# ---------------------------------------------------------------- web (mock)


def _web() -> dict:
    return _load("web.json")


@tool("web_search")
def web_search(query: str) -> str:
    """Search the web. Returns a JSON list of results with title, url and snippet."""
    CALLS.append({"tool": "web_search", "args": {"query": query}})
    data = _web()
    q = (query or "").lower()
    for topic in data["search"]:
        if all(k in q for k in topic["keywords"]):
            return json.dumps(topic["results"], indent=1)
    return json.dumps(data["default_search"], indent=1)


@tool("web_fetch")
def web_fetch(url: str) -> str:
    """Fetch the contents of a web page at a given URL."""
    CALLS.append({"tool": "web_fetch", "args": {"url": url}})
    data = _web()
    page = data["pages"].get(url)
    if page and page.get("error"):
        raise RuntimeError(page["error"])
    if page:
        return page["text"]
    return data["default_page"].format(url=url)


@tool("image_search")
def image_search(query: str) -> str:
    """Search for images. Returns a JSON list with title, image_url and source url."""
    CALLS.append({"tool": "image_search", "args": {"query": query}})
    return json.dumps([{"title": f"Image for {query}", "image_url": "https://images.example.org/1.jpg", "url": "https://example.org/gallery"}])


def reset() -> None:
    CALLS.clear()
    DRAFTS.clear()
