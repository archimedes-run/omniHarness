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

import asyncio
import importlib
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
# E-2: one open card per tool, per agent, per turn
# ---------------------------------------------------------------------------

#: The eval's shape: the lead re-issued its delegation, rephrased, with a
#: different max_turns each time, and split it into other delegations.
REPHRASED = [
    ("Best months to visit Lisbon", "Find the best months to visit Lisbon.", 10),
    ("Best months to visit Lisbon", "Research the best months to visit Lisbon, with weather and crowds.", 12),
    ("Lisbon transport passes & prices", "Find Lisbon transport passes and their prices.", 16),
    ("Top 3 day trips from Lisbon", "Pick the top 3 day trips from Lisbon.", 14),
    ("Best months to visit Lisbon", "What are the best months to visit Lisbon? Weather, crowds, prices.", 12),
    ("Lisbon transport passes & prices", "Compare Viva Viagem, Lisboa Card and day passes.", 16),
    ("Top 3 day trips from Lisbon", "Pick the top 3 day trips from Lisbon.", 14),
]


def _delegation(index: int) -> dict:
    description, prompt, turns = REPHRASED[index]
    return {"name": "task", "args": {"description": description, "prompt": prompt, "subagent_type": "general-purpose", "max_turns": turns}, "id": f"t{index}"}


def _tool_results(messages: list[dict]) -> list[str]:
    return [str(m.get("content")) for m in messages if m.get("type") == "tool"]


def _with_lead_tier3_tool(monkeypatch) -> None:
    """The lead also gets wipe_backup (Tier 3 in the fixture's rules)."""
    from test_delegated_confirmation import wipe_backup

    import omniharness.tools as tools

    real = tools.get_available_tools

    def available(**kwargs):
        listed = real(**kwargs)
        return [*listed, wipe_backup] if kwargs.get("subagent_enabled") else listed

    monkeypatch.setattr("omniharness.tools.get_available_tools", available)


def test_seven_rephrased_delegations_in_one_turn_make_one_card(gateway) -> None:  # noqa: F811
    """Eval E-2, as it happened: one at a time, then three in one step."""
    thread_id = _thread(gateway)
    steps = [
        AIMessage(content="", tool_calls=[_delegation(0)]),
        AIMessage(content="", tool_calls=[_delegation(1), _delegation(2), _delegation(3)]),
        AIMessage(content="", tool_calls=[_delegation(4)]),
        AIMessage(content="", tool_calls=[_delegation(5), _delegation(6)]),
        AIMessage(content="One is waiting for you."),
    ]
    messages = _say(gateway, thread_id, "plan a long weekend in Lisbon", steps)
    [card] = _pending(gateway, "task")
    assert card["arguments_display"]["prompt"] == REPHRASED[0][1]
    results = _tool_results(messages)
    assert len(results) == 7, results
    assert "Before I do this, please confirm" in results[0]
    for held in results[1:]:
        assert held.startswith("Not proposed: a card for task") and card["id"] in held, held
        assert "Do not propose task again in this turn; end your turn now" in held, held


def test_a_different_tool_in_the_same_turn_still_gets_a_card(gateway, monkeypatch) -> None:  # noqa: F811
    _with_lead_tier3_tool(monkeypatch)
    thread_id = _thread(gateway)
    wipe = {"name": "wipe_backup", "args": {"name": "nightly"}, "id": "w1"}
    _say(gateway, thread_id, "wipe the nightly backup and ask a helper to check", [AIMessage(content="", tool_calls=[_delegation(0)]), AIMessage(content="", tool_calls=[wipe]), AIMessage(content="Two are waiting.")])
    assert len(_pending(gateway, "task")) == 1 and len(_pending(gateway, "wipe_backup")) == 1


def test_another_tool_is_held_only_on_an_exact_repeat(gateway, monkeypatch) -> None:  # noqa: F811
    """Several different calls of one tool in a turn are several cards (two
    backups, two emails, a group of ledger suggestions); only the same call
    again is held."""
    _with_lead_tier3_tool(monkeypatch)
    thread_id = _thread(gateway)
    nightly = {"name": "wipe_backup", "args": {"name": "nightly"}, "id": "w1"}
    weekly = {"name": "wipe_backup", "args": {"name": "weekly"}, "id": "w2"}
    messages = _say(
        gateway,
        thread_id,
        "wipe the nightly and the weekly backups",
        [AIMessage(content="", tool_calls=[nightly, weekly]), AIMessage(content="", tool_calls=[{**nightly, "id": "w3"}]), AIMessage(content="Two are waiting.")],
    )
    cards = _pending(gateway, "wipe_backup")
    assert sorted(c["arguments_display"]["name"] for c in cards) == ["nightly", "weekly"]
    held = _tool_results(messages)[2]
    assert held.startswith("Not proposed: a card for wipe_backup") and "end your turn now" in held, held


def test_the_same_tool_in_a_later_turn_is_a_new_proposal(gateway) -> None:  # noqa: F811
    """Only the turn's own repeats are held: asked again in a new turn, the
    person sees a card for that turn too."""
    thread_id = _thread(gateway)
    _say(gateway, thread_id, "ask a helper about Lisbon", [AIMessage(content="", tool_calls=[_delegation(0)]), AIMessage(content="Waiting.")])
    _say(gateway, thread_id, "now also look into the Lisbon transport passes and what they cost", [AIMessage(content="", tool_calls=[_delegation(2)]), AIMessage(content="Waiting.")])
    assert len(_pending(gateway, "task")) == 2


def test_after_the_open_card_is_declined_the_tool_can_be_proposed_again(gateway) -> None:  # noqa: F811
    thread_id = _thread(gateway)
    _say(gateway, thread_id, "ask a helper about Lisbon", [AIMessage(content="", tool_calls=[_delegation(0)]), AIMessage(content="Waiting.")])
    [first] = _pending(gateway, "task")
    assert gateway.client.post(f"/api/confirmations/{first['id']}/decline", json={}).json()["outcome"] == "declined"
    _say(gateway, thread_id, "ok, just the transport passes then", [AIMessage(content="", tool_calls=[_delegation(2)]), AIMessage(content="Waiting.")])
    [second] = _pending(gateway, "task")
    assert second["id"] != first["id"]


def test_after_the_open_card_expires_the_tool_can_be_proposed_again_in_the_turn(gateway, monkeypatch) -> None:  # noqa: F811
    """Within ONE turn: an open card that expired no longer holds the tool
    (a confirmed or declined one is resolved the same way; a card cannot be
    pressed while its chat is replying). Expired through the store the
    gateway reads, between two tool calls of the same run."""
    from datetime import UTC, datetime, timedelta

    import test_delegated_confirmation as delegated

    from app.policy.pending import PendingStore

    store = PendingStore(directory=delegated_policy_dir() / "pending")
    seen: dict[str, int] = {}

    class Expiring(delegated.HeldLeadFake):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            # Before the second proposal: the first card has expired.
            if sum(1 for m in messages if getattr(m, "type", "") == "tool") == 1:
                for action in store.open_actions(datetime.now(UTC)):
                    action.expires_at = datetime.now(UTC) - timedelta(seconds=1)
                    store.save(action)
                    seen["expired"] = seen.get("expired", 0) + 1
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    monkeypatch.setattr("omniharness.agents.lead_agent.agent.create_chat_model", lambda **_: Expiring(messages=iter(list(delegated.LEAD_SCRIPT))))
    thread_id = _thread(gateway)
    messages = _say(gateway, thread_id, "ask a helper about Lisbon", [AIMessage(content="", tool_calls=[_delegation(0)]), AIMessage(content="", tool_calls=[_delegation(2)]), AIMessage(content="Waiting.")])
    assert seen.get("expired") == 1
    [card] = _pending(gateway, "task")
    assert card["arguments_display"]["prompt"] == REPHRASED[2][1], "the tool stayed held after its card expired"
    assert "Before I do this, please confirm" in _tool_results(messages)[1]


def delegated_policy_dir():
    from pathlib import Path

    from omniharness.config import get_app_config

    return Path(get_app_config().policy.state_dir)


# ---------------------------------------------------------------------------
# A failure after the card said "running" is told in the chat
# ---------------------------------------------------------------------------


def _failing_task_tools(monkeypatch, hold: tuple[threading.Event, threading.Event] | None) -> None:
    """The confirmed `task` raises after its claim (building its subagent's
    tools fails), optionally once released."""
    task_tool = importlib.import_module("omniharness.tools.builtins.task_tool")

    def broken(**_kwargs):
        if hold is not None:
            entered, release = hold
            entered.set()
            assert release.wait(30)
        raise RuntimeError("the tool sources could not be loaded")

    monkeypatch.setattr(task_tool, "subagent_base_tools", broken)


def _delegation_card(gw) -> tuple[str, dict]:
    thread_id = _thread(gw)
    _say(gw, thread_id, "ask a helper to wipe the nightly backup", [AIMessage(content="", tool_calls=[DELEGATE]), AIMessage(content="Waiting.")])
    [card] = _pending(gw, "task")
    return thread_id, card


def test_a_failure_after_running_is_posted_in_the_chat(gateway, monkeypatch) -> None:  # noqa: F811
    import app.gateway.routers.confirmations as confirmations

    monkeypatch.setattr(confirmations, "CONFIRM_REPLY_WAIT_SECONDS", 0.3)
    thread_id, card = _delegation_card(gateway)
    entered, release = threading.Event(), threading.Event()
    _failing_task_tools(monkeypatch, (entered, release))
    worker, box = _confirm_in_background(gateway, card["id"])
    try:
        assert entered.wait(30), "the confirmed call never started"
        worker.join(15)
        assert "response" in box, "the confirm request waited for the delegation"
        assert box["response"].json()["outcome"] == "running", box["response"].json()
    finally:
        release.set()

    assert _eventually(lambda: _report(gateway, thread_id, card["id"]) is not None, 30), "the failure was never told in the chat"
    posted = _report(gateway, thread_id, card["id"])
    assert "I could not complete **task** after you confirmed it" in posted["content"], posted["content"]
    assert "the tool sources could not be loaded" in posted["content"], posted["content"]
    assert posted["additional_kwargs"]["confirmation"]["outcome"] == "failed"
    assert posted["additional_kwargs"]["confirmation"]["continue_agent"] is None


def test_a_failure_the_card_shows_is_not_also_posted(gateway, monkeypatch) -> None:  # noqa: F811
    """A delegation that fails before the wait runs out answers on the card."""
    thread_id, card = _delegation_card(gateway)
    _failing_task_tools(monkeypatch, None)
    assert gateway.client.post(f"/api/confirmations/{card['id']}/confirm", json={}).json()["outcome"] == "failed"
    assert _report(gateway, thread_id, card["id"]) is None


def test_a_slow_call_that_is_not_a_delegation_is_waited_for_and_keeps_continue(gateway, monkeypatch) -> None:  # noqa: F811
    """Only a delegation answers RUNNING: a subagent's own slow call is
    waited for, so its card still gets Continue <agent>, as on main."""
    import test_delegated_confirmation as delegated
    from test_delegated_confirmation import _user_delegates_and_subagent_proposes

    import app.gateway.routers.confirmations as confirmations

    monkeypatch.setattr(confirmations, "CONFIRM_REPLY_WAIT_SECONDS", 0.3)
    _thread_id, wipe = _user_delegates_and_subagent_proposes(gateway)
    entered, release = threading.Event(), threading.Event()
    delegated.HOLD["wipe"] = (entered, release)
    worker, box = _confirm_in_background(gateway, wipe["id"])
    try:
        assert entered.wait(30)
        worker.join(1.5)
        assert "response" not in box, "a non-delegation answered before its call finished"
    finally:
        release.set()
    worker.join(30)
    body = box["response"].json()
    assert body["outcome"] == "executed", body
    assert body["detail"]["continue_agent"] == "general-purpose", body


def test_a_failure_while_the_card_waits_on_the_rest_is_answered_not_lost(gateway, monkeypatch) -> None:  # noqa: F811
    """The flow failed just before the wait ran out, and the rest (the
    resume check) is still running: the card answers the failure, never
    RUNNING with the failure left unsaid."""
    import app.gateway.resume as resume
    import app.gateway.routers.confirmations as confirmations

    monkeypatch.setattr(confirmations, "CONFIRM_REPLY_WAIT_SECONDS", 0.3)
    real = resume.resume_after_confirm

    async def slow(*args, **kwargs):
        # A loop timer, not asyncio.sleep (the fixture shortens that).
        loop = asyncio.get_running_loop()
        later = loop.create_future()
        loop.call_later(1.5, later.set_result, None)
        await later
        return await real(*args, **kwargs)

    monkeypatch.setattr(resume, "resume_after_confirm", slow)
    _thread_id, card = _delegation_card(gateway)
    _failing_task_tools(monkeypatch, None)
    body = gateway.client.post(f"/api/confirmations/{card['id']}/confirm", json={}).json()
    assert body["outcome"] == "failed", body
