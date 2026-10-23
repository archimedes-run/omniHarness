"""A confirmed action runs off the event loop, so a long one cannot freeze the gateway.

Live, 2026-10-23, container sandbox: confirming a bash card ran `npm exec` in
the sandbox from inside the async confirm route. The event loop waited on the
sandbox's HTTP call (up to its 600 s no-change timeout) and every other request
hung until the gateway was restarted.
"""

from __future__ import annotations

import asyncio
import threading

from test_capture_through_the_app import pending, propose


def _recording_runner(seen: list[dict]):
    async def _runner(request, thread_id, user_id):
        def run(tool_name: str, arguments: dict):
            try:
                asyncio.get_running_loop()
                on_loop = True
            except RuntimeError:
                on_loop = False
            seen.append({"tool": tool_name, "thread": threading.get_ident(), "on_loop": on_loop})
            return "ok"

        return run

    return _runner


def test_a_confirmed_action_runs_in_a_worker_thread(gateway, monkeypatch) -> None:
    seen: list[dict] = []
    monkeypatch.setattr("app.gateway.routers.confirmations._runner", _recording_runner(seen))
    propose(gateway)
    [action] = pending(gateway)

    resp = gateway.client.post(f"/api/confirmations/{action['id']}/confirm", json={})
    assert resp.json()["outcome"] == "executed", resp.text
    assert [s["tool"] for s in seen] == ["ledger_apply"]
    assert not seen[0]["on_loop"], "the confirmed tool ran on the event loop: a long command freezes every request"


def test_an_edited_and_confirmed_action_runs_in_a_worker_thread(gateway, monkeypatch) -> None:
    from test_capture_through_the_app import CHANGES

    seen: list[dict] = []
    monkeypatch.setattr("app.gateway.routers.confirmations._runner", _recording_runner(seen))
    propose(gateway)
    [action] = pending(gateway)

    resp = gateway.client.post(f"/api/confirmations/{action['id']}/edit", json={"arguments": {"changes": CHANGES[:1]}})
    assert resp.json()["outcome"] == "executed", resp.text
    assert [s["tool"] for s in seen] == ["ledger_apply"]
    assert not seen[0]["on_loop"], "the edited plan ran on the event loop"
