"""Projection fixes found checking the live Today app against real data.

GitHub items carry the repository and a link built here from whichever field
the search answer has; a capped answer says there is more; automations give
the next run of scheduled rules and say when a rule runs on events instead;
all-day events stay dates in the owner's own day; and every source reports
`empty` only after a good answer: a shape it does not recognise, or an
upstream that cannot be reached, is `failed`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from _apps_helpers import manifest

from app.gateway.apps import catalog
from app.gateway.apps.manifest import manifest_hash, validate_manifest

NOW = datetime(2026, 11, 13, 15, 0, tzinfo=UTC)
GH = catalog.CATALOG["github.pr_search"]
CAL = catalog.CATALOG["googlecalendar.events_today"]
P = {"preset": "failing", "limit": 20}


def _pr(number, **fields):
    return {"number": number, "title": f"PR {number}", "updated_at": "2026-11-13T10:00:00Z", **fields}


# -- GitHub ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "item",
    [
        _pr(59, repository_url="https://api.github.com/repos/archimedes-run/omniHarness"),
        _pr(59, html_url="https://github.com/archimedes-run/omniHarness/pull/59"),
        _pr(59, pull_request={"html_url": "https://github.com/archimedes-run/omniHarness/pull/59", "url": "https://api.github.com/repos/x/y/pulls/59"}),
        _pr(59, repository={"full_name": "archimedes-run/omniHarness"}),
    ],
)
def test_github_repo_and_link_from_every_answer_shape(item) -> None:
    out = GH.project({"total_count": 1, "items": [item]}, P, NOW)
    assert out["items"] == [{"repo": "archimedes-run/omniHarness", "number": 59, "title": "PR 59", "updated_at": "2026-11-13T10:00:00+00:00", "merged_at": None, "link": "https://github.com/archimedes-run/omniHarness/pull/59"}]
    assert out["dropped"] == 0 and out["more"] is False


def test_github_never_passes_an_upstream_url_through_and_drops_what_it_cannot_place() -> None:
    items = [
        _pr(1, html_url="https://evil.example/archimedes-run/omniHarness/pull/1"),
        _pr(2, html_url="https://github.com/o/r/pull/3"),  # number mismatch
        _pr(3, repository_url="https://api.github.com.evil.example/repos/o/r"),
        _pr(4),
        _pr(14, repository_url="https://api.github.com/repos/o/r", html_url="https://evil.example/x"),
    ]
    out = GH.project({"total_count": 5, "items": items}, P, NOW)
    assert [(i["number"], i["link"]) for i in out["items"]] == [(14, "https://github.com/o/r/pull/14")]
    assert out["dropped"] == 4
    assert all(i["repo"] for i in out["items"]), "never a blank repository"


def test_github_says_when_there_is_more_than_the_cap() -> None:
    items = [_pr(n, repository_url="https://api.github.com/repos/o/r", closed_at="2026-11-12T10:00:00Z") for n in range(20)]
    out = GH.project({"total_count": 21, "items": items}, {"preset": "merged_7d", "limit": 20}, NOW)
    assert out["more"] is True and len(out["items"]) == 20
    assert out["items"][0]["merged_at"] == "2026-11-12T10:00:00+00:00", "a merged preset takes closed_at when merged_at is absent"
    selected = catalog.select(out, GH, ["title"])
    assert selected["more"] is True and selected["dropped"] == 0 and selected["items"][0] == {"title": "PR 0"}


def test_adding_the_github_tz_param_keeps_approved_hashes() -> None:
    m = validate_manifest({"schema": 1, "name": "x", "sources": {"gh": {"use": "github.pr_search", "params": {"preset": "failing"}, "fields": ["title"]}}})
    assert m["sources"]["gh"]["params"] == {"preset": "failing", "limit": 20}
    # The canonical form is what it was before the param existed: same hash.
    before = {"gh": {"use": "github.pr_search", "params": {"preset": "failing", "limit": 20}, "fields": ["title"], "refresh_s": 300}}
    assert manifest_hash(m) == manifest_hash({"sources": before})


def test_github_fixes_reach_the_app(gateway, composio, apps) -> None:
    composio.connect("GITHUB")
    body = {"successful": True, "data": {"total_count": 21, "items": [_pr(59, html_url="https://github.com/o/r/pull/59"), _pr(60)]}}
    composio.fake.answers["GITHUB_SEARCH_ISSUES_AND_PULL_REQUESTS"] = httpx.Response(200, json=body)
    reg = apps.register(manifest(gh={"use": "github.pr_search", "params": {"preset": "failing", "limit": 2}, "fields": ["repo", "number", "link"]}))
    apps.approve(reg.app_id)
    data = gateway.client.get(f"/api/apps/{reg.app_id}/data/gh").json()["data"]
    assert data == {"more": True, "dropped": 1, "items": [{"repo": "o/r", "number": 59, "link": "https://github.com/o/r/pull/59"}]}


# -- calendar ---------------------------------------------------------------------------


def test_all_day_events_stay_dates() -> None:
    raw = {"items": [{"summary": "Home", "start": {"date": "2026-11-13"}, "end": {"date": "2026-11-14"}}, {"summary": "Standup", "start": {"dateTime": "2026-11-13T09:00:00-05:00"}, "end": {"dateTime": "2026-11-13T09:15:00-05:00"}}]}
    out = CAL.project(raw, {"tz": "America/New_York"}, NOW)
    assert out["items"][0] == {"title": "Home", "start": "2026-11-13", "end": "2026-11-14", "all_day": True}
    assert out["items"][1]["start"] == "2026-11-13T09:00:00-05:00" and out["items"][1]["all_day"] is False


@pytest.mark.parametrize(
    "now,tmin,tmax",
    [
        (datetime(2026, 11, 14, 4, 59, tzinfo=UTC), "2026-11-13T00:00:00-05:00", "2026-11-14T00:00:00-05:00"),  # 23:59 Friday in New York
        (datetime(2026, 11, 14, 5, 0, tzinfo=UTC), "2026-11-14T00:00:00-05:00", "2026-11-15T00:00:00-05:00"),  # 00:00 Saturday
        (datetime(2026, 3, 8, 12, 0, tzinfo=UTC), "2026-03-08T00:00:00-05:00", "2026-03-09T00:00:00-04:00"),  # DST starts: a 23-hour day
        (datetime(2026, 11, 1, 12, 0, tzinfo=UTC), "2026-11-01T00:00:00-04:00", "2026-11-02T00:00:00-05:00"),  # DST ends: a 25-hour day
    ],
)
def test_the_calendar_day_is_the_local_day(now, tmin, tmax) -> None:
    args = CAL.arguments({"tz": "America/New_York"}, now)
    assert (args["timeMin"], args["timeMax"]) == (tmin, tmax)


# -- automations ---------------------------------------------------------------------------

AUTOMATIONS = {"use": "omni.automations.recent", "fields": ["rule", "last_run", "outcome", "next_run"]}


def _engine(gateway, monkeypatch, tmp_path, rules):
    state = tmp_path / "engine"
    state.mkdir(exist_ok=True)
    (state / "audit.jsonl").write_text(json.dumps({"at": "2026-11-13T08:30:00+00:00", "rule_id": "morning-briefing", "event_type": "cron", "event_id": "e1", "outcome": "delivered", "reason": "", "actor": "x", "batch_id": None}) + "\n")
    path = tmp_path / "rules.json"
    path.write_text(json.dumps({"quiet_hours": {"start": "22:00", "end": "07:30", "timezone": "America/New_York", "enabled": True}, "rules": rules}))
    cfg = gateway.app.state.config.trigger_engine
    monkeypatch.setattr(cfg, "enabled", True)
    monkeypatch.setattr(cfg, "rules_path", str(path))
    monkeypatch.setattr(cfg, "state_dir", str(state))


def test_scheduled_rules_have_a_next_run_and_event_rules_say_so(gateway, apps, monkeypatch, tmp_path) -> None:
    rules = [
        {"id": "morning-briefing", "type": "cron", "enabled": True, "match": {"schedule": "30 8 * * *", "timezone": "America/New_York"}, "prompt": "brief me", "destination": "auto"},
        {"id": "blocked-session", "type": "watcher", "enabled": True, "match": {"event": "waiting-on-user"}, "prompt": "x", "destination": "auto"},
    ]
    _engine(gateway, monkeypatch, tmp_path, rules)
    reg = apps.register(manifest(automations=AUTOMATIONS))
    apps.approve(reg.app_id)
    items = {i["rule"]: i for i in gateway.client.get(f"/api/apps/{reg.app_id}/data/automations").json()["data"]["items"]}
    morning = items["Morning briefing"]
    assert morning["trigger"] == "schedule" and morning["next_run"] and morning["next_run"].endswith(("-05:00", "-04:00")) and "08:30:00" in morning["next_run"]
    assert morning["outcome"] == "delivered"
    assert items["Blocked session"] == {"rule": "Blocked session", "last_run": None, "outcome": None, "next_run": None, "trigger": "event"}, "next_run brings its trigger kind"


# -- sessions: unreachable after a good answer ----------------------------------------------

SESSIONS = {"use": "omni.sessions.active", "fields": ["tool", "title", "display_state"]}


def test_an_unreachable_watcher_after_a_good_answer_is_failed_with_stale_data(gateway, apps, monkeypatch) -> None:
    from app.gateway import sessions_view, watcher_client

    reachable = {"yes": True}

    async def list_sessions(self):
        if not reachable["yes"]:
            raise watcher_client.WatcherTimedOut("slow")
        return {"sessions": [{"project": "omniHarness@HEAD", "display_state": "working", "epistemic": "observed", "last_activity_at": NOW.isoformat(), "agent_label": "Claude Code"}]}

    monkeypatch.setattr(watcher_client.WatcherClient, "list_sessions", list_sessions)
    monkeypatch.setattr(sessions_view, "describe_sessions", lambda p, f=None: SimpleNamespace(sessions=[SimpleNamespace(**s) for s in p["sessions"]]))
    reg = apps.register(manifest(sessions=SESSIONS))
    apps.approve(reg.app_id)
    assert gateway.client.get(f"/api/apps/{reg.app_id}/data/sessions").json()["state"] == "fresh"
    reachable["yes"] = False
    gateway.client.portal.call(_age, reg.app_id)
    body = gateway.client.get(f"/api/apps/{reg.app_id}/data/sessions", params={"refresh": 1}).json()
    assert body["state"] == "failed" and body["reason"] == "The session watcher did not answer"
    assert body["stale"] is True and body["data"]["items"][0]["title"] == "omniHarness@HEAD"


async def _age(app_id):
    from sqlalchemy import update

    from omniharness.persistence.apps import AppSourceCacheRow
    from omniharness.persistence.engine import get_session_factory

    async with get_session_factory()() as s:
        await s.execute(update(AppSourceCacheRow).where(AppSourceCacheRow.app_id == app_id).values(attempted_at=0, answered_at=0))
        await s.commit()


# -- every source: a shape it does not know is failed, never empty -----------------------------


@pytest.mark.parametrize(
    "toolkit,slug,source,answer",
    [
        ("GOOGLECALENDAR", "GOOGLECALENDAR_EVENTS_LIST", {"use": "googlecalendar.events_today", "fields": ["title"]}, {"calendars": []}),
        ("GITHUB", "GITHUB_SEARCH_ISSUES_AND_PULL_REQUESTS", {"use": "github.pr_search", "params": {"preset": "failing"}, "fields": ["title"]}, {"results": "none"}),
        ("GMAIL", "GMAIL_FETCH_EMAILS", {"use": "gmail.unread_subjects", "fields": ["count"]}, {"threads": []}),
        ("GMAIL", "GMAIL_FETCH_EMAILS", {"use": "gmail.unread_subjects", "fields": ["count"]}, {"messages": "not a list"}),
    ],
)
def test_connector_shape_mismatch_is_failed(gateway, composio, apps, toolkit, slug, source, answer) -> None:
    composio.connect(toolkit)
    composio.fake.answers[slug] = httpx.Response(200, json={"successful": True, "data": answer})
    reg = apps.register(manifest(s=source))
    apps.approve(reg.app_id)
    body = gateway.client.get(f"/api/apps/{reg.app_id}/data/s").json()
    assert body["state"] == "failed" and "shape" in body["reason"] and body["data"] is None


@pytest.mark.parametrize("status", [500, 401])
def test_connector_upstream_error_is_failed(gateway, composio, apps, status) -> None:
    composio.connect("GMAIL")
    composio.fake.answers["GMAIL_FETCH_EMAILS"] = httpx.Response(status, json={})
    reg = apps.register(manifest(s={"use": "gmail.unread_subjects", "fields": ["count"]}))
    apps.approve(reg.app_id)
    body = gateway.client.get(f"/api/apps/{reg.app_id}/data/s").json()
    assert body["state"] == "failed" and body["reason"] == f"The connector answered HTTP {status}"


def test_ledger_read_failure_is_failed(gateway, apps, monkeypatch) -> None:
    repo = gateway.app.state.ledger_service.repo

    def broken(owner_id):
        raise RuntimeError("database gone")

    monkeypatch.setattr(repo, "projects", broken)
    reg = apps.register(manifest(ledger={"use": "omni.ledger.today", "fields": ["task"]}))
    apps.approve(reg.app_id)
    body = gateway.client.get(f"/api/apps/{reg.app_id}/data/ledger").json()
    assert body["state"] == "failed" and body["reason"] == "The source could not be read (RuntimeError)"


def test_sessions_unrecognised_answer_is_failed(gateway, apps, monkeypatch) -> None:
    from app.gateway import sessions_view, watcher_client

    async def list_sessions(self):
        return {"unexpected": True}

    monkeypatch.setattr(watcher_client.WatcherClient, "list_sessions", list_sessions)
    monkeypatch.setattr(sessions_view, "describe_sessions", lambda p, f=None: SimpleNamespace(sessions=None))
    reg = apps.register(manifest(sessions=SESSIONS))
    apps.approve(reg.app_id)
    body = gateway.client.get(f"/api/apps/{reg.app_id}/data/sessions").json()
    assert body["state"] == "failed" and body["reason"] == "The session watcher could not say which sessions are running"


def test_automations_unreadable_rules_are_failed(gateway, apps, monkeypatch, tmp_path) -> None:
    path = tmp_path / "rules.json"
    path.write_text("{not json")
    cfg = gateway.app.state.config.trigger_engine
    monkeypatch.setattr(cfg, "enabled", True)
    monkeypatch.setattr(cfg, "rules_path", str(path))
    monkeypatch.setattr(cfg, "state_dir", str(tmp_path))
    reg = apps.register(manifest(automations=AUTOMATIONS))
    apps.approve(reg.app_id)
    body = gateway.client.get(f"/api/apps/{reg.app_id}/data/automations").json()
    assert body["state"] == "failed" and body["reason"] == "The automation rules could not be read"
