"""A run that fails must not answer 200 {} (ROADMAP-FOLLOWUPS; audit f.1, T-8).

Found during Feature 004's T027 walkthrough: a run that died with
`FileNotFoundError` returned `HTTP 200 {}` from runs/wait, because the handler
returned the thread's checkpoint whenever one existed and never looked at the
run's status. The trigger engine — the in-repo consumer — then delivered
"(the assistant returned nothing)" for a run that had never started.

Both wait routes are covered: they carried the same fifteen lines, defect
included, and now share one implementation.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.routers import runs, thread_runs
from omniharness.runtime import RunRecord
from omniharness.runtime.runs.schemas import DisconnectMode, RunStatus

ROUTES = [
    pytest.param(thread_runs, "/api/threads/t1/runs/wait", id="thread"),
    pytest.param(runs, "/api/runs/wait", id="stateless"),
]


def _app(module, monkeypatch, *, status: RunStatus, error: str | None = None, values: dict | None = None):
    record = RunRecord(run_id="run-1", thread_id="t1", assistant_id="lead_agent", status=status, on_disconnect=DisconnectMode.cancel, error=error)

    async def _start_run(body, thread_id, request):
        return record

    import app.gateway.services as services

    monkeypatch.setattr(module, "start_run", _start_run)
    monkeypatch.setattr(services, "start_run", _start_run)

    app = make_authed_test_app()
    app.include_router(module.router)
    # The case that produced `{}`: a thread that HAS a checkpoint, empty or not.
    checkpointer = MagicMock()
    checkpointer.aget_tuple = AsyncMock(return_value=SimpleNamespace(checkpoint={"channel_values": values or {}}))
    app.state.checkpointer = checkpointer
    return app


@pytest.mark.parametrize(("module", "path"), ROUTES)
def test_a_successful_run_returns_its_state(module, path, monkeypatch) -> None:
    """Positive control: the route still answers 200 with the final state."""
    app = _app(module, monkeypatch, status=RunStatus.success, values={"title": "done"})

    with TestClient(app) as client:
        resp = client.post(path, json={"assistant_id": "lead_agent", "input": {}, "config": {"configurable": {"thread_id": "t1"}}})

    assert resp.status_code == 200, resp.text
    assert resp.json().get("title") == "done"


@pytest.mark.parametrize(("module", "path"), ROUTES)
def test_a_failed_run_is_not_reported_as_success(module, path, monkeypatch) -> None:
    app = _app(module, monkeypatch, status=RunStatus.error, error="FileNotFoundError: Agent directory not found")

    with TestClient(app) as client:
        resp = client.post(path, json={"assistant_id": "nope", "input": {}, "config": {"configurable": {"thread_id": "t1"}}})

    assert resp.status_code >= 400, f"a failed run answered {resp.status_code} {resp.text}"
    detail = resp.json()["detail"]
    assert detail["status"] == "error"
    assert "Agent directory not found" in detail["error"]


@pytest.mark.parametrize(("module", "path"), ROUTES)
@pytest.mark.parametrize(("status", "code"), [(RunStatus.timeout, 504), (RunStatus.interrupted, 409)])
def test_a_run_that_did_not_complete_says_how(module, path, status, code, monkeypatch) -> None:
    app = _app(module, monkeypatch, status=status)

    with TestClient(app) as client:
        resp = client.post(path, json={"assistant_id": "lead_agent", "input": {}, "config": {"configurable": {"thread_id": "t1"}}})

    assert resp.status_code == code, resp.text
    assert resp.json()["detail"]["status"] == status.value
