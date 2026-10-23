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
    """runs/wait returns the WHOLE thread, as the real gateway does: an earlier
    firing of the same rule (same prompt, its own tool output) comes first."""

    def __init__(self, *, fail: bool = False, no_thread_for: frozenset = frozenset(), summarised: bool = False):
        self.fail = fail
        self.no_thread_for = no_thread_for
        self.summarised = summarised

    def post(self, path, body):
        if path == "/api/threads":
            rule = body["metadata"]["trigger_rule_id"]
            if rule in self.no_thread_for:
                raise RuntimeError("thread store unavailable")
            return {"thread_id": f"t-{rule}"}
        if self.fail:
            raise RuntimeError("model timeout")
        sent = body["input"]["messages"][0]
        this_turn = [] if self.summarised else [{"type": "human", "content": sent["content"], "id": sent.get("id")}]
        return {
            "messages": [
                {"type": "human", "content": sent["content"], "id": "an-earlier-firing"},
                {"type": "tool", "name": "gmail_fetch", "content": "EARLIER-FIRING-TOOL-OUTPUT"},
                {"type": "ai", "content": "an earlier reply"},
                *this_turn,
                {"type": "ai", "content": "", "tool_calls": [{"name": "gmail_fetch", "args": {"q": "is:unread"}}]},
                {"type": "tool", "name": "gmail_fetch", "content": f"reset your token {GITHUB} now"},
                {"type": "ai", "content": "One mail asks you to reset a token."},
            ]
        }

    def put(self, path, body):
        return {"sources": body.get("sources", [])}

    def get(self, path):
        return {"status": "idle"}


def _rule(rule_id: str, prompt: str = "Summarise my inbox.") -> dict:
    return {"id": rule_id, "type": "cron", "match": {"schedule": "* * * * *"}, "prompt": prompt, "destination": "quiet"}


def _loop(tmp_path, gateway, history, rules_list=None):
    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps({"quiet_hours": {"enabled": False}, "rules": rules_list or [_rule("inbox")]}))
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
    assert len(runs) == 1 and runs[0].status == "completed" and runs[0].thread_id == "t-inbox"
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


async def test_only_this_turns_messages_are_stored(tmp_path) -> None:
    """runs/wait returns the whole thread; an earlier firing with the SAME
    prompt is not this turn. Found by the id the injector sent."""
    history = RunHistory(tmp_path / "history")
    await _loop(tmp_path, _Gateway(), history).cycle()

    (run,) = history.list(kind=AUTOMATION, source_id="inbox")
    body = history.get(run.id)["body"]
    assert body["turn_found"] is True
    assert [m["type"] for m in body["messages"]] == ["human", "ai", "tool", "ai"]
    assert "EARLIER-FIRING-TOOL-OUTPUT" not in json.dumps(body), "an earlier turn was stored as this one"


async def test_a_turn_that_cannot_be_found_stores_no_messages_and_says_so(tmp_path) -> None:
    history = RunHistory(tmp_path / "history")
    await _loop(tmp_path, _Gateway(summarised=True), history).cycle()

    (run,) = history.list(kind=AUTOMATION, source_id="inbox")
    body = history.get(run.id)["body"]
    assert body["turn_found"] is False and body["messages"] == []
    assert "EARLIER-FIRING-TOOL-OUTPUT" not in json.dumps(body), "the whole thread was stored"
    assert body["reply"] == "One mail asks you to reset a token."


async def test_a_firing_that_fails_before_injecting_records_no_earlier_messages(tmp_path) -> None:
    """Rule `a` runs and fills the injector's last turn; rule `b` fails creating
    its thread. b's record must not carry a's messages."""
    history = RunHistory(tmp_path / "history")
    loop = _loop(tmp_path, _Gateway(no_thread_for=frozenset({"b"})), history, [_rule("a", "Prompt for a."), _rule("b", "Prompt for b.")])

    await loop.cycle()

    (a,) = history.list(kind=AUTOMATION, source_id="a")
    (b,) = history.list(kind=AUTOMATION, source_id="b")
    assert history.get(a.id)["body"]["messages"], "rule a recorded nothing"
    b_body = history.get(b.id)["body"]
    assert b.status == "failed" and "thread store unavailable" in (b.error or "")
    assert b_body["messages"] == [], "rule b's record carries rule a's messages"
    assert "Prompt for a." not in json.dumps(b_body)


async def test_every_stored_message_says_where_it_came_from(tmp_path) -> None:
    """For 007 replay: the injected prompt is `trigger`, the model's output is
    `assistant`, and what a tool returned is `untrusted_tool_output`."""
    history = RunHistory(tmp_path / "history")
    await _loop(tmp_path, _Gateway(), history).cycle()

    (run,) = history.list(kind=AUTOMATION, source_id="inbox")
    body = history.get(run.id)["body"]
    assert [m["provenance"] for m in body["messages"]] == ["trigger", "assistant", "untrusted_tool_output", "assistant"]
    assert body["provenance"] == {"prompt": "trigger", "event": "untrusted_source_data", "reply": "assistant"}
