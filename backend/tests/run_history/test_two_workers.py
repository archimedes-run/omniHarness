"""Two workers over one data dir: the gateway that takes the HTTP delete, and
the worker whose trigger engine fires (built by `build_loop`, the production
builder, over the same state dir, as that worker builds it).

  * the rule-to-thread map is a file the engine re-reads before each firing:
    a delete on the other worker is never undone by its in-memory copy;
  * a firing holds a cross-process lock; a delete during one refuses (409)
    and deletes nothing.
"""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import pytest

from app.gateway.trigger_engine_wiring import build_loop


class _EngineGateway:
    def __init__(self, loop_ref: list):
        self.created = 0
        self.loop_ref = loop_ref
        self.lock_free_during_turn: list[bool] = []

    def post(self, path, body):
        if path == "/api/threads":
            self.created += 1
            return {"thread_id": f"t-{body['metadata']['trigger_rule_id']}-{self.created}"}
        # Mid-turn: is the firing lock held? (Another worker's view of it.)
        with self.loop_ref[0].threads.firing_lock(timeout=0) as free:
            self.lock_free_during_turn.append(free)
        sent = body["input"]["messages"][0]
        return {"messages": [{"type": "human", "content": sent["content"], "id": sent["id"]}, {"type": "ai", "content": "done"}]}

    def put(self, path, body):
        return {"sources": []}

    def get(self, path):
        return {"status": "idle"}


def _engine(state_dir, gateway):
    rules = state_dir.parent / "rules.json"
    rules.write_text(json.dumps({"quiet_hours": {"enabled": False}, "rules": [{"id": "inbox", "type": "cron", "match": {"schedule": "* * * * *"}, "prompt": "p", "destination": "quiet"}]}))
    cfg = SimpleNamespace(trigger_engine=SimpleNamespace(rules_path=str(rules), state_dir=str(state_dir), actor="default", tick_seconds=30.0))
    return build_loop(cfg, gateway_post=gateway.post, gateway_put=gateway.put, gateway_get=gateway.get, fetch_sessions=lambda: {"observable": True, "sessions": []}, exchange_state=lambda tid: {"status": "idle"}, remote=None)


@pytest.fixture
def two_workers(make_gateway, tmp_path):
    state = tmp_path / "triggers"

    def tweak(config: dict) -> None:
        config["trigger_engine"] = {"enabled": False, "state_dir": str(state)}

    ref: list = []
    engine_gateway = _EngineGateway(ref)
    engine = _engine(state, engine_gateway)
    ref.append(engine)
    with make_gateway(tweak) as (client, _):
        yield client, engine, engine_gateway


@pytest.mark.asyncio
async def test_a_delete_on_one_worker_is_not_undone_by_the_engine_on_another(two_workers) -> None:
    client, engine, gw = two_workers
    await engine.cycle()
    first = engine.threads.thread_for("inbox")
    assert gw.created == 1 and first == "t-inbox-1"

    resp = client.delete("/api/run-history/runs", params={"confirm": "delete-all"})
    assert resp.status_code == 200, resp.text

    # The engine worker's map instance was loaded before the delete.
    assert engine.threads.thread_for("inbox") != first, "the engine reused the deleted thread from a stale copy"
    assert gw.created == 2


@pytest.mark.asyncio
async def test_the_engine_holds_the_firing_lock_through_the_turn(two_workers) -> None:
    _, engine, gw = two_workers
    await engine.cycle()
    assert gw.lock_free_during_turn == [False], "the turn ran without the firing lock"


def test_a_delete_during_a_firing_on_another_worker_refuses(two_workers, monkeypatch) -> None:
    import app.run_history.delete as delete

    client, engine, _ = two_workers
    monkeypatch.setattr(delete, "LOCK_WAIT", 0.3)
    client.app.state.run_history.record(kind="automation", source_id="inbox", body={}, status="completed")
    held, release = threading.Event(), threading.Event()

    def firing() -> None:
        with engine.threads.firing_lock():
            held.set()
            release.wait(10)

    t = threading.Thread(target=firing)
    t.start()
    held.wait(5)
    try:
        resp = client.delete("/api/run-history/runs", params={"confirm": "delete-all"})
    finally:
        release.set()
        t.join()
    assert resp.status_code == 409, resp.text
    assert client.app.state.run_history.count() == 1, "something was deleted during the firing"
