"""Deleting the run history deletes the automations' conversation threads too
(app/run_history/delete.py), through create_app() and real HTTP: the thread's
checkpoints, record and files go; a person's own chat thread stays; a running
thread refuses the delete; and with the engine running, the delete runs on the
engine's own worker."""

from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace

import pytest

SECRET_CONTENT = "AUTOMATION-THREAD-CONTENT-7731"


def _state_dir(tmp_path):
    return tmp_path / "triggers"


@pytest.fixture
def seeded(make_gateway, tmp_path):
    """A gateway with one automation thread (in the rule map, named by a stored
    run, holding content) and one ordinary chat thread."""

    def tweak(config: dict) -> None:
        config["trigger_engine"] = {"enabled": False, "state_dir": str(_state_dir(tmp_path))}

    with make_gateway(tweak) as (client, home):
        auto = client.post("/api/threads", json={"metadata": {"title": "inbox automation"}}).json()["thread_id"]
        chat = client.post("/api/threads", json={"metadata": {"title": "my chat"}}).json()["thread_id"]
        for tid, text in ((auto, SECRET_CONTENT), (chat, "a person's own chat")):
            r = client.post(f"/api/threads/{tid}/state", json={"values": {"messages": [{"type": "human", "content": text}]}})
            assert r.status_code == 200, r.text
        _state_dir(tmp_path).mkdir(parents=True, exist_ok=True)
        (_state_dir(tmp_path) / "threads.json").write_text(json.dumps({"inbox": auto}))
        client.app.state.run_history.record(kind="automation", source_id="inbox", thread_id=auto, body={"reply": "r"}, status="completed")
        yield client, auto, chat


def _checkpoint(client, tid):
    cp = client.app.state.checkpointer
    return client.portal.call(lambda: cp.aget_tuple({"configurable": {"thread_id": tid, "checkpoint_ns": ""}}))


def test_deleting_the_history_deletes_the_automation_threads(seeded, tmp_path) -> None:
    client, auto, chat = seeded
    assert SECRET_CONTENT in json.dumps(client.get(f"/api/threads/{auto}/state").json())

    resp = client.delete("/api/run-history/runs", params={"confirm": "delete-all"})

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"deleted": 1, "threads_deleted": 1, "threads_failed": []}
    assert client.get(f"/api/threads/{auto}").status_code == 404, "the automation's thread record survived"
    assert _checkpoint(client, auto) is None, "the automation's checkpoints (its messages) survived"
    assert json.loads((_state_dir(tmp_path) / "threads.json").read_text()) == {}, "the rule still points at the deleted thread"
    # A person's own chat is not an automation thread and is untouched.
    assert client.get(f"/api/threads/{chat}").status_code == 200
    assert _checkpoint(client, chat) is not None


def test_a_running_automation_thread_refuses_the_delete(seeded) -> None:
    client, auto, _ = seeded
    from omniharness.runtime.runs.schemas import RunStatus

    manager = client.app.state.run_manager
    record = client.portal.call(lambda: manager.create(auto, "lead_agent"))
    client.portal.call(lambda: manager.set_status(record.run_id, RunStatus.running))

    resp = client.delete("/api/run-history/runs", params={"confirm": "delete-all"})

    assert resp.status_code == 409 and "Nothing was deleted" in resp.json()["detail"]
    assert client.app.state.run_history.count() == 1
    assert client.get(f"/api/threads/{auto}").status_code == 200
    assert _checkpoint(client, auto) is not None


@pytest.mark.asyncio
async def test_with_the_engine_running_the_delete_runs_on_its_worker(tmp_path) -> None:
    """No firing can start between the busy check and the delete."""
    from concurrent.futures import ThreadPoolExecutor

    from app.run_history.delete import delete_history_and_threads
    from app.run_history.store import RunHistory
    from app.trigger_engine.lifespan import EngineHandle
    from app.trigger_engine.runner import RuleRunner
    from app.trigger_engine.threads import RuleThreadMap

    history = RunHistory(tmp_path / "history")
    seen: list[str] = []
    real_delete_all = history.delete_all

    def delete_all() -> int:
        seen.append(threading.current_thread().name)
        return real_delete_all()

    history.delete_all = delete_all
    runner = RuleRunner.__new__(RuleRunner)
    runner.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="trigger-engine")
    loop = SimpleNamespace(threads=RuleThreadMap(path=tmp_path / "threads.json", create_thread=lambda r: "t"), runner=runner)
    handle = EngineHandle(loop=loop, task=asyncio.create_task(asyncio.sleep(30)))
    app = SimpleNamespace(state=SimpleNamespace(run_history=history, trigger_engine=handle))

    await delete_history_and_threads(app)
    handle.task.cancel()

    assert seen and seen[0].startswith("trigger-engine"), f"ran on {seen}"
