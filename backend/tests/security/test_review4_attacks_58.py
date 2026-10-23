# ruff: noqa: F401, F811
"""Fourth independent adversarial review of PR #58. Real HTTP, auth ON.

Reuses `gateway` (create_app()+lifespan, real runs, the real task tool and
SubagentExecutor, fake models) from tests/policy/test_delegated_confirmation.py.
Ported close to verbatim from the reviewer's attack scripts; each asserts the
SAFE outcome.

H1 - Stopping a Continue released its lock while the resumed agent was still
running (the worker thread outlives the cancelled await), so a second Continue
entered the same delegation concurrently.

H2 - A delegation confirmed by TYPING "yes" ran the whole subagent on the
gateway's event loop (awrap_model_call -> _complete_confirmation ->
run_on_surface -> invoke -> _await joins a thread), so every other request
hung until it finished. The card path already ran off the loop.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

from langchain_core.messages import AIMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "policy"))
import test_delegated_confirmation as dc  # noqa: E402
from test_delegated_confirmation import (  # noqa: E402
    DELEGATE,
    RAN,
    SUB_SCRIPT,
    SUBAGENT_RUNS,
    _pending,
    _say,
    _stored,
    _thread,
    _user_delegates_and_subagent_proposes,
    gateway,
)


def _continue_run(gateway, thread_id: str, action_id: str):
    return gateway.client.post(
        f"/api/threads/{thread_id}/runs",
        json={"assistant_id": "lead_agent", "input": {"messages": [{"role": "user", "content": "Continue general-purpose."}]}, "context": {"continue_action": action_id}},
    )


# ---------------------------------------------------------------------------
# H1: a stopped Continue keeps its lock until the resumed agent really ends
# ---------------------------------------------------------------------------


def test_cancelled_continue_releases_lock_while_resume_still_runs(gateway, monkeypatch, tmp_path):
    thread_id, wipe = _user_delegates_and_subagent_proposes(gateway)
    assert gateway.client.post(f"/api/confirmations/{wipe['id']}/confirm", json={}).json()["outcome"] == "executed"

    entered, release = threading.Event(), threading.Event()
    resumes = []

    real = dc.SeeingFake._generate

    def held(self, messages, stop=None, run_manager=None, **kw):
        if any("Observed context" in str(m.content) for m in messages):
            resumes.append(time.time())
            entered.set()
            assert release.wait(30)
        return real(self, messages, stop=stop, run_manager=run_manager, **kw)

    monkeypatch.setattr(dc.SeeingFake, "_generate", held)
    SUB_SCRIPT[:] = [AIMessage(content="continued A")]
    dc.LEAD_SCRIPT[:] = [AIMessage(content="lead must not answer")]
    resp = _continue_run(gateway, thread_id, wipe["id"])
    assert resp.status_code == 200, resp.text
    run_id = resp.json()["run_id"]
    try:
        assert entered.wait(30), "first resume never started"

        from app.policy.registration import build
        from omniharness.config import get_app_config

        store = build(get_app_config()).pending
        lock = store._continue_path(wipe["id"])
        assert lock.exists(), "the Continue lock is not held during the first resume"

        c = gateway.client.post(f"/api/threads/{thread_id}/runs/{run_id}/cancel")
        assert c.status_code in (200, 202, 204), c.text
        # Wait until the run is no longer in flight
        for _ in range(100):
            r = gateway.client.get(f"/api/threads/{thread_id}/runs/{run_id}").json()
            if r.get("status") not in ("pending", "running"):
                break
            time.sleep(0.1)
        assert r.get("status") not in ("pending", "running"), f"the run was not stopped: {r}"
        assert not release.is_set()
        lock_after_cancel = lock.exists()

        entered.clear()
        second = _continue_run(gateway, thread_id, wipe["id"])
        got_second = entered.wait(10)
        assert not (second.status_code == 200 and got_second), "DOUBLE RE-ENTRY: Continue released by cancel while the first resume still runs"
        assert lock_after_cancel, "Stop released the Continue lock while the resumed agent is still inside the delegation"
        assert second.status_code == 409 and "being continued now" in second.text, second.text
        assert len(resumes) == 1
    finally:
        release.set()

    # The lock follows the worker thread: once the stopped resume really ends,
    # the Continue (which did not succeed) can be pressed again.
    for _ in range(100):
        if not lock.exists():
            break
        time.sleep(0.1)
    assert not lock.exists(), "the stopped Continue never released its lock after the resumed agent ended"
    assert not _stored(wipe["id"]).continued, "a stopped Continue was recorded as done"


# ---------------------------------------------------------------------------
# H2: a typed "yes" runs the confirmed delegation off the event loop
# ---------------------------------------------------------------------------


def test_typed_yes_delegation_blocks_event_loop(gateway, monkeypatch):
    thread_id = _thread(gateway)
    _say(gateway, thread_id, "ask a helper to wipe the nightly backup", [AIMessage(content="", tool_calls=[DELEGATE]), AIMessage(content="Delegation waiting.")])
    [delegation] = _pending(gateway, "task")

    entered, release = threading.Event(), threading.Event()
    real = dc.SeeingFake._generate

    def held(self, messages, stop=None, run_manager=None, **kw):
        entered.set()
        release.wait(20)
        return real(self, messages, stop=stop, run_manager=run_manager, **kw)

    monkeypatch.setattr(dc.SeeingFake, "_generate", held)
    SUB_SCRIPT[:] = [AIMessage(content="done")]
    dc.LEAD_SCRIPT[:] = [AIMessage(content="unused")]
    resp = gateway.client.post(f"/api/threads/{thread_id}/runs", json={"assistant_id": "lead_agent", "input": {"messages": [{"role": "user", "content": "yes"}]}, "context": {"subagent_enabled": True}})
    assert resp.status_code == 200
    try:
        assert entered.wait(20), "subagent never started"

        box = {}

        def probe():
            t0 = time.time()
            r = gateway.client.get("/api/confirmations")
            box["status"], box["secs"] = r.status_code, time.time() - t0

        t = threading.Thread(target=probe)
        t.start()
        t.join(5)
        blocked = t.is_alive()
    finally:
        release.set()
    t.join(30)
    assert not blocked, "event loop blocked by a typed-yes confirmed delegation"
    assert box.get("status") == 200, box

    # The typed "yes" still confirmed and ran it, exactly once.
    run_id = resp.json()["run_id"]
    for _ in range(100):
        r = gateway.client.get(f"/api/threads/{thread_id}/runs/{run_id}").json()
        if r.get("status") not in ("pending", "running"):
            break
        time.sleep(0.1)
    assert r.get("status") == "success", r
    stored = _stored(delegation["id"])
    assert stored.outcome is not None and stored.outcome.value == "executed", stored.outcome
    assert (stored.confirmation or {}).get("via") == "typed_reply", stored.confirmation
    assert len(SUBAGENT_RUNS) == 1, "the confirmed delegation did not run exactly once"
