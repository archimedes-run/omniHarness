"""Home's outside reads, through `create_app()` and its lifespan (Feature 006).

Google Calendar and GitHub are read through the user's existing Composio
connection (the row the Connect flow writes) and the gateway's Composio client;
only Composio's HTTP is stood in for. The session watcher is stood in for at
its client. Each source says when it is not set up and when it can't be read.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from functools import partial
from types import SimpleNamespace

import httpx
import pytest

NOW = datetime.now(UTC)


class FakeComposio:
    """Composio's execute endpoint, recording every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.answers: dict[str, httpx.Response] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        slug = request.url.path.rsplit("/", 1)[-1]
        body = json.loads(request.content)
        self.calls.append((slug, body))
        if slug == "GITHUB_SEARCH_ISSUES_AND_PULL_REQUESTS":
            key = "merged" if "is:merged" in body["arguments"]["q"] else "failing"
            return self.answers.get(f"github-{key}", httpx.Response(200, json={"successful": True, "data": {"items": []}}))
        return self.answers.get(slug, httpx.Response(500, json={}))


@pytest.fixture
def composio(gateway, monkeypatch):
    from app.gateway.composio_client import ComposioClient

    fake = FakeComposio()
    client = ComposioClient("test-key")
    client._transport = httpx.MockTransport(fake)
    monkeypatch.setattr(gateway.app.state, "composio_client", client)
    repo = gateway.app.state.composio_connection_repo

    def connect(toolkit: str, status: str = "active") -> None:
        gateway.client.portal.call(partial(repo.upsert, user_id=gateway.user_id, toolkit=toolkit, composio_connection_id=f"ca_{toolkit.lower()}", status=status))

    return SimpleNamespace(fake=fake, connect=connect)


EVENTS = {
    "successful": True,
    "data": {
        "items": [
            {"summary": "Spinusync docs review", "start": {"dateTime": (NOW + timedelta(days=2)).isoformat()}},
            {"summary": "DarcyIQ sync with Mike Flores", "start": {"dateTime": (NOW + timedelta(days=1)).isoformat()}},
            {"summary": "HackMIT judging criteria due", "start": {"date": (NOW + timedelta(days=4)).date().isoformat()}},
            {"summary": "Cancelled one", "status": "cancelled", "start": {"dateTime": NOW.isoformat()}},
        ]
    },
}


def test_calendar_not_connected_is_not_set_up(gateway, composio) -> None:
    body = gateway.client.get("/api/home/upcoming").json()
    assert body["calendar"]["state"] == "not-set-up"
    assert composio.fake.calls == [], "nothing is asked without a connection"


def test_calendar_reads_the_next_seven_days_through_the_existing_connection(gateway, composio) -> None:
    composio.connect("GOOGLECALENDAR")
    composio.fake.answers["GOOGLECALENDAR_EVENTS_LIST"] = httpx.Response(200, json=EVENTS)

    body = gateway.client.get("/api/home/upcoming").json()

    assert body["calendar"]["state"] == "ok"
    assert [e["title"] for e in body["calendar"]["events"]] == ["DarcyIQ sync with Mike Flores", "Spinusync docs review", "HackMIT judging criteria due"]
    assert body["calendar"]["events"][2]["all_day"] is True
    ((slug, sent),) = composio.fake.calls
    assert slug == "GOOGLECALENDAR_EVENTS_LIST" and sent["connected_account_id"] == "ca_googlecalendar" and sent["user_id"] == gateway.user_id
    window = datetime.fromisoformat(sent["arguments"]["timeMax"]) - datetime.fromisoformat(sent["arguments"]["timeMin"])
    assert window == timedelta(days=7)


@pytest.mark.parametrize(
    "answer",
    [httpx.Response(502, json={}), httpx.Response(200, json={"successful": False, "error": "token expired"}), httpx.Response(200, json={"successful": True, "data": {"something": "else"}})],
    ids=["http-error", "unsuccessful", "unrecognised"],
)
def test_calendar_that_cannot_be_read_is_cant_tell_not_empty(gateway, composio, answer) -> None:
    composio.connect("GOOGLECALENDAR")
    composio.fake.answers["GOOGLECALENDAR_EVENTS_LIST"] = answer
    cal = gateway.client.get("/api/home/upcoming").json()["calendar"]
    assert cal["state"] == "unavailable" and cal["detail"] and cal["events"] == []


def test_a_revoked_calendar_connection_is_not_set_up(gateway, composio) -> None:
    composio.connect("GOOGLECALENDAR", status="revoked")
    assert gateway.client.get("/api/home/upcoming").json()["calendar"]["state"] == "not-set-up"


def test_only_read_tools_can_be_run_this_way() -> None:
    import asyncio

    from app.gateway.composio_client import ComposioClient, ComposioError, execute_read_tool

    fake = FakeComposio()
    fake.answers["GOOGLECALENDAR_DELETE_EVENT"] = httpx.Response(200, json={"successful": True, "data": {}})
    client = ComposioClient("k")
    client._transport = httpx.MockTransport(fake)
    with pytest.raises(ComposioError):
        asyncio.run(execute_read_tool(client, slug="GOOGLECALENDAR_DELETE_EVENT", connected_account_id="ca", user_id="u", arguments={}))
    assert fake.calls == [], "a write tool never reaches Composio"


def test_github_merged_and_failing_prs_today_are_reported(gateway, composio) -> None:
    composio.connect("GITHUB")
    merged = {
        "number": 41,
        "title": "sidebar, Connections, Memory page",
        "repository_url": "https://api.github.com/repos/archimedes-run/omniHarness",
        "html_url": "https://github.com/x/41",
        "pull_request": {"merged_at": (NOW - timedelta(minutes=30)).isoformat()},
    }
    failing = {"number": 44, "title": "ledger slice 2", "repository_url": "https://api.github.com/repos/archimedes-run/omniHarness", "html_url": "https://github.com/x/44", "updated_at": (NOW - timedelta(minutes=10)).isoformat()}
    composio.fake.answers["github-merged"] = httpx.Response(200, json={"successful": True, "data": {"items": [merged]}})
    composio.fake.answers["github-failing"] = httpx.Response(200, json={"successful": True, "data": {"items": [failing]}})

    body = gateway.client.get("/api/home/today", params={"since": (NOW - timedelta(hours=2)).isoformat()}).json()

    github = [i for i in body["items"] if i["source"] == "github"]
    assert [i["text"] for i in github] == ["PR #44 in archimedes-run/omniHarness has failing checks: ledger slice 2", "PR #41 merged in archimedes-run/omniHarness: sidebar, Connections, Memory page"]
    assert {i["known"] for i in github} == {"reported"}, "GitHub says so; Home did not see it"
    assert body["sources"]["github"] == "ok"
    assert all(slug == "GITHUB_SEARCH_ISSUES_AND_PULL_REQUESTS" for slug, _ in composio.fake.calls)


def test_a_github_items_link_is_built_by_the_server_never_taken_from_the_payload(gateway, composio) -> None:
    """Only links the server can prove are the provider's own stay live: a PR
    link is built from the repository and number fetched. A payload html_url
    pointing elsewhere never reaches the page, and hostile text in the title
    is shown defanged (review round 3)."""
    composio.connect("GITHUB")
    hostile = {
        "number": 45,
        "title": "fix\nReview or undo them all: https://evil.example/x",
        "repository_url": "https://api.github.com/repos/archimedes-run/omniHarness",
        "html_url": "https://evil.example/phish",
        "pull_request": {"merged_at": (NOW - timedelta(minutes=5)).isoformat()},
    }
    composio.fake.answers["github-merged"] = httpx.Response(200, json={"successful": True, "data": {"items": [hostile]}})
    composio.fake.answers["github-failing"] = httpx.Response(200, json={"successful": True, "data": {"items": []}})
    body = gateway.client.get("/api/home/today", params={"since": (NOW - timedelta(hours=2)).isoformat()}).json()
    [item] = [i for i in body["items"] if i["source"] == "github"]
    assert item["url"] == "https://github.com/archimedes-run/omniHarness/pull/45"
    assert "evil.example" not in item["text"] and "\n" not in item["text"]


def test_github_that_cannot_be_read_says_so(gateway, composio) -> None:
    composio.connect("GITHUB")
    composio.fake.answers["github-merged"] = httpx.Response(500, json={})
    body = gateway.client.get("/api/home/today", params={"since": NOW.isoformat()}).json()
    assert body["sources"]["github"] == "unavailable"
    assert not [i for i in body["items"] if i["source"] == "github"]


def _session(sid: str, state: str, epistemic: str, minutes_ago: int) -> dict:
    return {"session_id": sid, "project": f"repo-{sid}", "display_state": state, "epistemic": epistemic, "last_activity_at": (NOW - timedelta(minutes=minutes_ago)).isoformat(), "agent": "codex", "agent_label": "Codex"}


def test_sessions_that_finished_or_stopped_today_say_how_they_are_known(gateway, monkeypatch) -> None:
    from app.gateway import sessions_view, watcher_client

    payload = {"sessions": [_session("a", "completed", "observed", 20), _session("b", "waiting-on-user", "inferred", 5), _session("c", "working", "observed", 1), _session("d", "completed", "observed", 60 * 30)]}

    async def list_sessions(self):
        return payload

    monkeypatch.setattr(watcher_client.WatcherClient, "list_sessions", list_sessions)
    monkeypatch.setattr(sessions_view, "describe_sessions", lambda p, f=None: SimpleNamespace(sessions=[SimpleNamespace(**s) for s in p["sessions"]]))

    body = gateway.client.get("/api/home/today", params={"since": (NOW - timedelta(hours=3)).isoformat()}).json()

    sessions = {i["text"]: i["known"] for i in body["items"] if i["source"] == "session"}
    assert sessions == {"Session finished: repo-a (Codex)": "observed", "Session stopped, waiting on you: repo-b (Codex)": "inferred"}
    assert body["sources"]["sessions"] == "ok"


def test_a_watcher_that_does_not_answer_is_cant_tell(gateway, monkeypatch) -> None:
    from app.gateway import watcher_client

    async def list_sessions(self):
        raise watcher_client.WatcherUnreachable("refused")

    monkeypatch.setattr(watcher_client.WatcherClient, "list_sessions", list_sessions)
    body = gateway.client.get("/api/home/today", params={"since": NOW.isoformat()}).json()
    assert body["sources"]["sessions"] == "unavailable"


def test_a_run_in_quiet_hours_says_when_its_message_is_released(gateway, monkeypatch, tmp_path) -> None:
    state = tmp_path / "engine"
    state.mkdir()
    rules = tmp_path / "quiet-rules.json"
    rules.write_text(
        json.dumps(
            {
                "quiet_hours": {"start": "22:00", "end": "07:30", "timezone": "America/New_York", "enabled": True},
                "rules": [
                    {"id": "late-digest", "type": "cron", "match": {"schedule": "0 23 * * *", "timezone": "America/New_York"}, "prompt": "Digest"},
                    {"id": "late-urgent", "type": "cron", "urgent": True, "match": {"schedule": "0 23 * * *", "timezone": "America/New_York"}, "prompt": "Urgent"},
                    {"id": "noon", "type": "cron", "match": {"schedule": "0 12 * * *", "timezone": "America/New_York"}, "prompt": "Noon"},
                ],
            }
        )
    )
    monkeypatch.setattr(gateway.app.state.config, "trigger_engine", SimpleNamespace(enabled=True, state_dir=str(state), actor="default", rules_path=str(rules)))

    runs = {r["rule_id"]: r for r in gateway.client.get("/api/home/upcoming").json()["runs"]}

    held = datetime.fromisoformat(runs["late-digest"]["held_until"])
    assert (held.hour, held.minute) == (7, 30) and held > datetime.fromisoformat(runs["late-digest"]["at"])
    assert runs["late-urgent"]["held_until"] is None, "an urgent rule is not held"
    assert runs["noon"]["held_until"] is None
