"""A job is alive from its row until its terminal status (a heartbeat
thread), and only a job with BOTH an old heartbeat and no live runner is
ever shown or recorded as stopped. Read routes never write."""

from __future__ import annotations

import os
import threading
import time

import pytest

from app.gateway.code_jobs import runner as runner_mod
from app.gateway.code_jobs import store as store_mod

from .test_app_mode import app_result
from .test_app_mode_http import AppFake, apps, build
from .test_app_update_http import UPDATE, _following_lead, approved_today, ask_in, pending
from .test_code_job_http import SANDBOX, _thread, gateway  # noqa: F401 - the fixture

#: How old the running job's heartbeat was, each time the watcher looked.
AGES: list = []


class SlowStart(AppFake):
    """The first command of the job (making its folder) takes `delay` s, as a
    busy sandbox's first exec can: longer than the staleness threshold."""

    delay = 3.0
    slowed = False

    def sh(self, command: str, *, timeout: int = 30):
        if not self.slowed and "/tmp/omni-jobs/" in command and "mkdir -p" in command:
            self.slowed = True
            time.sleep(self.delay)
        return super().sh(command, timeout=timeout)


@pytest.fixture
def quick(monkeypatch):
    """A 1 s staleness threshold and a 0.2 s heartbeat: the slow start is 3x the threshold."""
    monkeypatch.setattr(store_mod, "STALE_SECONDS", 1.0)
    monkeypatch.setattr(runner_mod, "HEARTBEAT_SECONDS", 0.2)


def _watch(gateway, thread_id: str, call_id: str, stop: threading.Event, seen: list):  # noqa: F811
    """What the card and every reaper see while the job runs."""
    store = gateway.client.app.state.code_job_store
    while not stop.is_set():
        store.reap_stale()
        resp = gateway.client.get(f"/api/threads/{thread_id}/code-jobs/by-call/{call_id}")
        if resp.status_code == 200:
            body = resp.json()["job"]
            seen.append(body["status"])
            row = store.get(body["id"])
            if row is not None and row.status == "running":
                AGES.append(time.time() - row.updated_at)
        time.sleep(0.1)


def test_a_slow_start_is_never_shown_or_recorded_as_stopped(gateway, quick):  # noqa: F811
    from .test_app_mode_http import BRIEF, ask

    SANDBOX["current"] = SlowStart(build())
    AGES.clear()
    seen: list = []
    stop = threading.Event()
    thread_id = _thread(gateway)
    watcher = threading.Thread(target=lambda: _watch(gateway, thread_id, "cj1", stop, seen), daemon=True)
    watcher.start()
    try:
        from langchain_core.messages import AIMessage

        from .test_code_job_http import LEAD_SCRIPT

        LEAD_SCRIPT[:] = [AIMessage(content="", tool_calls=[{"name": "code_job", "args": BRIEF, "id": "cj1"}]), AIMessage(content="Reported."), *[AIMessage(content="(done)")] * 3]
        resp = gateway.client.post(f"/api/threads/{thread_id}/runs/wait", json={"assistant_id": "lead_agent", "input": {"messages": [{"role": "user", "content": "Build me a Today page."}]}, "context": {"mode": "pro"}})
        assert resp.status_code == 200
    finally:
        stop.set()
        watcher.join(5)
    (job,) = gateway.client.app.state.code_job_store.for_thread(thread_id)
    assert job.status == "verified", (job.status, job.reason)
    assert seen and "blocked" not in seen and seen[0] == "running"
    # The heartbeat kept beating through the 3 s start (0.2 s beats; threshold 1 s).
    assert AGES and max(AGES) < 1.0, max(AGES)
    del ask


def test_a_live_job_without_beats_is_still_never_reaped_in_its_own_process(gateway, quick, monkeypatch):  # noqa: F811
    from .test_app_mode_http import BRIEF

    monkeypatch.setattr(runner_mod, "HEARTBEAT_SECONDS", 3600.0)  # no beats at all
    monkeypatch.setattr(runner_mod, "BEAT_SECONDS", 3600.0)
    SANDBOX["current"] = SlowStart(build())
    thread_id = _thread(gateway)
    seen: list = []
    stop = threading.Event()
    watcher = threading.Thread(target=lambda: _watch(gateway, thread_id, "cj1", stop, seen), daemon=True)
    watcher.start()
    try:
        assert "STATUS VERIFIED" in ask_in(gateway, thread_id, BRIEF, "cj1")
    finally:
        stop.set()
        watcher.join(5)
    assert "blocked" not in seen


def _row(store, job_id: str, owner: str, age: float = 600.0) -> None:
    store.create(job_id=job_id, thread_id="t", user_id="u", tool_call_id=job_id, title="x", project_dir="p", budget_usd=1, model="m")
    store._conn().execute("UPDATE jobs SET owner = ?, updated_at = ? WHERE id = ?", (owner, time.time() - age, job_id))


def test_a_dead_runner_is_reaped_with_a_truthful_reason(tmp_path):
    store = store_mod.CodeJobStore(tmp_path / "jobs.db")
    _row(store, "a" * 16, "999999:1")  # a process that is gone
    _row(store, "b" * 16, store_mod.OWNER)  # this process, but no live runner
    _row(store, "c" * 16, store_mod.OWNER, age=10)  # beating recently
    assert sorted(store.reap_stale()) == ["a" * 16, "b" * 16]
    assert store.get("a" * 16).reason == "the gateway restarted while the job ran"
    assert store.get("b" * 16).reason == "the job's runner stopped responding"
    assert store.get("c" * 16).status == "running"


def test_two_instances_never_reap_a_job_another_live_process_runs(tmp_path):
    first = store_mod.CodeJobStore(tmp_path / "jobs.db")
    second = store_mod.CodeJobStore(tmp_path / "jobs.db")
    parent = os.getppid()
    _row(first, "d" * 16, f"{parent}:{store_mod._process_start(parent) or ''}")  # a live process (not this one), stale beats
    assert first.reap_stale() == [] and second.reap_stale() == []
    job = second.get("d" * 16)
    assert job.status == "running" and second.as_seen(job).status == "running"


def test_reading_a_job_never_writes(gateway, quick):  # noqa: F811
    store = gateway.client.app.state.code_job_store
    thread_id = _thread(gateway)
    owner = gateway.client.get("/api/v1/auth/me").json()["id"]
    store.create(job_id="e" * 16, thread_id=thread_id, user_id=owner, tool_call_id="r1", title="x", project_dir="p", budget_usd=1, model="m")
    store._conn().execute("UPDATE jobs SET owner = ?, updated_at = ? WHERE id = ?", ("999999:1", time.time() - 600, "e" * 16))
    assert gateway.client.get(f"/api/threads/{thread_id}/code-jobs/by-call/r1").json()["job"]["status"] == "blocked"
    assert gateway.client.get(f"/api/threads/{thread_id}/code-jobs").status_code == 200
    assert store.get("e" * 16).status == "running"  # shown stopped, recorded by no read


def test_the_update_fail_pass_chain_with_a_slow_start_keeps_app_mode_and_the_app_budget(gateway, quick, monkeypatch):  # noqa: F811
    thread_id = approved_today(gateway)
    overflow = app_result({("light", "fresh"): {360: {"overflow_px": 400}}})
    SANDBOX["queue"] = [AppFake(build(), probe=overflow), SlowStart(build())]
    monkeypatch.setattr("omniharness.agents.lead_agent.agent.create_chat_model", lambda **_: _following_lead())
    resp = gateway.client.post(f"/api/threads/{thread_id}/runs/wait", json={"assistant_id": "lead_agent", "input": {"messages": [{"role": "user", "content": "Change my Today app."}]}, "context": {"mode": "pro"}})
    assert resp.status_code == 200, resp.text
    jobs = sorted(gateway.client.app.state.code_job_store.for_thread(thread_id), key=lambda j: j.created_at)
    update, passed = jobs[-2], jobs[-1]
    assert update.status == "unverified" and passed.status == "verified", (passed.status, passed.reason)
    assert passed.result["fix_of"] == update.id and passed.result["app"]["root"] == update.id
    assert update.budget_usd == 2.0 and passed.budget_usd == 2.0
    assert apps(gateway)[0]["pending_version"] == 2 and pending(gateway, thread_id)[0]["kind"] == "version"


def _untagged_lead():
    """Runs the update, then a 'design pass' WITHOUT fix_of (as a live lead did)."""
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage, ToolMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    class Lead(BaseChatModel):
        disable_streaming: bool = True

        @property
        def _llm_type(self) -> str:
            return "untagged-lead"

        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            results = [m for m in messages if isinstance(m, ToolMessage) and str(getattr(m, "tool_call_id", "")).startswith("ut")]
            if not results:
                call = {"name": "code_job", "args": UPDATE, "id": "ut1"}
            elif len(results) == 1:
                call = {"name": "code_job", "args": {"goal": "Design pass: fix these without changing behaviour or sources", "project_dir": "today"}, "id": "ut2"}
            else:
                call = None
            message = AIMessage(content="", tool_calls=[call]) if call else AIMessage(content="Reported.")
            return ChatResult(generations=[ChatGeneration(message=message)])

    return Lead()


def test_a_pass_started_without_fix_of_is_still_the_apps_design_pass(gateway, monkeypatch):  # noqa: F811
    thread_id = approved_today(gateway)
    overflow = app_result({("light", "fresh"): {360: {"overflow_px": 400}}})
    SANDBOX["queue"] = [AppFake(build(), probe=overflow), AppFake(build())]
    monkeypatch.setattr("omniharness.agents.lead_agent.agent.create_chat_model", lambda **_: _untagged_lead())
    resp = gateway.client.post(f"/api/threads/{thread_id}/runs/wait", json={"assistant_id": "lead_agent", "input": {"messages": [{"role": "user", "content": "Change my Today app."}]}, "context": {"mode": "pro"}})
    assert resp.status_code == 200, resp.text
    jobs = sorted(gateway.client.app.state.code_job_store.for_thread(thread_id), key=lambda j: j.created_at)
    update, passed = jobs[-2], jobs[-1]
    assert passed.result["fix_of"] == update.id and passed.result["app"]["design_pass"] is True
    assert passed.budget_usd == 2.0 and passed.status == "verified"
    assert apps(gateway)[0]["pending_version"] == 2
