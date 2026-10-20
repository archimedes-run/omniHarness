"""Every automation run lands in the run history, through `build_loop` (the
production builder) and a full TriggerLoop.cycle(): the prompt, the tool call,
the tool result (redacted) and the reply. A failed run is recorded too."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.gateway.trigger_engine_wiring import build_loop
from app.run_history.recorder import AUTOMATION, automation_recorder
from app.run_history.store import RunHistory

GITHUB = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4"


def on_disk(root):
    return b"".join(p.read_bytes() for p in root.rglob("*") if p.is_file())


pytestmark = pytest.mark.asyncio


class _Gateway:
    def __init__(self, *, fail: bool = False):
        self.fail = fail

    def post(self, path, body):
        if path == "/api/threads":
            return {"thread_id": "t-1"}
        if self.fail:
            raise RuntimeError("model timeout")
        prompt = body["input"]["messages"][0]["content"]
        return {
            "messages": [
                {"type": "human", "content": "an earlier turn"},
                {"type": "ai", "content": "an earlier reply"},
                {"type": "human", "content": prompt},
                {"type": "ai", "content": "", "tool_calls": [{"name": "gmail_fetch", "args": {"q": "is:unread"}}]},
                {"type": "tool", "name": "gmail_fetch", "content": f"reset your token {GITHUB} now"},
                {"type": "ai", "content": "One mail asks you to reset a token."},
            ]
        }

    def put(self, path, body):
        return {"sources": body.get("sources", [])}

    def get(self, path):
        return {"status": "idle"}


def _loop(tmp_path, gateway, history):
    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps({"quiet_hours": {"enabled": False}, "rules": [{"id": "inbox", "type": "cron", "match": {"schedule": "* * * * *"}, "prompt": "Summarise my inbox.", "destination": "quiet"}]}))
    cfg = SimpleNamespace(trigger_engine=SimpleNamespace(rules_path=str(rules), state_dir=str(tmp_path / "state"), actor="default", tick_seconds=30.0))
    return build_loop(
        cfg,
        gateway_post=gateway.post,
        gateway_put=gateway.put,
        gateway_get=gateway.get,
        fetch_sessions=lambda: {"observable": True, "sessions": []},
        exchange_state=lambda tid: {"status": "idle"},
        remote=None,
        record_run=automation_recorder(history),
    )


async def test_a_run_is_recorded_whole_and_redacted(tmp_path) -> None:
    history = RunHistory(tmp_path / "history")
    loop = _loop(tmp_path, _Gateway(), history)

    await loop.cycle()

    runs = history.list(kind=AUTOMATION, source_id="inbox")
    assert len(runs) == 1 and runs[0].status == "completed" and runs[0].thread_id == "t-1"
    body = history.get(runs[0].id)["body"]
    kinds = [m["type"] for m in body["messages"]]
    assert kinds == ["human", "ai", "tool", "ai"], "not exactly this turn's messages"
    assert body["prompt"] == "Summarise my inbox." and body["reply"] == "One mail asks you to reset a token."
    assert body["messages"][1]["tool_calls"][0]["name"] == "gmail_fetch"
    assert GITHUB.encode() not in on_disk(tmp_path / "history"), "the token reached the disk"


async def test_a_failed_run_is_recorded_with_its_reason(tmp_path) -> None:
    history = RunHistory(tmp_path / "history")
    loop = _loop(tmp_path, _Gateway(fail=True), history)

    await loop.cycle()

    (run,) = history.list(kind=AUTOMATION, source_id="inbox")
    assert run.status == "failed" and "model timeout" in (run.error or "")


async def test_the_production_loop_records_into_the_history_it_is_given(tmp_path, monkeypatch) -> None:
    """build_production_loop is what the gateway lifespan calls; it must hand
    the engine a recorder bound to the history, not drop it."""
    from app.gateway.trigger_engine_wiring import build_production_loop

    empty = tmp_path / "ext.json"
    empty.write_text('{"mcpServers": {}, "skills": {}}')
    monkeypatch.setenv("OMNI_HARNESS_EXTENSIONS_CONFIG_PATH", str(empty))
    from omniharness.config.extensions_config import reset_extensions_config

    reset_extensions_config()
    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps({"rules": [{"id": "inbox", "type": "cron", "match": {"schedule": "0 9 * * *"}, "prompt": "p", "destination": "quiet"}]}))
    cfg = SimpleNamespace(trigger_engine=SimpleNamespace(rules_path=str(rules), state_dir=str(tmp_path / "state"), actor="default", tick_seconds=30.0, remote=None), channels={})
    history = RunHistory(tmp_path / "history")

    loop = build_production_loop(cfg, run_store=None, run_history=history)

    loop.runner.record_run({"rule_id": "inbox", "status": "completed", "body": {"reply": "hi"}})
    assert [r.source_id for r in history.list(kind=AUTOMATION)] == ["inbox"]
    reset_extensions_config()
