"""Tool assembly never holds the gateway's event loop.

Measured on 2026-11-15: opening a chat asked `GET /api/threads/{id}/tools/count`,
which assembled the chat's tools on the event loop. Connector toolkits start a
server process each and list their tools over it, and one took about 75
seconds: for all of it the gateway answered nothing (requests behind it hit
the proxy's 60 s limit, the bot poller failed).

The gateway is `create_app()` with its real lifespan and the real connector
loader; only the toolkit's server is a stand-in whose start-and-list step
takes a few seconds. While the count request is in flight, another request
must be answered at once.
"""

from __future__ import annotations

import asyncio
import threading
import time

from langchain_core.tools import StructuredTool

#: How long the stand-in toolkit takes to start and list its tools.
SLOW = 3.0


def _slow_client(listed: list[str]):
    class SlowClient:
        def __init__(self, connections, tool_name_prefix=False):
            [(self.server, _spec)] = connections.items()

        async def get_tools(self):
            await asyncio.sleep(SLOW)
            return [StructuredTool.from_function(func=lambda: "", name=f"{self.server}_{n}", description=n) for n in listed]

    return SlowClient


def test_a_slow_connector_load_does_not_hold_other_requests(studio, monkeypatch) -> None:
    import omniharness.tools.connector_tools as connector_tools

    client = studio.client
    repo = client.app.state.composio_connection_repo
    client.portal.call(lambda: repo.upsert(user_id=studio.user_id, toolkit="GMAIL", composio_connection_id="ca-GMAIL", status="active"))

    async def active(user_id, toolkits):
        return {"GMAIL": "ca-GMAIL"} if "GMAIL" in toolkits else {}

    monkeypatch.setenv("COMPOSIO_API_KEY", "test-key")
    monkeypatch.setattr(connector_tools, "_active_accounts_for_user", active)
    monkeypatch.setattr("langchain_mcp_adapters.client.MultiServerMCPClient", _slow_client(["send_email", "fetch_emails"]))

    tid = client.post("/api/threads", json={}).json()["thread_id"]
    assert "connector:GMAIL" in client.get(f"/api/threads/{tid}/tools").json()["sources"]

    count: dict = {}

    def ask_count() -> None:
        started = time.monotonic()
        resp = client.get(f"/api/threads/{tid}/tools/count")
        count.update(status=resp.status_code, body=resp.json(), took=time.monotonic() - started, done=time.monotonic())

    asker = threading.Thread(target=ask_count)
    asker.start()
    time.sleep(0.5)  # the count request is now loading the toolkit

    started = time.monotonic()
    health = client.get("/health")
    answered_in = time.monotonic() - started
    answered_at = time.monotonic()
    asker.join(timeout=30)

    assert health.status_code == 200
    assert count["status"] == 200, count
    # The count did wait for the toolkit (the loader really ran)...
    assert count["took"] >= SLOW - 0.2, count
    # ...and the other request did not wait for it.
    assert answered_in < 1.0, f"/health waited {answered_in:.2f}s behind the tool assembly"
    assert answered_at < count["done"]
    # The toolkit's tools are counted, as before.
    assert count["body"]["count"] >= 2


def _gmail_chat(studio, monkeypatch, client_class) -> str:
    import omniharness.tools.connector_tools as connector_tools

    client = studio.client
    repo = client.app.state.composio_connection_repo
    client.portal.call(lambda: repo.upsert(user_id=studio.user_id, toolkit="GMAIL", composio_connection_id="ca-GMAIL", status="active"))

    async def active(user_id, toolkits):
        return {"GMAIL": "ca-GMAIL"} if "GMAIL" in toolkits else {}

    monkeypatch.setenv("COMPOSIO_API_KEY", "test-key")
    monkeypatch.setattr(connector_tools, "_active_accounts_for_user", active)
    monkeypatch.setattr("langchain_mcp_adapters.client.MultiServerMCPClient", client_class)
    return client.post("/api/threads", json={}).json()["thread_id"]


def test_page_opens_asking_at_once_share_one_assembly(studio, monkeypatch) -> None:
    """Five tabs opening the chat while its toolkits load start them once, not
    five times (every assembly starts a process per toolkit)."""
    started: list[str] = []
    base = _slow_client(["send_email", "fetch_emails"])

    class Counting(base):
        async def get_tools(self):
            started.append(self.server)
            return await super().get_tools()

    tid = _gmail_chat(studio, monkeypatch, Counting)
    answers: list[dict] = []

    def ask() -> None:
        answers.append(studio.client.get(f"/api/threads/{tid}/tools/count").json())

    askers = [threading.Thread(target=ask) for _ in range(5)]
    for t in askers:
        t.start()
        time.sleep(0.05)
    for t in askers:
        t.join(30)
    assert len(answers) == 5 and len({a["count"] for a in answers}) == 1, answers
    assert started == ["connector-gmail"], started
    # Nothing is kept once answered: the next ask loads again (a disconnect
    # or a grant change takes effect at once).
    studio.client.get(f"/api/threads/{tid}/tools/count")
    assert started == ["connector-gmail", "connector-gmail"]


def test_a_toolkit_that_does_not_answer_in_time_is_named_in_the_count(studio, monkeypatch) -> None:
    import omniharness.tools.connector_tools as connector_tools

    class Hanging:
        def __init__(self, connections, tool_name_prefix=False):
            pass

        async def get_tools(self):
            await asyncio.sleep(30)

    monkeypatch.setenv(connector_tools.TOOLKIT_LOAD_TIMEOUT_ENV, "0.5")
    tid = _gmail_chat(studio, monkeypatch, Hanging)
    body = studio.client.get(f"/api/threads/{tid}/tools/count").json()
    assert body["not_loaded"] == [{"toolkit": "GMAIL", "name": "Gmail", "reason": "timed_out"}], body
