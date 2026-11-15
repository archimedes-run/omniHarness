"""A restart that lands while a run's agent is still being BUILT.

Building the agent (assembling its tools, a process per connector toolkit) is
off the event loop, so it can take seconds while the gateway keeps answering,
and a graceful stop can land in the middle of it. Nothing has recorded the
person's message yet then: the journal records it at the first model call and
the graph saves it at its first step. Before the fix such a run ended with an
empty journal, its notice offered nothing to try again (or, in a chat with
earlier turns, the PREVIOUS message), and with a build longer than the
shutdown's wait no notice was written at all.

Real gateways on one data dir (the restart test's harness), the scripted
model, and a build made slow by a delay before the real agent factory.
"""

from __future__ import annotations

import functools
import logging
import threading
import time

import pytest
from test_run_interrupted_by_restart import NOTICE, _gateway, _notices_in_history, _run_body, _runs, _wait, root, scripted  # noqa: F401

#: Seconds the shutdown waits for live runs (run_recovery.interrupt_live_runs).
SHUTDOWN_WAIT = 3.0


def _journal(client, thread_id: str, run_id: str) -> list[dict]:
    rows = client.get(f"/api/threads/{thread_id}/runs/{run_id}/messages", params={"limit": 200}).json()["data"]
    return [r["content"] for r in rows if isinstance(r.get("content"), dict)]


def _text(content) -> str:
    if isinstance(content, list):
        return " ".join(str(b.get("text", "")) for b in content if isinstance(b, dict))
    return str(content or "")


@pytest.mark.parametrize("build_seconds", [1.5, SHUTDOWN_WAIT + 1.0], ids=["short-build", "build-longer-than-shutdown-wait"])
@pytest.mark.parametrize("earlier_turn", [False, True], ids=["first-turn", "later-turn"])
def test_a_restart_during_the_build_keeps_the_message_and_its_notice(root, monkeypatch, caplog, build_seconds: float, earlier_turn: bool) -> None:  # noqa: F811
    import omniharness.agents.lead_agent.agent as lead

    real = lead.make_lead_agent
    slow = {"on": False}
    built = threading.Event()

    @functools.wraps(real)
    def slow_factory(*args, **kwargs):
        if not slow["on"]:
            return real(*args, **kwargs)
        try:
            time.sleep(build_seconds)
            return real(*args, **kwargs)
        finally:
            built.set()

    monkeypatch.setattr(lead, "make_lead_agent", slow_factory)
    asked = "what is on my calendar tomorrow?"
    scripted.SCRIPT.load({"lead": [{"content": "Nothing booked yet."}, {"sleep": 30, "content": "never written"}]})

    caplog.set_level(logging.WARNING)
    with _gateway(root, first=True) as client:
        thread_id = client.post("/api/threads", json={}).json()["thread_id"]
        if earlier_turn:
            assert client.post(f"/api/threads/{thread_id}/runs", json=_run_body("who is Jane Roe", thread_id)).status_code == 200
            assert _wait(lambda: [r for r in _runs(client, thread_id) if r["status"] == "success"])
        slow["on"] = True
        assert client.post(f"/api/threads/{thread_id}/runs", json=_run_body(asked, thread_id)).status_code == 200
        assert _wait(lambda: any(r["status"] == "running" for r in _runs(client, thread_id)))
        time.sleep(0.3)  # inside the build
        assert not built.is_set()
        stopping = time.monotonic()
    stopped_in = time.monotonic() - stopping
    # The stop did not wait for the build.
    assert stopped_in < SHUTDOWN_WAIT + 3.0, stopped_in
    # The abandoned build finishes in its thread before the next start.
    assert built.wait(timeout=build_seconds + 10)

    import app.gateway.run_recovery as recovery

    async def no_sweep(*a, **k):
        return None

    monkeypatch.setattr(recovery, "recover_forever", no_sweep)
    with _gateway(root, first=False) as client:
        runs = _runs(client, thread_id)
        cut = [r for r in runs if r["status"] != "success"]
        assert [(r["status"], r.get("error")) for r in cut] == [("interrupted", "restart")], runs
        assert _notices_in_history(client, thread_id) == 1
        rows = _journal(client, thread_id, cut[0]["run_id"])
        # The person's message is in the chat's history, in their words...
        humans = [r for r in rows if r.get("type") == "human"]
        assert [_text(h.get("content")) for h in humans] == [asked], rows
        # ...and the notice (written into the thread's state at shutdown, at
        # the end: after the earlier turn, never inside it) offers exactly it
        # again, never the earlier turn's message.
        state = client.get(f"/api/threads/{thread_id}/state").json()
        messages = (state.get("values") or {}).get("messages") or []
        notice = messages[-1]
        assert NOTICE in str(notice.get("content")), messages
        assert notice["additional_kwargs"]["omniharness_run_notice"]["retry_text"] == asked
        if earlier_turn:
            assert [_text(m.get("content")) for m in messages[:-1]] == ["who is Jane Roe", "Nothing booked yet."], messages
        assert len(runs) == (2 if earlier_turn else 1), "a run was retried without the owner asking"

    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "Task was destroyed but it is pending" not in logged
    assert "no active connection" not in logged
