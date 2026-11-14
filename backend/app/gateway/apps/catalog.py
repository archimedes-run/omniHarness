"""The source catalog (Spec 011 FR-001, FR-002, FR-010, FR-011).

An app never names a tool. Its manifest picks an ENTRY of this catalog, and the
entry fixes everything else: the real read tool (or the in-process reader),
the arguments it is called with, the fields an app may receive, a typed and
bounded schema for the few params a manifest may set, the words the approval
card shows, and the hosts the app's links may open.

Nothing from the frame reaches an entry at run time. Params come from the
APPROVED manifest only, validated against the entry's schema at registration.

Each entry's `project` builds its items FROM SCRATCH out of the allowed fields;
it never passes a raw object through. `select` then keeps only the fields the
manifest declared, clips strings, caps arrays and bounds the payload. Both run
before anything is cached (FR-011).
"""

from __future__ import annotations

import asyncio
import json
import re
import zoneinfo
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from typing import Any, Literal

from app.gateway.display_safe import github_pr_link
from app.gateway.home_sources import _dicts_with

#: The ONLY connector tools an app source may run. Generalises
#: composio_client.READ_ONLY_SLUGS (Home's two) with Gmail's metadata read.
#: Every one is Tier 1 in default_rules.yaml; checks.py verifies that at run
#: time too, independently of this list.
READ_ALLOWLIST = frozenset({"GOOGLECALENDAR_EVENTS_LIST", "GITHUB_SEARCH_ISSUES_AND_PULL_REQUESTS", "GMAIL_FETCH_EMAILS"})

STRING_MAX = 200
ITEMS_MAX = 50
PAYLOAD_MAX_BYTES = 64 * 1024
REFRESH_DEFAULT_S = 300
REFRESH_MIN_S = 60
REFRESH_MAX_S = 3600

#: The sentence every approval card and permissions view carries (FR-006).
DATA_SENTENCE = "Data is shown in the app only; the assistant never sees it."


class Unrecognised(Exception):
    """The upstream answered in a shape the entry does not recognise: failed,
    never empty."""


class NotConnected(Exception):
    """The source's service is not set up for this owner."""


class SourceFailed(Exception):
    """The source could not be read. The message is fixed wording, never
    upstream text."""


ParamType = Literal["integer", "enum", "timezone"]


@dataclass(frozen=True)
class Param:
    type: ParamType
    default: Any = None
    required: bool = False
    minimum: int | None = None
    maximum: int | None = None
    values: tuple[str, ...] = ()

    def schema(self) -> dict:
        out: dict[str, Any] = {"type": self.type}
        if self.type == "integer":
            out.update(minimum=self.minimum, maximum=self.maximum)
        if self.type == "enum":
            out["values"] = list(self.values)
        if self.required:
            out["required"] = True
        else:
            out["default"] = self.default
        return out


@dataclass(frozen=True)
class SourceContext:
    """What an in-process reader may use: the gateway's state and the owner."""

    app_state: Any
    owner_id: str


@dataclass(frozen=True)
class Entry:
    id: str
    kind: Literal["connector", "service"]
    item_fields: tuple[str, ...]
    field_words: dict[str, str]
    params: dict[str, Param]
    link_hosts: tuple[str, ...]
    #: The plain-words phrase for the card, from params only.
    phrase: Callable[[dict], str]
    project: Callable[[Any, dict, datetime], dict]
    top_fields: tuple[str, ...] = ()
    toolkit: str | None = None
    tool: str | None = None
    arguments: Callable[[dict, datetime], dict] | None = None
    read: Callable[[SourceContext, dict, datetime], Awaitable[Any]] | None = None
    default_refresh_s: int = REFRESH_DEFAULT_S
    #: Item keys that travel with a selected field (approving `next_run`
    #: brings its `trigger` kind, so a tile can say "runs on events").
    companions: tuple[tuple[str, tuple[str, ...]], ...] = ()
    #: Top-level facts about the answer, always sent (never the owner's
    #: data): whether the upstream had more than the cap, items dropped.
    meta_fields: tuple[str, ...] = ()

    @property
    def fields(self) -> tuple[str, ...]:
        return self.top_fields + self.item_fields

    @property
    def policy_name(self) -> str:
        """The name the policy layer classifies the tool by (connector form)."""
        return f"connector-{(self.toolkit or '').lower()}_{self.tool}"

    def words(self, params: dict, fields: list[str]) -> str:
        chosen = ", ".join(self.field_words[f] for f in self.fields if f in fields)
        return f"{self.phrase(params)}: {chosen}"

    def describe(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "toolkit": self.toolkit,
            "fields": list(self.fields),
            "params": {name: p.schema() for name, p in self.params.items()},
            "link_hosts": list(self.link_hosts),
            "default_refresh_s": self.default_refresh_s,
        }


# -- helpers -------------------------------------------------------------------


@lru_cache(maxsize=1)
def _zones() -> frozenset[str]:
    return frozenset(zoneinfo.available_timezones()) | {"UTC"}


def valid_timezone(name: object) -> bool:
    return isinstance(name, str) and len(name) <= 64 and name in _zones()


def _clip(value: object) -> str:
    text = " ".join(str(value).split())
    return text[:STRING_MAX]


def _iso(value: object) -> str | None:
    """An ISO time from an ISO string, a date, or epoch seconds/milliseconds."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        # A date stays a date (an all-day event), never midnight UTC.
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError:
            return None
    if re.fullmatch(r"\d{10,13}", text):
        seconds = int(text) / (1000 if len(text) == 13 else 1)
        return datetime.fromtimestamp(seconds, UTC).isoformat()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError:
            return None
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).isoformat()


def _day_bounds(tz_name: str, now: datetime) -> tuple[datetime, datetime]:
    tz = zoneinfo.ZoneInfo(tz_name)
    local = now.astimezone(tz)
    start = datetime.combine(local.date(), time.min, tzinfo=tz)
    return start, start + timedelta(days=1)


# -- Google Calendar -----------------------------------------------------------


def _calendar_args(params: dict, now: datetime) -> dict:
    start, end = _day_bounds(params["tz"], now)
    return {"calendarId": "primary", "timeMin": start.isoformat(), "timeMax": end.isoformat(), "singleEvents": True, "orderBy": "startTime", "maxResults": ITEMS_MAX}


def _calendar_project(raw: Any, params: dict, now: datetime) -> dict:
    events = _dicts_with(raw, "start")
    if events is None:
        raise Unrecognised("Google Calendar answered in a shape the app platform does not recognise")
    items = []
    for e in events:
        if e.get("status") == "cancelled":
            continue
        start, end = e.get("start") or {}, e.get("end") or {}
        if not isinstance(start, dict):
            continue
        when = start.get("dateTime") or start.get("date")
        if not when:
            continue
        until = end.get("dateTime") or end.get("date") if isinstance(end, dict) else None
        items.append({"title": _clip(e.get("summary") or "(no title)"), "start": _iso(when), "end": _iso(until), "all_day": "dateTime" not in start})
    items.sort(key=lambda i: i["start"] or "")
    return {"items": items}


# -- GitHub --------------------------------------------------------------------

GITHUB_PRESETS = ("review_requested", "failing", "merged_7d", "merged_week")


def _local_midnight(tz_name: str, now: datetime, days_back: int = 0) -> datetime:
    start, _ = _day_bounds(tz_name, now)
    return datetime.combine(start.date() - timedelta(days=days_back), time.min, tzinfo=zoneinfo.ZoneInfo(tz_name))


def github_since(preset: str, now: datetime, tz_name: str | None) -> datetime | None:
    """Where a merged preset's window starts, in the manifest's zone (UTC when
    the manifest names none): merged_7d, the local midnight six days before
    today (seven local days, today included); merged_week, Monday 00:00 of
    this local week (ISO weeks start on Monday)."""
    tz_name = tz_name or "UTC"
    if preset == "merged_7d":
        return _local_midnight(tz_name, now, 6)
    if preset == "merged_week":
        return _local_midnight(tz_name, now, now.astimezone(zoneinfo.ZoneInfo(tz_name)).weekday())
    return None


def _github_query(preset: str, now: datetime, tz_name: str | None = None) -> str:
    if preset == "review_requested":
        return "is:pr is:open review-requested:@me"
    if preset == "failing":
        return "is:pr is:open author:@me status:failure"
    since = github_since(preset, now, tz_name)
    if since is not None:
        return f"is:pr is:merged author:@me merged:>={since.isoformat()}"
    raise ValueError(f"unknown preset {preset}")


def _github_args(params: dict, now: datetime) -> dict:
    return {"q": _github_query(params["preset"], now, params.get("tz")), "per_page": params["limit"], "sort": "updated", "order": "desc"}


_API_REPO = re.compile(r"^https://api\.github\.com/repos/([A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100})$")
_HTML_PR = re.compile(r"^https://github\.com/([A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100})/(?:pull|issues)/(\d{1,10})$")


def github_repo(item: dict) -> str | None:
    """OWNER/NAME of a search result, from the fields search answers carry:
    `repository_url` (the API's), `repository.full_name`, or the item's own
    GitHub page (`html_url`, `pull_request.html_url`) when its number matches.
    Only the name is taken; the link is always built here."""
    m = _API_REPO.match(str(item.get("repository_url") or ""))
    if m:
        return m.group(1)
    repo = item.get("repository")
    if isinstance(repo, dict) and _GITHUB_REPO_NAME.match(str(repo.get("full_name") or "")):
        return str(repo["full_name"])
    pull = item.get("pull_request") if isinstance(item.get("pull_request"), dict) else {}
    for url in (item.get("html_url"), pull.get("html_url")):
        m = _HTML_PR.match(str(url or ""))
        if m and int(m.group(2)) == item.get("number"):
            return m.group(1)
    return None


_GITHUB_REPO_NAME = re.compile(r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}$")


def merged_at(item: dict, params: dict) -> object:
    """The merge time: the search answer's `pull_request.merged_at`, or, for a
    merged preset (every result is merged), its `closed_at`."""
    pull = item.get("pull_request") if isinstance(item.get("pull_request"), dict) else {}
    if pull.get("merged_at"):
        return pull["merged_at"]
    return item.get("closed_at") if str(params.get("preset", "")).startswith("merged") else None


def _github_project(raw: Any, params: dict, now: datetime) -> dict:
    found = _dicts_with(raw, "number")
    if found is None:
        raise Unrecognised("GitHub answered in a shape the app platform does not recognise")
    items = []
    dropped = 0
    for it in found:
        number = it.get("number")
        repo = github_repo(it) if isinstance(number, int) and not isinstance(number, bool) else None
        link = github_pr_link(repo, number) if repo else None
        if repo is None or link is None:
            dropped += 1  # never shown with a blank repository or link
            continue
        items.append({"repo": _clip(repo), "number": number, "title": _clip(it.get("title", "")), "updated_at": _iso(it.get("updated_at")), "merged_at": _iso(merged_at(it, params)), "link": link})
    total = raw.get("total_count") if isinstance(raw, dict) else None
    if total is None and isinstance(raw, dict) and isinstance(raw.get("data"), dict):
        total = raw["data"].get("total_count")
    more = (isinstance(total, int) and not isinstance(total, bool) and total > len(found)) or len(found) >= params.get("limit", ITEMS_MAX)
    return {"items": items, "more": bool(more), "dropped": dropped}


_GITHUB_PHRASES = {
    "review_requested": "Search GitHub for open pull requests waiting on your review",
    "failing": "Search GitHub for your open pull requests with failing checks",
    "merged_7d": "Search GitHub for your pull requests merged in the last 7 days",
    "merged_week": "Search GitHub for your pull requests merged this week (since Monday)",
}

# -- Gmail ---------------------------------------------------------------------

INBOX_QUERY = "in:inbox is:unread category:primary -from:me newer_than:3d"
_GMAIL_ID = re.compile(r"^[0-9a-fA-F]{8,32}$")


def _gmail_args(params: dict, now: datetime) -> dict:
    # Metadata only: no payload, no body (verbose off).
    return {"query": INBOX_QUERY, "max_results": params["limit"], "include_payload": False, "verbose": False, "user_id": "me"}


def _subject(message: dict) -> str:
    if isinstance(message.get("subject"), str):
        return message["subject"]
    preview = message.get("preview")
    if isinstance(preview, dict) and isinstance(preview.get("subject"), str):
        return preview["subject"]
    payload = message.get("payload")
    headers = payload.get("headers") if isinstance(payload, dict) else None
    for h in headers if isinstance(headers, list) else []:
        if isinstance(h, dict) and str(h.get("name", "")).lower() == "subject":
            return str(h.get("value", ""))
    return "(no subject)"


def _gmail_project(raw: Any, params: dict, now: datetime) -> dict:
    messages = None
    if isinstance(raw, dict) and isinstance(raw.get("messages"), list):
        messages = raw["messages"]
    elif isinstance(raw, dict) and isinstance(raw.get("data"), dict) and isinstance(raw["data"].get("messages"), list):
        messages = raw["data"]["messages"]
    if messages is None or not all(isinstance(m, dict) for m in messages):
        raise Unrecognised("Gmail answered in a shape the app platform does not recognise")
    items = []
    for m in messages:
        thread = str(m.get("threadId") or m.get("thread_id") or "")
        items.append(
            {
                "subject": _clip(_subject(m)),
                "received_at": _iso(m.get("messageTimestamp") or m.get("internalDate")),
                "link": f"https://mail.google.com/mail/u/0/#inbox/{thread}" if _GMAIL_ID.match(thread) else None,
            }
        )
    more = bool((raw.get("nextPageToken") or (raw.get("data") or {}).get("nextPageToken")) if isinstance(raw, dict) else False)
    return {"count": len(items), "count_capped": more or len(items) >= params["limit"], "items": items}


# -- in-process readers ----------------------------------------------------------


async def _ledger_read(ctx: SourceContext, params: dict, now: datetime) -> dict:
    service = getattr(ctx.app_state, "ledger_service", None)
    if service is None:
        raise SourceFailed("The Project Ledger needs a database")
    start, _ = _day_bounds(params["tz"], now)
    repo = service.repo

    def read() -> dict:
        projects = repo.projects(ctx.owner_id)
        return {"projects": projects, "tasks": [t for p in projects for t in repo.children("task", p["id"])], "changes": repo.changes_since(ctx.owner_id, start.astimezone(UTC))}

    return await asyncio.to_thread(read)


def _ledger_project(raw: Any, params: dict, now: datetime) -> dict:
    tz = zoneinfo.ZoneInfo(params["tz"])
    today = now.astimezone(tz).date()
    names = {p["id"]: p.get("name", "") for p in raw["projects"]}
    moved = {c.get("entity_id") for c in raw["changes"] if c.get("entity") == "task"}
    stuck_before = now - timedelta(days=3)
    items: list[tuple[int, dict]] = []
    for t in raw["tasks"]:
        status = str(t.get("status", ""))
        due = t.get("due_date")
        try:
            due_day = date.fromisoformat(str(due)) if due else None
        except ValueError:
            due_day = None
        updated = _iso(t.get("updated_at"))
        updated_at = datetime.fromisoformat(updated) if updated and "T" in updated else None
        if due_day is not None and due_day < today and status not in ("done", "dropped"):
            bucket, rank = "overdue", 0
        elif status == "blocked" or (status == "doing" and updated_at is not None and updated_at < stuck_before):
            bucket, rank = "stuck", 1
        elif t.get("id") in moved:
            bucket, rank = "moved", 2
        else:
            continue
        project_id = t.get("project_id")
        item = {"bucket": bucket, "task": _clip(t.get("title", "")), "project": _clip(names.get(project_id, "")), "status": status, "due_date": due_day.isoformat() if due_day else None, "link": f"/workspace/projects/{project_id}"}
        items.append((rank, item))
    items.sort(key=lambda pair: pair[0])
    return {"items": [i for _, i in items]}


async def _sessions_read(ctx: SourceContext, params: dict, now: datetime) -> Any:
    from app.gateway.sessions_view import describe_sessions
    from app.gateway.watcher_client import WatcherClient, WatcherDisabled, WatcherNotConfigured, WatcherUnavailable

    try:
        payload = await WatcherClient(timeout=2.0).list_sessions()
    except (WatcherNotConfigured, WatcherDisabled) as exc:
        raise NotConnected("the session watcher is not set up") from exc
    except WatcherUnavailable as exc:
        raise SourceFailed("The session watcher did not answer") from exc
    view = describe_sessions(payload)
    if view.sessions is None:
        raise SourceFailed("The session watcher could not say which sessions are running")
    return view.sessions


def _sessions_project(raw: Any, params: dict, now: datetime) -> dict:
    items = []
    for s in raw:
        if s.display_state not in ("working", "waiting-on-user"):
            continue
        items.append({"tool": _clip(s.agent_label), "title": _clip(s.project), "display_state": s.display_state, "known": "observed" if s.epistemic == "observed" else "inferred", "since": _iso(s.last_activity_at)})
    return {"items": items}


async def _automations_read(ctx: SourceContext, params: dict, now: datetime) -> dict:
    cfg = ctx.app_state.config.trigger_engine
    if not cfg.enabled:
        raise SourceFailed("Automations are switched off")

    def read() -> dict:
        from pathlib import Path

        from app.gateway.trigger_engine_wiring import _quiet_hours, _resolve_rules_path
        from app.gateway.triggers_view import describe_firings, next_run
        from app.trigger_engine.audit import AuditLog
        from app.trigger_engine.config import ConfigLoader

        loader = ConfigLoader(path=_resolve_rules_path(cfg))
        config = loader.load()
        if loader.last_error:
            raise SourceFailed("The automation rules could not be read")
        quiet = _quiet_hours(config)
        firings = describe_firings(AuditLog(path=Path(cfg.state_dir) / "audit.jsonl", actor=cfg.actor).entries()).firings
        last = {}
        for f in firings:  # newest first
            last.setdefault(f.rule_id, f)
        rows = []
        for rule in config.rules:
            if not rule.enabled:
                continue
            nxt = next_run(rule, now=now, engine_enabled=True, quiet_hours=quiet)
            f = last.get(rule.id)
            trigger = "schedule" if str(rule.type) == "cron" else "event"
            rows.append({"rule_id": rule.id, "last_run": f.at if f else None, "outcome": f.outcome if f else None, "next_run": nxt.get("next_run_at") if trigger == "schedule" else None, "trigger": trigger})
        return {"rows": rows}

    return await asyncio.to_thread(read)


def _automations_project(raw: Any, params: dict, now: datetime) -> dict:
    from app.gateway.home_view import rule_title

    rows = sorted(raw["rows"], key=lambda r: r["last_run"] or "", reverse=True)[: params["limit"]]
    return {"items": [{"rule": _clip(rule_title(r["rule_id"])), "last_run": _iso(r["last_run"]), "outcome": _clip(r["outcome"]) if r["outcome"] else None, "next_run": _iso(r["next_run"]), "trigger": r["trigger"]} for r in rows]}


# -- the catalog -----------------------------------------------------------------

_TZ = Param(type="timezone", default="UTC")


def _limit(default: int) -> Param:
    return Param(type="integer", default=default, minimum=1, maximum=ITEMS_MAX)


CATALOG: dict[str, Entry] = {
    e.id: e
    for e in (
        Entry(
            id="googlecalendar.events_today",
            kind="connector",
            toolkit="GOOGLECALENDAR",
            tool="GOOGLECALENDAR_EVENTS_LIST",
            item_fields=("title", "start", "end", "all_day"),
            field_words={"title": "title", "start": "start", "end": "end", "all_day": "all day"},
            params={"tz": _TZ},
            link_hosts=("calendar.google.com",),
            phrase=lambda p: f"Read today's events from Google Calendar, for the day in {p['tz']}",
            arguments=_calendar_args,
            project=_calendar_project,
        ),
        Entry(
            id="github.pr_search",
            kind="connector",
            toolkit="GITHUB",
            tool="GITHUB_SEARCH_ISSUES_AND_PULL_REQUESTS",
            item_fields=("repo", "number", "title", "updated_at", "merged_at", "link"),
            field_words={"repo": "repository", "number": "number", "title": "title", "updated_at": "last updated", "merged_at": "merged time", "link": "link"},
            params={"preset": Param(type="enum", values=GITHUB_PRESETS, required=True), "limit": _limit(20), "tz": Param(type="timezone", default=None)},
            link_hosts=("github.com",),
            meta_fields=("more", "dropped"),
            phrase=lambda p: f"{_GITHUB_PHRASES[p['preset']]}, up to {p['limit']}",
            arguments=_github_args,
            project=_github_project,
        ),
        Entry(
            id="gmail.unread_subjects",
            kind="connector",
            toolkit="GMAIL",
            tool="GMAIL_FETCH_EMAILS",
            top_fields=("count",),
            item_fields=("subject", "received_at", "link"),
            field_words={"count": "how many", "subject": "subject", "received_at": "received time", "link": "link"},
            params={"limit": _limit(25)},
            link_hosts=("mail.google.com",),
            phrase=lambda p: f"Read subjects of unread mail in Primary from the last 3 days, not from you (not bodies), up to {p['limit']}",
            arguments=_gmail_args,
            project=_gmail_project,
        ),
        Entry(
            id="omni.ledger.today",
            kind="service",
            item_fields=("bucket", "task", "project", "status", "due_date", "link"),
            field_words={"bucket": "moved, stuck or overdue", "task": "task", "project": "project", "status": "status", "due_date": "due date", "link": "link"},
            params={"tz": _TZ},
            link_hosts=(),
            phrase=lambda p: f"Read your Project Ledger tasks that moved today, are stuck or are overdue, for the day in {p['tz']}",
            read=_ledger_read,
            project=_ledger_project,
        ),
        Entry(
            id="omni.sessions.active",
            kind="service",
            item_fields=("tool", "title", "display_state", "known", "since"),
            field_words={"tool": "coding tool", "title": "project", "display_state": "working or waiting on you", "known": "how it is known", "since": "since when"},
            params={},
            link_hosts=(),
            phrase=lambda p: "Read which coding sessions are running or waiting on you",
            read=_sessions_read,
            project=_sessions_project,
        ),
        Entry(
            id="omni.automations.recent",
            kind="service",
            item_fields=("rule", "last_run", "outcome", "next_run", "trigger"),
            field_words={"rule": "automation name", "last_run": "last run", "outcome": "outcome", "next_run": "next run", "trigger": "scheduled or on events"},
            companions=(("next_run", ("trigger",)),),
            params={"limit": _limit(10)},
            link_hosts=(),
            phrase=lambda p: f"Read your automations' last runs, outcomes and next runs, up to {p['limit']}",
            read=_automations_read,
            project=_automations_project,
        ),
    )
}


def get_entry(entry_id: str) -> Entry | None:
    return CATALOG.get(entry_id)


def is_empty(projected: dict) -> bool:
    return not projected.get("items") and not projected.get("count")


def select(projected: dict, entry: Entry, fields: list[str]) -> dict:
    """Keep only the declared fields; clip, cap and bound (FR-011)."""
    chosen = set(fields)
    for field, extra in entry.companions:
        if field in chosen:
            chosen.update(extra)
    wanted_items = [f for f in entry.item_fields if f in chosen]
    out: dict[str, Any] = {key: projected[key] for key in entry.meta_fields if key in projected}
    for top in entry.top_fields:
        if top in fields:
            out[top] = projected.get(top)
            if top == "count":
                out["count_capped"] = bool(projected.get("count_capped"))
    items = []
    for item in (projected.get("items") or [])[:ITEMS_MAX]:
        row = {}
        for f in wanted_items:
            value = item.get(f)
            row[f] = _clip(value) if isinstance(value, str) else value
        items.append(row)
    out["items"] = items
    while len(json.dumps(out, separators=(",", ":")).encode()) > PAYLOAD_MAX_BYTES and out["items"]:
        out["items"].pop()
    return out


def refresh_words(seconds: int) -> str:
    if seconds % 3600 == 0:
        n, unit = seconds // 3600, "hour"
    elif seconds % 60 == 0:
        n, unit = seconds // 60, "minute"
    else:
        n, unit = seconds, "second"
    every = f"every {unit}" if n == 1 else f"every {n} {unit}s"
    return f"Refreshes {every} while you use it"


def describe_catalog() -> dict:
    return {"entries": [e.describe() for e in CATALOG.values()], "refresh_s": {"default": REFRESH_DEFAULT_S, "minimum": REFRESH_MIN_S, "maximum": REFRESH_MAX_S}}
