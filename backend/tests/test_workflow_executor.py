"""Tests for Phase 1 Slice 2 — Workflow executor seam + manual-run API.

Covers:
- executor module is importable (no side effects, no app.* at import time)
- executor guard: no-op on terminal status
- executor guard: no-op on already "running" status
- executor guard: transition to failed when no instruction_prompt
- executor guard: transition to failed when workflow not found
- executor set_thread_run is called with correct IDs (happy path, mocked run pipeline)
- executor transitions to failed (never left "running") on run pipeline error
- router POST /api/workflows/{id}/run → 202 + WorkflowRunResponse
- router manual runs never deduplicate (two POSTs → two distinct run IDs)
- router GET /api/workflows/{id}/runs lists runs
- router GET /api/workflows/{id}/runs/{run_id} returns single run
- router GET /api/workflows/{id}/runs/{run_id} returns 404 for wrong workflow_id
- services.py still exports launch_agent_run_detached (harness-boundary side)
"""

from __future__ import annotations

import asyncio
import importlib
import types
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from omniharness.persistence.base import Base

# ---------------------------------------------------------------------------
# In-memory SQLite fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        import omniharness.persistence.models  # noqa: F401 — registers all tables

        await conn.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    yield sf
    await engine.dispose()


# ---------------------------------------------------------------------------
# Helper: build a minimal workflow + run via real repos
# ---------------------------------------------------------------------------


async def _make_workflow(sf, *, instruction_prompt: str | None = "do x") -> dict:
    from omniharness.persistence.workflow_versions.sql import WorkflowVersionRepository
    from omniharness.persistence.workflows.sql import WorkflowRepository

    wf_repo = WorkflowRepository(sf)
    ver_repo = WorkflowVersionRepository(sf)

    wf = await wf_repo.create(id=str(uuid.uuid4()), owner_id="u1", title="Test Wf", instruction_prompt=instruction_prompt)
    if instruction_prompt:
        vid = str(uuid.uuid4())
        await ver_repo.create(id=vid, workflow_id=wf["id"], version_number=1, instruction_prompt=instruction_prompt)
        wf = await wf_repo.set_current_version(wf["id"], vid) or wf
    return wf


async def _make_run(sf, workflow_id: str, *, status: str = "queued") -> dict:
    from omniharness.persistence.workflow_runs.sql import WorkflowRunRepository

    repo = WorkflowRunRepository(sf)
    key = f"wf:{workflow_id}:manual:{uuid.uuid4()}"
    row, _ = await repo.create_or_get_by_key(
        workflow_id=workflow_id,
        idempotency_key=key,
        id=str(uuid.uuid4()),
        trigger_type="manual",
    )
    if status != "queued":
        row = await repo.transition_status(row["id"], status)
    return row


# ---------------------------------------------------------------------------
# Helper: build a minimal fake app.state
# ---------------------------------------------------------------------------


def _make_app_state(sf, *, bridge=None, run_mgr=None, event_store=None):
    from omniharness.persistence.workflow_artifact_links.sql import WorkflowArtifactLinkRepository
    from omniharness.persistence.workflow_runs.sql import WorkflowRunRepository
    from omniharness.persistence.workflow_step_runs.sql import WorkflowStepRunRepository
    from omniharness.persistence.workflow_versions.sql import WorkflowVersionRepository
    from omniharness.persistence.workflows.sql import WorkflowRepository

    state = types.SimpleNamespace(
        workflow_repo=WorkflowRepository(sf),
        workflow_version_repo=WorkflowVersionRepository(sf),
        workflow_run_repo=WorkflowRunRepository(sf),
        workflow_step_run_repo=WorkflowStepRunRepository(sf),
        workflow_artifact_link_repo=WorkflowArtifactLinkRepository(sf),
        stream_bridge=bridge or MagicMock(),
        run_manager=run_mgr or MagicMock(),
        run_event_store=event_store,
        checkpointer=None,
        store=None,
        thread_store=None,
        preview_controller=None,
        config=MagicMock(run_events=None),
    )

    app = types.SimpleNamespace(state=state)
    return app


# ---------------------------------------------------------------------------
# Section 1 — executor import
# ---------------------------------------------------------------------------


class TestExecutorImport:
    def test_executor_importable(self):
        mod = importlib.import_module("app.gateway.workflows.executor")
        assert hasattr(mod, "execute_workflow_run")

    def test_execute_workflow_run_is_coroutine_function(self):
        from app.gateway.workflows.executor import execute_workflow_run

        assert asyncio.iscoroutinefunction(execute_workflow_run)

    def test_services_exports_launch_agent_run_detached(self):
        from app.gateway.services import launch_agent_run_detached

        assert asyncio.iscoroutinefunction(launch_agent_run_detached)


# ---------------------------------------------------------------------------
# Section 2 — executor guard: idempotent no-ops
# ---------------------------------------------------------------------------


class TestExecutorGuards:
    @pytest.mark.asyncio
    async def test_noop_on_terminal_succeeded(self, session_factory):
        from app.gateway.workflows.executor import execute_workflow_run
        from omniharness.persistence.workflow_runs.sql import WorkflowRunRepository

        wf = await _make_workflow(session_factory)
        run_row = await _make_run(session_factory, wf["id"], status="queued")
        repo = WorkflowRunRepository(session_factory)
        # Manually advance to terminal
        await repo.transition_status(run_row["id"], "running")
        await repo.transition_status(run_row["id"], "succeeded")

        fake_app = _make_app_state(session_factory)
        await execute_workflow_run(run_row["id"], app=fake_app)

        after = await repo.get(run_row["id"])
        assert after["status"] == "succeeded"  # unchanged

    @pytest.mark.asyncio
    async def test_noop_on_already_running(self, session_factory):
        from app.gateway.workflows.executor import execute_workflow_run
        from omniharness.persistence.workflow_runs.sql import WorkflowRunRepository

        wf = await _make_workflow(session_factory)
        run_row = await _make_run(session_factory, wf["id"], status="queued")
        repo = WorkflowRunRepository(session_factory)
        await repo.transition_status(run_row["id"], "running")

        fake_app = _make_app_state(session_factory)
        # Should return immediately without error
        await execute_workflow_run(run_row["id"], app=fake_app)

        after = await repo.get(run_row["id"])
        assert after["status"] == "running"  # not further modified

    @pytest.mark.asyncio
    async def test_noop_run_not_found(self, session_factory):
        from app.gateway.workflows.executor import execute_workflow_run

        fake_app = _make_app_state(session_factory)
        # Should log and return without raising
        await execute_workflow_run("nonexistent-run-id", app=fake_app)

    @pytest.mark.asyncio
    async def test_fails_when_no_instruction_prompt(self, session_factory):
        from app.gateway.workflows.executor import execute_workflow_run
        from omniharness.persistence.workflow_runs.sql import WorkflowRunRepository

        wf = await _make_workflow(session_factory, instruction_prompt=None)
        run_row = await _make_run(session_factory, wf["id"])
        repo = WorkflowRunRepository(session_factory)

        fake_app = _make_app_state(session_factory)
        await execute_workflow_run(run_row["id"], app=fake_app)

        after = await repo.get(run_row["id"])
        assert after["status"] == "failed"
        assert after["error_summary"] is not None

    @pytest.mark.asyncio
    async def test_fails_when_workflow_not_found(self, session_factory):
        """Run referencing a deleted/missing workflow → failed."""
        from app.gateway.workflows.executor import execute_workflow_run
        from omniharness.persistence.workflow_runs.sql import WorkflowRunRepository

        # Create a workflow then delete it (simulate via direct run with fake wf id)
        fake_wf_id = str(uuid.uuid4())
        repo = WorkflowRunRepository(session_factory)
        key = f"wf:{fake_wf_id}:manual:{uuid.uuid4()}"
        run_row, _ = await repo.create_or_get_by_key(
            workflow_id=fake_wf_id,
            idempotency_key=key,
            id=str(uuid.uuid4()),
            trigger_type="manual",
        )

        # workflow_repo.get will return None since wf never existed
        fake_app = _make_app_state(session_factory)
        await execute_workflow_run(run_row["id"], app=fake_app)

        after = await repo.get(run_row["id"])
        assert after["status"] == "failed"

    @pytest.mark.asyncio
    async def test_missing_bridge_logs_and_returns(self, session_factory):
        """When bridge/run_mgr are None (memory backend), executor logs and returns cleanly."""
        from app.gateway.workflows.executor import execute_workflow_run

        wf = await _make_workflow(session_factory)
        run_row = await _make_run(session_factory, wf["id"])

        state = types.SimpleNamespace(
            workflow_repo=None,  # missing — executor should early-return
            stream_bridge=None,
            run_manager=None,
            run_event_store=None,
            config=None,
        )
        fake_app = types.SimpleNamespace(state=state)
        await execute_workflow_run(run_row["id"], app=fake_app)  # must not raise


# ---------------------------------------------------------------------------
# Section 3 — executor happy path (mocked run pipeline)
# ---------------------------------------------------------------------------


class TestExecutorHappyPath:
    @pytest.mark.asyncio
    async def test_happy_path_transitions_to_succeeded(self, session_factory):
        from omniharness.persistence.workflow_runs.sql import WorkflowRunRepository
        from omniharness.runtime import RunRecord, RunStatus

        wf = await _make_workflow(session_factory)
        run_row = await _make_run(session_factory, wf["id"])
        repo = WorkflowRunRepository(session_factory)

        # Build a fake RunRecord whose task completes successfully
        fake_task = asyncio.ensure_future(asyncio.sleep(0))
        fake_record = MagicMock(spec=RunRecord)
        fake_record.task = fake_task
        fake_record.run_id = str(uuid.uuid4())
        fake_record.status = RunStatus.success

        fake_app = _make_app_state(session_factory)

        with patch("app.gateway.workflows.executor.launch_agent_run_detached", new=AsyncMock(return_value=fake_record)):
            with patch("app.gateway.workflows.executor.build_run_config", return_value={"configurable": {}}):
                from app.gateway.workflows.executor import execute_workflow_run

                await execute_workflow_run(run_row["id"], app=fake_app)

        after = await repo.get(run_row["id"])
        assert after["status"] == "succeeded"
        assert after["thread_id"] is not None
        assert after["run_id"] == fake_record.run_id

    @pytest.mark.asyncio
    async def test_launch_failure_transitions_to_failed(self, session_factory):
        from omniharness.persistence.workflow_runs.sql import WorkflowRunRepository

        wf = await _make_workflow(session_factory)
        run_row = await _make_run(session_factory, wf["id"])
        repo = WorkflowRunRepository(session_factory)

        fake_app = _make_app_state(session_factory)

        with patch("app.gateway.workflows.executor.launch_agent_run_detached", new=AsyncMock(side_effect=RuntimeError("boom"))):
            with patch("app.gateway.workflows.executor.build_run_config", return_value={"configurable": {}}):
                from app.gateway.workflows.executor import execute_workflow_run

                await execute_workflow_run(run_row["id"], app=fake_app)

        after = await repo.get(run_row["id"])
        assert after["status"] == "failed"
        assert "boom" in (after["error_summary"] or "")

    @pytest.mark.asyncio
    async def test_run_error_transitions_to_failed(self, session_factory):
        from omniharness.persistence.workflow_runs.sql import WorkflowRunRepository
        from omniharness.runtime import RunRecord, RunStatus

        wf = await _make_workflow(session_factory)
        run_row = await _make_run(session_factory, wf["id"])
        repo = WorkflowRunRepository(session_factory)

        async def _failing_coro():
            raise RuntimeError("agent crashed")

        fake_task = asyncio.ensure_future(_failing_coro())
        # Wait a tick so the task resolves before executor awaits it
        await asyncio.sleep(0)

        fake_record = MagicMock(spec=RunRecord)
        fake_record.task = fake_task
        fake_record.run_id = str(uuid.uuid4())
        fake_record.status = RunStatus.error

        fake_app = _make_app_state(session_factory)

        with patch("app.gateway.workflows.executor.launch_agent_run_detached", new=AsyncMock(return_value=fake_record)):
            with patch("app.gateway.workflows.executor.build_run_config", return_value={"configurable": {}}):
                from app.gateway.workflows.executor import execute_workflow_run

                await execute_workflow_run(run_row["id"], app=fake_app)

        after = await repo.get(run_row["id"])
        assert after["status"] == "failed"


# ---------------------------------------------------------------------------
# Section 4 — router tests
# ---------------------------------------------------------------------------


def _make_test_app(sf):
    """Build a minimal FastAPI test app wired to an in-memory DB."""
    from omniharness.persistence.workflow_artifact_links.sql import WorkflowArtifactLinkRepository
    from omniharness.persistence.workflow_runs.sql import WorkflowRunRepository
    from omniharness.persistence.workflow_step_runs.sql import WorkflowStepRunRepository
    from omniharness.persistence.workflow_versions.sql import WorkflowVersionRepository
    from omniharness.persistence.workflows.sql import WorkflowRepository

    app = FastAPI()

    # Stub out config
    with patch("omniharness.config.get_app_config") as mock_cfg:
        mock_cfg.return_value.workflows.enabled = True
        app.state.workflow_repo = WorkflowRepository(sf)
        app.state.workflow_version_repo = WorkflowVersionRepository(sf)
        app.state.workflow_run_repo = WorkflowRunRepository(sf)
        app.state.workflow_step_run_repo = WorkflowStepRunRepository(sf)
        app.state.workflow_artifact_link_repo = WorkflowArtifactLinkRepository(sf)
        app.state.stream_bridge = MagicMock()
        app.state.run_manager = MagicMock()
        app.state.run_event_store = None
        app.state.checkpointer = None
        app.state.store = None
        app.state.thread_store = None
        app.state.preview_controller = None
        app.state.config = MagicMock(run_events=None)

    from app.gateway.routers.workflows import router

    app.include_router(router)
    return app


class TestWorkflowRunRouter:
    @pytest_asyncio.fixture
    async def app_and_wf(self, session_factory):
        app = _make_test_app(session_factory)
        wf = await _make_workflow(session_factory)
        return app, wf, session_factory

    def test_post_run_returns_202(self, app_and_wf):
        app, wf, _ = app_and_wf
        with (
            patch("omniharness.config.get_app_config") as mock_cfg,
            patch("app.gateway.routers.workflows.get_effective_user_id", return_value="u1"),
            patch("app.gateway.workflows.executor.execute_workflow_run", new=AsyncMock()),
        ):
            mock_cfg.return_value.workflows.enabled = True
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.post(f"/api/workflows/{wf['id']}/run", json={})
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "queued"
        assert data["workflow_id"] == wf["id"]
        assert data["trigger_type"] == "manual"

    def test_post_run_returns_404_for_unknown_workflow(self, app_and_wf):
        app, _, _ = app_and_wf
        with (
            patch("omniharness.config.get_app_config") as mock_cfg,
            patch("app.gateway.routers.workflows.get_effective_user_id", return_value="u1"),
        ):
            mock_cfg.return_value.workflows.enabled = True
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.post("/api/workflows/does-not-exist/run", json={})
        assert resp.status_code == 404

    def test_two_manual_runs_produce_distinct_run_ids(self, app_and_wf):
        app, wf, _ = app_and_wf
        with (
            patch("omniharness.config.get_app_config") as mock_cfg,
            patch("app.gateway.routers.workflows.get_effective_user_id", return_value="u1"),
            patch("app.gateway.workflows.executor.execute_workflow_run", new=AsyncMock()),
        ):
            mock_cfg.return_value.workflows.enabled = True
            client = TestClient(app, raise_server_exceptions=True)
            r1 = client.post(f"/api/workflows/{wf['id']}/run", json={})
            r2 = client.post(f"/api/workflows/{wf['id']}/run", json={})
        assert r1.status_code == 202
        assert r2.status_code == 202
        assert r1.json()["id"] != r2.json()["id"], "manual runs must never deduplicate"

    def test_list_runs(self, app_and_wf):
        app, wf, _ = app_and_wf
        with (
            patch("omniharness.config.get_app_config") as mock_cfg,
            patch("app.gateway.routers.workflows.get_effective_user_id", return_value="u1"),
            patch("app.gateway.workflows.executor.execute_workflow_run", new=AsyncMock()),
        ):
            mock_cfg.return_value.workflows.enabled = True
            client = TestClient(app, raise_server_exceptions=True)
            client.post(f"/api/workflows/{wf['id']}/run", json={})
            client.post(f"/api/workflows/{wf['id']}/run", json={})
            resp = client.get(f"/api/workflows/{wf['id']}/runs")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_get_single_run(self, app_and_wf):
        app, wf, _ = app_and_wf
        with (
            patch("omniharness.config.get_app_config") as mock_cfg,
            patch("app.gateway.routers.workflows.get_effective_user_id", return_value="u1"),
            patch("app.gateway.workflows.executor.execute_workflow_run", new=AsyncMock()),
        ):
            mock_cfg.return_value.workflows.enabled = True
            client = TestClient(app, raise_server_exceptions=True)
            post_resp = client.post(f"/api/workflows/{wf['id']}/run", json={})
            run_id = post_resp.json()["id"]
            get_resp = client.get(f"/api/workflows/{wf['id']}/runs/{run_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == run_id

    def test_get_run_wrong_workflow_returns_404(self, app_and_wf):
        app, wf, sf = app_and_wf
        # Need a second workflow to test cross-workflow access
        import asyncio as _aio

        wf2 = _aio.get_event_loop().run_until_complete(_make_workflow(sf))
        with (
            patch("omniharness.config.get_app_config") as mock_cfg,
            patch("app.gateway.routers.workflows.get_effective_user_id", return_value="u1"),
            patch("app.gateway.workflows.executor.execute_workflow_run", new=AsyncMock()),
        ):
            mock_cfg.return_value.workflows.enabled = True
            client = TestClient(app, raise_server_exceptions=True)
            # Create run under wf["id"]
            post_resp = client.post(f"/api/workflows/{wf['id']}/run", json={})
            run_id = post_resp.json()["id"]
            # Try to get it under wf2["id"]
            resp = client.get(f"/api/workflows/{wf2['id']}/runs/{run_id}")
        assert resp.status_code == 404
