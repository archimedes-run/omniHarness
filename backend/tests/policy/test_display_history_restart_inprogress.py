"""The chat's display history after a gateway restart and during a run
(dogfooding, 2026-10-25).

PR #150 made the chat read what the person said and was shown from each run's
journal (`/api/threads/{id}/runs/{run_id}/messages`), every page of every run,
while the model's context stays summarized. Two holes were left:

D1-f  After a gateway restart the person's older messages vanished again in a
      summarized chat. The runs list (`GET /api/threads/{id}/runs`) read only
      the runs THIS process held in memory, so after a restart (or on another
      worker, or once a record was cleaned up) the chat got no runs and fell
      back to the summarized thread state.
D1-g  While a run was still going, a reload hid the person's message of that
      run. Its journal was empty until the run ended: the journal is a
      LangChain callback handler, LangChain calls a sync handler on executor
      threads under an async run, and a flush from a thread with no running
      loop was skipped, so every event waited for the worker's final flush.

Through the production composition (`create_app()` with its lifespan, the
gateway's SQLite run and event stores, the run routes and worker,
`make_lead_agent` with the production summarization middleware); only the
chat models are scripted. A restart is the app shut down and a NEW
`create_app()` on the same database.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from types import SimpleNamespace

import pytest
import test_summary_display_and_links as summ
import test_web_research as research
import yaml
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

FIRST = "find 5 great date-night restaurants in Philly with links"
SECOND = "now find 3 brunch spots too"
CREDENTIALS = {"email": "owner@example.com", "password": "Str0ng!Pass99"}


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    """test_web_research's production gateway, restartable on the same data."""
    from app.gateway.auth.config import AuthConfig, set_auth_config
    from omniharness.config.app_config import reset_app_config
    from omniharness.config.extensions_config import reset_extensions_config

    config = yaml.safe_load(research.EXAMPLE.read_text())
    config["database"] = {"backend": "sqlite", "sqlite_dir": str(tmp_path / "data")}
    (tmp_path / "rules.yaml").write_text(research.RULES.read_text())
    config["policy"] = {"enabled": True, "state_dir": str(tmp_path / "policy"), "rules_path": str(tmp_path / "rules.yaml")}
    config["trigger_engine"] = {"enabled": False}
    config.setdefault("memory", {})["enabled"] = False
    config.setdefault("title", {})["enabled"] = False
    config.setdefault("summarization", {})["enabled"] = False
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config))
    extensions = tmp_path / "extensions.json"
    extensions.write_text('{"mcpServers": {}, "skills": {}}')
    monkeypatch.setenv("OMNI_HARNESS_CONFIG_PATH", str(path))
    monkeypatch.setenv("OMNI_HARNESS_EXTENSIONS_CONFIG_PATH", str(extensions))
    monkeypatch.chdir(tmp_path)
    reset_app_config()
    reset_extensions_config()
    set_auth_config(AuthConfig(jwt_secret=os.environ["AUTH_JWT_SECRET"]))
    for bucket in (research.SENT, research.RAN, research.LEAD_SAW, research.LEAD_SCRIPT, research.SUB_SCRIPT):
        bucket.clear()
    research._wire(monkeypatch)

    holder = SimpleNamespace(client=None, app=None, stack=None)

    def start(first: bool) -> None:
        import app.gateway.deps as deps
        from app.gateway.app import create_app

        monkeypatch.setattr(deps, "_cached_local_provider", None)
        monkeypatch.setattr(deps, "_cached_repo", None)
        stack = contextlib.ExitStack()
        app = create_app()
        client = stack.enter_context(TestClient(app))
        if first:
            resp = client.post("/api/v1/auth/initialize", json=CREDENTIALS)
            assert resp.status_code in (200, 201), resp.text
        else:
            resp = client.post("/api/v1/auth/login/local", data={"username": CREDENTIALS["email"], "password": CREDENTIALS["password"]})
            assert resp.status_code == 200, resp.text
        csrf = client.cookies.get("csrf_token")
        if csrf:
            client.headers["X-CSRF-Token"] = csrf
        holder.client, holder.app, holder.stack = client, app, stack

    def restart() -> None:
        holder.stack.close()
        start(first=False)

    start(first=True)
    holder.restart = restart
    yield holder
    holder.stack.close()
    reset_app_config()
    reset_extensions_config()


def _two_summarized_turns(gw, monkeypatch) -> str:
    """Two research turns; the second's first model call is the summarizer's,
    so the first message is no longer in the thread state."""
    summ._summarize_early(monkeypatch)
    thread_id = research._thread(gw)
    summ._stream(gw, thread_id, FIRST, summ._research())
    summ._stream(gw, thread_id, SECOND, summ._research())
    assert summ.SUMMARIES, "the chat was never summarized; this test proves nothing"
    assert FIRST not in json.dumps(research._messages(gw, thread_id)), "the first message is still in the model's context; this test proves nothing"
    return thread_id


# -- D1-f: after a restart ------------------------------------------------------


def test_after_a_restart_the_runs_and_the_display_history_keep_every_message(gateway, monkeypatch):
    thread_id = _two_summarized_turns(gateway, monkeypatch)
    before = gateway.client.get(f"/api/threads/{thread_id}/runs").json()
    assert len(before) == 2
    assert summ._human_texts(summ._history(gateway, thread_id)) == [FIRST, SECOND]

    gateway.restart()

    assert gateway.client.portal.call(gateway.app.state.run_manager.list_by_thread, thread_id) == [], "the restarted gateway still holds the runs in memory; this test proves nothing"
    runs = gateway.client.get(f"/api/threads/{thread_id}/runs").json()
    # Oldest first, as the chat reads them (core/threads/hooks.ts useThreadHistory
    # starts at the LAST run and pages back).
    assert [r["run_id"] for r in runs] == [r["run_id"] for r in before]
    assert [r["status"] for r in runs] == ["success", "success"]
    assert summ._human_texts(summ._history(gateway, thread_id)) == [FIRST, SECOND]
    # The model's context is still the summary.
    assert FIRST not in json.dumps(research._messages(gateway, thread_id))


def test_the_runs_list_reads_the_store_when_this_process_holds_no_record(gateway, monkeypatch):
    """Another worker (or a record cleaned up after its run): this process's
    run manager holds nothing for the thread, the store does."""
    thread_id = _two_summarized_turns(gateway, monkeypatch)
    manager = gateway.app.state.run_manager
    for record in gateway.client.portal.call(manager.list_by_thread, thread_id):
        manager._runs.pop(record.run_id, None)
    assert gateway.client.portal.call(manager.list_by_thread, thread_id) == []
    assert summ._human_texts(summ._history(gateway, thread_id)) == [FIRST, SECOND]


# -- D1-g: during a run -----------------------------------------------------------

GATE = threading.Event()
REACHED = threading.Event()


@tool("web_fetch")
def held_fetch(url: str) -> str:
    """Fetch a page (stand-in that holds the run on one URL until the test lets go)."""
    if "hold" in url:
        REACHED.set()
        GATE.wait(30)
    return f"# Page {url}\n\nGreat brunch."


def start_held_turn(gw, monkeypatch) -> tuple[str, str]:
    """A summarized chat whose second turn is held mid-run, after the summary
    replaced the person's message in the thread state."""
    summ._summarize_early(monkeypatch)
    tools = [t for t in research.LEAD_TOOLS if t.name != "web_fetch"] + [held_fetch]
    monkeypatch.setattr("omniharness.tools.get_available_tools", lambda **_: tools)
    thread_id = research._thread(gw)
    summ._stream(gw, thread_id, FIRST, summ._research())
    GATE.clear()
    REACHED.clear()
    research.LEAD_SCRIPT[:] = [
        research._step(research._call("web_search", {"query": "brunch philly"}, "b1")),
        research._step(research._call("web_fetch", {"url": "https://brunch1.example"}, "b2")),
        research._step(research._call("web_fetch", {"url": "https://hold.example"}, "b3")),
        AIMessage(content="Brunch picks: Talula's Garden, Middle Child, Suraya."),
        *[AIMessage(content="(done)")] * 4,
    ]
    body = {
        "assistant_id": "lead_agent",
        "input": {"messages": [{"type": "human", "content": [{"type": "text", "text": SECOND}]}]},
        "stream_mode": ["values", "updates", "messages-tuple", "custom"],
        "stream_subgraphs": True,
        "on_disconnect": "continue",
        "context": {},
    }
    resp = gw.client.post(f"/api/threads/{thread_id}/runs", json=body)
    assert resp.status_code == 200, resp.text
    assert REACHED.wait(30), "the run never reached the held step"
    return thread_id, resp.json()["run_id"]


def test_a_reload_during_a_run_shows_the_persons_message_of_that_run_once(gateway, monkeypatch):
    thread_id, run_id = start_held_turn(gateway, monkeypatch)
    try:
        state = research._messages(gateway, thread_id)
        assert SECOND not in json.dumps(state), "the person's message is still in the thread state; this test proves nothing"
        runs = gateway.client.get(f"/api/threads/{thread_id}/runs").json()
        assert [r["status"] for r in runs] == ["success", "running"]
        # What a reload reads now: the journal so far, written as the run goes.
        deadline = time.time() + 5
        while True:
            texts = summ._human_texts(summ._history(gateway, thread_id))
            if texts == [FIRST, SECOND] or time.time() > deadline:
                break
            time.sleep(0.05)
        assert texts == [FIRST, SECOND], f"a reload mid-run lost the person's message of the running run: {texts}"
    finally:
        GATE.set()
    assert research._wait_run(gateway, thread_id, run_id) == "success"

    # Written as it went AND flushed at the end: every message once.
    rows = gateway.client.get(f"/api/threads/{thread_id}/runs/{run_id}/messages?limit=200").json()["data"]
    keys = [(r["content"].get("type"), r["content"].get("id") or r["content"].get("tool_call_id")) for r in rows if isinstance(r["content"], dict)]
    assert len(keys) == len(set(keys)), f"a message was journaled twice: {keys}"
    assert summ._human_texts(summ._history(gateway, thread_id)) == [FIRST, SECOND]
    assert "Talula" in json.dumps(rows), "the run's final answer is not in its journal"
