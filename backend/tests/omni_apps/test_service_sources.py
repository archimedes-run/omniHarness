"""The first-party sources, in process (Spec 011 Today table): Ledger, coding
sessions, automations; and the two GitHub/Calendar connector sources through
the app. No loopback HTTP: the gateway's own services are read directly."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import httpx
from conftest import manifest

LEDGER = {"use": "omni.ledger.today", "fields": ["bucket", "task", "project", "status", "due_date", "link"]}
SESSIONS = {"use": "omni.sessions.active", "fields": ["tool", "title", "display_state", "known", "since"]}
AUTOMATIONS = {"use": "omni.automations.recent", "fields": ["rule", "last_run", "outcome", "next_run"]}


def _approved(apps, **sources):
    reg = apps.register(manifest(**sources))
    apps.approve(reg.app_id)
    return reg


def test_ledger_moved_stuck_and_overdue(gateway, apps) -> None:
    repo = gateway.app.state.ledger_service.repo
    owner = gateway.user_id
    with repo.transaction() as s:
        project = repo.create(s, "project", owner_id=owner, actor="user", name="Spinusync")
        repo.create(s, "task", owner_id=owner, actor="user", project_id=project["id"], title="Overdue one", status="todo", due_date=date.today() - timedelta(days=2))
        repo.create(s, "task", owner_id=owner, actor="user", project_id=project["id"], title="Blocked one", status="blocked")
        repo.create(s, "task", owner_id=owner, actor="user", project_id=project["id"], title="Done long ago", status="done", due_date=date.today() - timedelta(days=9))
    with repo.transaction() as s:
        other = repo.create(s, "project", owner_id="someone-else", actor="user", name="Not mine")
        repo.create(s, "task", owner_id="someone-else", actor="user", project_id=other["id"], title="Never shown", status="blocked")
    reg = _approved(apps, ledger=LEDGER)
    body = gateway.client.get(f"/api/apps/{reg.app_id}/data/ledger").json()
    assert body["state"] == "fresh"
    rows = {(i["bucket"], i["task"]) for i in body["data"]["items"]}
    # Every task created today is a change since the start of today: "moved".
    assert ("overdue", "Overdue one") in rows and ("stuck", "Blocked one") in rows and ("moved", "Done long ago") in rows
    assert all(i["project"] == "Spinusync" and i["link"] == f"/workspace/projects/{project['id']}" for i in body["data"]["items"])
    assert "Never shown" not in str(body)


def test_ledger_empty_is_empty(gateway, apps) -> None:
    reg = _approved(apps, ledger=LEDGER)
    assert gateway.client.get(f"/api/apps/{reg.app_id}/data/ledger").json()["state"] == "empty"


def test_sessions_not_set_up_is_not_connected(gateway, apps) -> None:
    reg = _approved(apps, sessions=SESSIONS)
    body = gateway.client.get(f"/api/apps/{reg.app_id}/data/sessions").json()
    assert body["state"] == "not_connected" and body["data"] is None


def test_sessions_running_or_waiting(gateway, apps, monkeypatch) -> None:
    from app.gateway import sessions_view, watcher_client

    now = datetime.now(UTC).isoformat()
    rows = [
        {"project": "repo-a", "display_state": "working", "epistemic": "observed", "last_activity_at": now, "agent_label": "Codex", "summary": "SECRET SUMMARY"},
        {"project": "repo-b", "display_state": "waiting-on-user", "epistemic": "inferred", "last_activity_at": now, "agent_label": "Claude Code", "summary": ""},
        {"project": "repo-c", "display_state": "completed", "epistemic": "observed", "last_activity_at": now, "agent_label": "Codex", "summary": ""},
    ]

    async def list_sessions(self):
        return {"sessions": rows}

    monkeypatch.setattr(watcher_client.WatcherClient, "list_sessions", list_sessions)
    monkeypatch.setattr(sessions_view, "describe_sessions", lambda p, f=None: SimpleNamespace(sessions=[SimpleNamespace(**s) for s in p["sessions"]]))
    reg = _approved(apps, sessions=SESSIONS)
    body = gateway.client.get(f"/api/apps/{reg.app_id}/data/sessions").json()
    assert [(i["title"], i["display_state"], i["known"], i["tool"]) for i in body["data"]["items"]] == [("repo-a", "working", "observed", "Codex"), ("repo-b", "waiting-on-user", "inferred", "Claude Code")]
    assert "SECRET SUMMARY" not in str(body)


def test_sessions_unreachable_is_failed(gateway, apps, monkeypatch) -> None:
    from app.gateway import watcher_client

    async def list_sessions(self):
        raise watcher_client.WatcherUnreachable("refused")

    monkeypatch.setattr(watcher_client.WatcherClient, "list_sessions", list_sessions)
    reg = _approved(apps, sessions=SESSIONS)
    body = gateway.client.get(f"/api/apps/{reg.app_id}/data/sessions").json()
    assert body["state"] == "failed" and body["reason"] == "The session watcher did not answer"


def test_automations_off_is_cant_tell_not_empty(gateway, apps) -> None:
    reg = _approved(apps, automations=AUTOMATIONS)
    body = gateway.client.get(f"/api/apps/{reg.app_id}/data/automations").json()
    assert body["state"] == "failed" and body["reason"] == "Automations are switched off"


def test_automations_last_runs_and_next_runs(gateway, apps, monkeypatch, tmp_path) -> None:
    import json

    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps({"rules": [{"id": "morning-briefing", "type": "cron", "match": {"schedule": "0 8 * * *"}, "prompt": "brief me", "enabled": True}]}))
    state = tmp_path / "engine"
    state.mkdir()
    (state / "audit.jsonl").write_text(json.dumps({"at": "2026-11-13T08:00:00+00:00", "rule_id": "morning-briefing", "event_type": "cron", "event_id": "e1", "outcome": "delivered", "reason": "", "actor": "x", "batch_id": None}) + "\n")
    cfg = gateway.app.state.config.trigger_engine
    monkeypatch.setattr(cfg, "enabled", True)
    monkeypatch.setattr(cfg, "rules_path", str(rules))
    monkeypatch.setattr(cfg, "state_dir", str(state))
    reg = _approved(apps, automations=AUTOMATIONS)
    body = gateway.client.get(f"/api/apps/{reg.app_id}/data/automations").json()
    assert body["state"] == "fresh", body
    item = body["data"]["items"][0]
    assert item["rule"] == "Morning briefing" and item["outcome"] == "delivered" and item["last_run"].startswith("2026-11-13T08:00") and item["next_run"]


def test_github_review_requests_run_the_fixed_preset(gateway, composio, apps) -> None:
    composio.connect("GITHUB")
    composio.fake.answers["GITHUB_SEARCH_ISSUES_AND_PULL_REQUESTS"] = httpx.Response(
        200, json={"successful": True, "data": {"items": [{"number": 12, "title": "Add bridge", "repository_url": "https://api.github.com/repos/o/r", "updated_at": "2026-11-13T10:00:00Z", "body": "PR BODY"}]}}
    )
    reg = _approved(apps, gh_review={"use": "github.pr_search", "params": {"preset": "review_requested"}, "fields": ["repo", "number", "title", "link"]})
    body = gateway.client.get(f"/api/apps/{reg.app_id}/data/gh_review").json()
    assert body["data"]["items"] == [{"repo": "o/r", "number": 12, "title": "Add bridge", "link": "https://github.com/o/r/pull/12"}]
    assert composio.fake.calls[0][1]["arguments"]["q"] == "is:pr is:open review-requested:@me"


def test_calendar_today(gateway, composio, apps) -> None:
    composio.connect("GOOGLECALENDAR")
    event = {"summary": "Design review", "start": {"dateTime": "2026-11-13T15:00:00Z"}, "end": {"dateTime": "2026-11-13T16:00:00Z"}}
    composio.fake.answers["GOOGLECALENDAR_EVENTS_LIST"] = httpx.Response(200, json={"successful": True, "data": {"items": [event]}})
    reg = _approved(apps, calendar={"use": "googlecalendar.events_today", "params": {"tz": "Europe/London"}, "fields": ["title", "start"]})
    body = gateway.client.get(f"/api/apps/{reg.app_id}/data/calendar").json()
    assert body["state"] == "fresh" and body["data"]["items"] == [{"title": "Design review", "start": "2026-11-13T15:00:00+00:00"}]
    args = composio.fake.calls[0][1]["arguments"]
    assert args["calendarId"] == "primary" and args["timeMax"] > args["timeMin"]
