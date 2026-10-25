"""A confirmed delegation runs its subagent, posts its result, and the confirm
request returns promptly (eval E-1); one card per proposal (eval E-2).

E-1, as observed on an isolated gateway: the lead's `task` call became a card,
the card was confirmed, the subagent logged "starting async execution" and
then made NO model call until it timed out 900 s later, while
`POST /api/confirmations/{id}/confirm` held the request open the whole time.

Two causes, each tested here through `create_app()` and the real `task` tool,
`SubagentExecutor` and confirmation route:

- The model: ChatOpenAI's default async HTTP client is ONE process-wide
  client. The lead's calls (the server's loop) left connections in its pool,
  and the subagent's first call (the isolated subagent loop) reused one that
  belongs to another loop: it failed and was retried (the request sent twice,
  the first answer dropped), or waited on an event only the other loop sets,
  forever. These tests use the REAL ChatOpenAI, scripted by a local
  OpenAI-compatible server, so the HTTP client is the production one.
- The route: it waited for the whole subagent run.

E-2: the lead, told "please confirm", re-issued the same delegation again and
again in one turn (eight open cards). The same call in the same turn while its
card is open makes no new card.
"""

from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from test_delegated_confirmation import (  # noqa: F401 - `gateway` is a fixture
    DELEGATE,
    EXAMPLE,
    _eventually,
    _pending,
    _say,
    _thread,
    _thread_messages,
    _wire,
    gateway,
)

# ---------------------------------------------------------------------------
# A scripted OpenAI-compatible server
# ---------------------------------------------------------------------------

#: Replies, in order, for the lead (its requests offer the `task` tool) and
#: for the subagent (they do not).
LEAD: list[dict] = []
SUB: list[dict] = []
#: Every request: (who, client port). The port shows which connection served it.
REQUESTS: list[tuple[str, int]] = []
#: Set: the subagent's request waits here until released.
SUB_HOLD: dict[str, threading.Event] = {}
SECOND = "A SECOND REQUEST: the first was sent and its answer dropped."


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args) -> None:
        pass

    def do_POST(self) -> None:  # noqa: N802 - http.server's name
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        names = [t["function"]["name"] for t in body.get("tools") or []]
        who = "lead" if "task" in names else "sub"
        REQUESTS.append((who, self.client_address[1]))
        if who == "sub" and "release" in SUB_HOLD:
            SUB_HOLD["entered"].set()
            SUB_HOLD["release"].wait(30)
        queue = LEAD if who == "lead" else SUB
        message = queue.pop(0) if queue else {"content": SECOND}
        out = json.dumps(
            {
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 1,
                "model": "scripted",
                "choices": [{"index": 0, "message": {"role": "assistant", **message}, "finish_reason": "tool_calls" if message.get("tool_calls") else "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


def _delegation_call() -> dict:
    return {"content": "", "tool_calls": [{"id": "d1", "type": "function", "function": {"name": "task", "arguments": json.dumps(DELEGATE["args"])}}]}


@pytest.fixture
def openai_gateway(tmp_path, monkeypatch):
    """The production composition with the REAL ChatOpenAI for lead and
    subagent, pointed at the scripted server."""
    import contextlib

    import app.gateway.deps as deps
    from app.gateway.app import create_app
    from app.gateway.auth.config import AuthConfig, set_auth_config
    from omniharness.config.app_config import reset_app_config
    from omniharness.config.extensions_config import reset_extensions_config
    from omniharness.models import create_chat_model

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    LEAD.clear()
    SUB.clear()
    REQUESTS.clear()
    SUB_HOLD.clear()

    config = yaml.safe_load(EXAMPLE.read_text())
    for model in config["models"]:
        model["base_url"] = f"http://127.0.0.1:{server.server_address[1]}/v1"
        model["api_key"] = "placeholder-not-a-real-key"
    config["database"] = {"backend": "sqlite", "sqlite_dir": str(tmp_path / "data")}
    config["policy"] = {"enabled": True, "state_dir": str(tmp_path / "policy")}
    config["trigger_engine"] = {"enabled": False}
    for feature in ("memory", "title", "summarization"):
        config.setdefault(feature, {})["enabled"] = False
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(config))
    (tmp_path / "extensions.json").write_text('{"mcpServers": {}, "skills": {}}')
    monkeypatch.setenv("OMNI_HARNESS_CONFIG_PATH", str(tmp_path / "config.yaml"))
    monkeypatch.setenv("OMNI_HARNESS_EXTENSIONS_CONFIG_PATH", str(tmp_path / "extensions.json"))
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    reset_app_config()
    reset_extensions_config()
    set_auth_config(AuthConfig(jwt_secret=os.environ["AUTH_JWT_SECRET"]))

    # The real executor and task tool, the fixed tool list; then the REAL
    # model factory back in place of the fakes.
    _wire(monkeypatch)
    import sys

    monkeypatch.setattr("omniharness.agents.lead_agent.agent.create_chat_model", create_chat_model)
    monkeypatch.setattr(sys.modules["omniharness.subagents.executor"], "create_chat_model", create_chat_model)
    monkeypatch.setattr(deps, "_cached_local_provider", None)
    monkeypatch.setattr(deps, "_cached_repo", None)

    with contextlib.ExitStack() as stack:
        client = stack.enter_context(TestClient(create_app()))
        resp = client.post("/api/v1/auth/initialize", json={"email": "owner@example.com", "password": "Str0ng!Pass99"})
        assert resp.status_code in (200, 201), resp.text
        if client.cookies.get("csrf_token"):
            client.headers["X-CSRF-Token"] = client.cookies.get("csrf_token")
        yield SimpleNamespace(client=client)
    server.shutdown()
    reset_app_config()
    reset_extensions_config()


def _propose_delegation(gw) -> tuple[str, dict]:
    LEAD[:] = [_delegation_call(), {"content": "A delegation is waiting for you."}]
    thread_id = _thread(gw)
    resp = gw.client.post(
        f"/api/threads/{thread_id}/runs/wait",
        json={"assistant_id": "lead_agent", "input": {"messages": [{"role": "user", "content": "ask a helper to wipe the nightly backup"}]}, "context": {"subagent_enabled": True}},
    )
    assert resp.status_code == 200, resp.text
    [action] = _pending(gw, "task")
    assert [who for who, _ in REQUESTS] == ["lead", "lead"], REQUESTS
    return thread_id, action


def _confirm_in_background(gw, action_id: str) -> tuple[threading.Thread, dict]:
    box: dict = {}

    def press() -> None:
        started = time.monotonic()
        box["response"] = gw.client.post(f"/api/confirmations/{action_id}/confirm", json={})
        box["seconds"] = time.monotonic() - started

    worker = threading.Thread(target=press, daemon=True)
    worker.start()
    return worker, box


def _report(gw, thread_id: str, action_id: str) -> dict | None:
    return next((m for m in _thread_messages(gw, thread_id) if m.get("id") == f"confirmation-{action_id}"), None)


# ---------------------------------------------------------------------------
# E-1: the confirmed delegation runs its subagent
# ---------------------------------------------------------------------------


def test_a_confirmed_task_runs_its_subagent_once_and_posts_its_result(openai_gateway) -> None:
    gw = openai_gateway
    thread_id, action = _propose_delegation(gw)
    SUB[:] = [{"content": "Nothing to wipe today."}]

    worker, box = _confirm_in_background(gw, action["id"])
    worker.join(60)
    assert "response" in box, "the confirm request never returned"
    body = box["response"].json()
    assert body["outcome"] == "executed", body

    subagent = [port for who, port in REQUESTS if who == "sub"]
    assert len(subagent) == 1, f"the subagent's model was asked {len(subagent)} times (a request on another loop's connection fails and is retried): {REQUESTS}"
    lead_ports = {port for who, port in REQUESTS if who == "lead"}
    assert subagent[0] not in lead_ports, "the subagent reused a connection the lead opened on another event loop"
    assert "Nothing to wipe today." in str(body["detail"].get("result")), body
    assert SECOND not in str(body), body

    report = _report(gw, thread_id, action["id"])
    assert report is not None, "the result was not posted in the chat"
    assert "Nothing to wipe today." in report["content"], report["content"]


def test_the_confirm_request_returns_while_the_subagent_is_still_working(openai_gateway, monkeypatch) -> None:
    import app.gateway.routers.confirmations as confirmations

    monkeypatch.setattr(confirmations, "CONFIRM_REPLY_WAIT_SECONDS", 0.5)
    gw = openai_gateway
    thread_id, action = _propose_delegation(gw)
    SUB[:] = [{"content": "The backup is wiped."}]
    SUB_HOLD.update(entered=threading.Event(), release=threading.Event())

    worker, box = _confirm_in_background(gw, action["id"])
    try:
        assert SUB_HOLD["entered"].wait(30), "the subagent never called its model"
        worker.join(15)
        assert "response" in box, "the confirm request waited for the whole subagent run"
        body = box["response"].json()
        assert body["outcome"] == "running", body
        assert "posted in this chat when it finishes" in body["message"], body
        assert _report(gw, thread_id, action["id"]) is None, "a result was posted before the subagent finished"
    finally:
        SUB_HOLD["release"].set()

    assert _eventually(lambda: _report(gw, thread_id, action["id"]) is not None, 30), "the result was never posted in the chat"
    assert "The backup is wiped." in _report(gw, thread_id, action["id"])["content"]
    assert _pending(gw, "task") == [], "the confirmed card is still open"
    assert [who for who, _ in REQUESTS].count("sub") == 1, REQUESTS


# ---------------------------------------------------------------------------
# E-2: one card per proposal
# ---------------------------------------------------------------------------

OTHER = {**DELEGATE, "args": {**DELEGATE["args"], "prompt": "Wipe the backup named weekly."}}


def _tool_results(messages: list[dict]) -> list[str]:
    return [str(m.get("content")) for m in messages if m.get("type") == "tool"]


def test_the_same_delegation_reissued_in_one_turn_makes_one_card(gateway) -> None:  # noqa: F811
    thread_id = _thread(gateway)
    messages = _say(
        gateway,
        thread_id,
        "ask a helper to wipe the nightly backup",
        [
            AIMessage(content="", tool_calls=[{**DELEGATE, "id": "d1"}]),
            AIMessage(content="", tool_calls=[{**DELEGATE, "id": "d2"}]),
            # The same arguments in another key order are the same proposal.
            AIMessage(content="", tool_calls=[{**DELEGATE, "args": dict(reversed(list(DELEGATE["args"].items()))), "id": "d3"}]),
            AIMessage(content="It is waiting for you."),
        ],
    )
    [card] = _pending(gateway, "task")
    results = _tool_results(messages)
    assert len(results) == 3, results
    assert "Before I do this, please confirm" in results[0]
    for repeated in results[1:]:
        assert repeated.startswith("Not proposed again") and card["id"] in repeated and "Do not propose it again" in repeated, repeated


def test_the_same_delegation_twice_in_one_step_makes_one_card(gateway) -> None:  # noqa: F811
    thread_id = _thread(gateway)
    _say(
        gateway,
        thread_id,
        "ask a helper to wipe the nightly backup",
        [AIMessage(content="", tool_calls=[{**DELEGATE, "id": "p1"}, {**DELEGATE, "id": "p2"}]), AIMessage(content="Waiting.")],
    )
    assert len(_pending(gateway, "task")) == 1


def test_different_delegations_in_one_turn_each_get_a_card(gateway) -> None:  # noqa: F811
    thread_id = _thread(gateway)
    _say(
        gateway,
        thread_id,
        "ask helpers to wipe the nightly and the weekly backups",
        [AIMessage(content="", tool_calls=[{**DELEGATE, "id": "d1"}]), AIMessage(content="", tool_calls=[{**OTHER, "id": "d2"}]), AIMessage(content="Two are waiting.")],
    )
    assert sorted(a["arguments_display"]["prompt"] for a in _pending(gateway, "task")) == ["Wipe the backup named nightly.", "Wipe the backup named weekly."]


def test_the_same_delegation_in_a_later_turn_is_a_new_proposal(gateway) -> None:  # noqa: F811
    """Only a repeat within the turn is collapsed: asked again in a new turn,
    the person sees a card for that turn too (the earlier one may be stale)."""
    thread_id = _thread(gateway)
    _say(gateway, thread_id, "ask a helper to wipe the nightly backup", [AIMessage(content="", tool_calls=[{**DELEGATE, "id": "d1"}]), AIMessage(content="Waiting.")])
    _say(gateway, thread_id, "please, ask a helper to wipe the nightly backup", [AIMessage(content="", tool_calls=[{**DELEGATE, "id": "d2"}]), AIMessage(content="Waiting.")])
    assert len(_pending(gateway, "task")) == 2


def test_a_repeat_after_the_card_was_answered_is_a_new_proposal(gateway) -> None:  # noqa: F811
    thread_id = _thread(gateway)
    _say(gateway, thread_id, "ask a helper to wipe the nightly backup", [AIMessage(content="", tool_calls=[{**DELEGATE, "id": "d1"}]), AIMessage(content="Waiting.")])
    [first] = _pending(gateway, "task")
    assert gateway.client.post(f"/api/confirmations/{first['id']}/decline", json={}).json()["outcome"] == "declined"
    _say(gateway, thread_id, "ok, ask a helper to wipe the nightly backup", [AIMessage(content="", tool_calls=[{**DELEGATE, "id": "d2"}]), AIMessage(content="Waiting.")])
    [second] = _pending(gateway, "task")
    assert second["id"] != first["id"]
