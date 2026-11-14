"""Reloading a chat after a restart: its latest run is no longer held by this
process (interrupted by the restart, or finished before it). Joining it, or
reading it by id, answers from the run store instead of a 404 that the chat
showed as a red "HTTP 404: Run … not found" toast."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.routers import thread_runs
from omniharness.runtime import RunManager
from omniharness.runtime.runs.store.memory import MemoryRunStore


def _client(store: MemoryRunStore) -> TestClient:
    app = make_authed_test_app()
    app.include_router(thread_runs.router)
    # A fresh manager over the same store: the process after the restart.
    app.state.run_manager = RunManager(store=store)
    app.state.stream_bridge = MagicMock()  # never subscribed: the run is not live here
    return TestClient(app)


@pytest.fixture
def store():
    import asyncio

    s = MemoryRunStore()

    async def plant():
        await s.put("run-interrupted", thread_id="t1", status="interrupted", error="restart")
        await s.put("run-done", thread_id="t1", status="success")

    asyncio.run(plant())
    return s


@pytest.mark.parametrize("run_id,status", [("run-interrupted", "interrupted"), ("run-done", "success")])
def test_joining_a_run_from_before_the_restart_ends_quietly(store, run_id: str, status: str) -> None:
    client = _client(store)
    for method, path in (("GET", f"/api/threads/t1/runs/{run_id}/join"), ("GET", f"/api/threads/t1/runs/{run_id}/stream"), ("POST", f"/api/threads/t1/runs/{run_id}/stream")):
        resp = client.request(method, path)
        assert resp.status_code == 200, (path, resp.text)
        assert "event: end" in resp.text
    run = client.get(f"/api/threads/t1/runs/{run_id}")
    assert run.status_code == 200 and run.json()["status"] == status


def test_an_unknown_run_or_another_threads_run_is_still_404(store) -> None:
    client = _client(store)
    assert client.get("/api/threads/t1/runs/nope/join").status_code == 404
    assert client.get("/api/threads/t2/runs/run-done/join").status_code == 404
    assert client.get("/api/threads/t2/runs/run-done").status_code == 404
