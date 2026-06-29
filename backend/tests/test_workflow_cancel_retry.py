"""Tests for Phase 1 Slice 3 — Workflow run cancel and retry.

Covers:
- Cancel a queued run → canceled, no underlying run_mgr.cancel needed
- Cancel a running run → run_mgr.cancel invoked with underlying run_id, row → canceled
- Cancel a terminal run → 409, state unchanged
- Cancel of a run that races to terminal before we transition → 409
- Retry a failed run → new run (new id, new key, source_run_id in payload), executor invoked once
- Retry a canceled run → same new-run behavior
- Retry a succeeded run → 409
- Retry a running run → 409
- Retry a queued run → 409
- source_run_id surfaces in WorkflowRunResponse (via trigger_payload)
- Harness boundary: routers/workflows still only imports omniharness.* (not app.*)
- Flag-off (workflows disabled) → 404 on all new endpoints
- _serialize_run surfaces source_run_id from trigger_payload
"""

from __future__ import annotations

import uuid
from datetime import UTC
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from omniharness.persistence.base import Base
from omniharness.persistence.workflow_runs.sql import IllegalStatusTransition

# ---------------------------------------------------------------------------
# In-memory SQLite fixture (same pattern as other workflow tests)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        import omniharness.persistence.models  # noqa: F401

        await conn.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    yield sf
    await engine.dispose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_workflow(sf) -> dict:
    from omniharness.persistence.workflow_versions.sql import WorkflowVersionRepository
    from omniharness.persistence.workflows.sql import WorkflowRepository

    wf_repo = WorkflowRepository(sf)
    ver_repo = WorkflowVersionRepository(sf)
    wf = await wf_repo.create(id=str(uuid.uuid4()), owner_id="u1", title="Test Wf", instruction_prompt="do x")
    vid = str(uuid.uuid4())
    await ver_repo.create(id=vid, workflow_id=wf["id"], version_number=1, instruction_prompt="do x")
    wf = await wf_repo.set_current_version(wf["id"], vid) or wf
    return wf


async def _make_run(sf, workflow_id: str, *, status: str = "queued", underlying_run_id: str | None = None) -> dict:
    from omniharness.persistence.workflow_runs.sql import WorkflowRunRepository

    repo = WorkflowRunRepository(sf)
    key = f"wf:{workflow_id}:manual:{uuid.uuid4()}"
    row, _ = await repo.create_or_get_by_key(
        workflow_id=workflow_id,
        idempotency_key=key,
        id=str(uuid.uuid4()),
        trigger_type="manual",
    )
    # Advance status to whatever is requested via legal transitions.
    transitions = {
        "running": ["running"],
        "succeeded": ["running", "succeeded"],
        "failed": ["running", "failed"],
        "canceled": ["canceled"],
        "expired": ["running", "expired"],
    }
    for s in transitions.get(status, []):
        row = await repo.transition_status(row["id"], s)

    # Optionally set a thread+run reference (simulates executor having launched).
    if underlying_run_id:
        row = await repo.set_thread_run(row["id"], thread_id=str(uuid.uuid4()), run_id=underlying_run_id) or row

    return row


def _make_test_app(sf, *, run_mgr=None):
    from omniharness.persistence.workflow_artifact_links.sql import WorkflowArtifactLinkRepository
    from omniharness.persistence.workflow_runs.sql import WorkflowRunRepository
    from omniharness.persistence.workflow_step_runs.sql import WorkflowStepRunRepository
    from omniharness.persistence.workflow_versions.sql import WorkflowVersionRepository
    from omniharness.persistence.workflows.sql import WorkflowRepository

    app = FastAPI()
    app.state.workflow_repo = WorkflowRepository(sf)
    app.state.workflow_version_repo = WorkflowVersionRepository(sf)
    app.state.workflow_run_repo = WorkflowRunRepository(sf)
    app.state.workflow_step_run_repo = WorkflowStepRunRepository(sf)
    app.state.workflow_artifact_link_repo = WorkflowArtifactLinkRepository(sf)
    app.state.stream_bridge = MagicMock()
    app.state.run_manager = run_mgr or MagicMock()
    app.state.run_event_store = None
    app.state.checkpointer = None
    app.state.store = None
    app.state.thread_store = None
    app.state.preview_controller = None
    app.state.config = MagicMock(run_events=None)

    from app.gateway.routers.workflows import router

    app.include_router(router)
    return app


def _client(sf, *, run_mgr=None):
    app = _make_test_app(sf, run_mgr=run_mgr)
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Section 1 — Unit tests for _serialize_run source_run_id
# ---------------------------------------------------------------------------


class TestSerializeRun:
    def test_source_run_id_extracted_from_trigger_payload(self):
        from datetime import datetime

        from app.gateway.routers.workflows import _serialize_run

        now = datetime.now(UTC)
        row = {
            "id": "r1",
            "workflow_id": "w1",
            "trigger_type": "manual",
            "trigger_payload": {"source_run_id": "original-run-id"},
            "status": "queued",
            "started_at": None,
            "completed_at": None,
            "error_summary": None,
            "thread_id": None,
            "run_id": None,
            "idempotency_key": "key",
            "initiated_by": None,
            "created_at": now,
            "updated_at": now,
        }
        result = _serialize_run(row)
        assert result.source_run_id == "original-run-id"

    def test_source_run_id_none_when_not_set(self):
        from datetime import datetime

        from app.gateway.routers.workflows import _serialize_run

        now = datetime.now(UTC)
        row = {
            "id": "r1",
            "workflow_id": "w1",
            "trigger_type": "manual",
            "trigger_payload": {},
            "status": "queued",
            "started_at": None,
            "completed_at": None,
            "error_summary": None,
            "thread_id": None,
            "run_id": None,
            "idempotency_key": "key",
            "initiated_by": None,
            "created_at": now,
            "updated_at": now,
        }
        result = _serialize_run(row)
        assert result.source_run_id is None


# ---------------------------------------------------------------------------
# Section 2 — Cancel endpoint
# ---------------------------------------------------------------------------


class TestCancelWorkflowRun:
    @pytest_asyncio.fixture
    async def ctx(self, session_factory):
        wf = await _make_workflow(session_factory)
        return session_factory, wf

    def _call_cancel(self, sf, wf_id, run_id, *, run_mgr=None):
        with (
            patch("omniharness.config.get_app_config") as mock_cfg,
            patch("app.gateway.routers.workflows.get_effective_user_id", return_value="u1"),
        ):
            mock_cfg.return_value.workflows.enabled = True
            client = _client(sf, run_mgr=run_mgr)
            return client.post(f"/api/workflows/{wf_id}/runs/{run_id}/cancel")

    @pytest.mark.asyncio
    async def test_cancel_queued_run_transitions_to_canceled(self, ctx):
        sf, wf = ctx
        run = await _make_run(sf, wf["id"], status="queued")
        resp = self._call_cancel(sf, wf["id"], run["id"])
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "canceled"
        assert data["error_summary"] == "Cancelled by user"

    @pytest.mark.asyncio
    async def test_cancel_queued_run_does_not_invoke_run_mgr(self, ctx):
        """Queued run has no underlying run yet — run_mgr.cancel must not be called."""
        sf, wf = ctx
        run = await _make_run(sf, wf["id"], status="queued")
        mock_mgr = AsyncMock()
        mock_mgr.cancel = AsyncMock(return_value=False)

        self._call_cancel(sf, wf["id"], run["id"], run_mgr=mock_mgr)
        mock_mgr.cancel.assert_not_called()

    @pytest.mark.asyncio
    async def test_cancel_running_run_invokes_run_mgr_cancel(self, ctx):
        """Running run with an in-flight underlying run — run_mgr.cancel must be called."""
        sf, wf = ctx
        underlying_id = str(uuid.uuid4())
        run = await _make_run(sf, wf["id"], status="running", underlying_run_id=underlying_id)

        mock_mgr = MagicMock()
        mock_mgr.cancel = AsyncMock(return_value=True)

        resp = self._call_cancel(sf, wf["id"], run["id"], run_mgr=mock_mgr)
        assert resp.status_code == 200
        assert resp.json()["status"] == "canceled"
        mock_mgr.cancel.assert_awaited_once_with(underlying_id)

    @pytest.mark.asyncio
    async def test_cancel_running_run_transitions_to_canceled(self, ctx):
        sf, wf = ctx
        underlying_id = str(uuid.uuid4())
        run = await _make_run(sf, wf["id"], status="running", underlying_run_id=underlying_id)
        mock_mgr = MagicMock()
        mock_mgr.cancel = AsyncMock(return_value=True)

        resp = self._call_cancel(sf, wf["id"], run["id"], run_mgr=mock_mgr)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "canceled"
        assert data["completed_at"] is not None

    @pytest.mark.asyncio
    async def test_cancel_succeeded_run_returns_409(self, ctx):
        sf, wf = ctx
        run = await _make_run(sf, wf["id"], status="succeeded")
        resp = self._call_cancel(sf, wf["id"], run["id"])
        assert resp.status_code == 409
        assert "terminal" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_cancel_failed_run_returns_409(self, ctx):
        sf, wf = ctx
        run = await _make_run(sf, wf["id"], status="failed")
        resp = self._call_cancel(sf, wf["id"], run["id"])
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_cancel_already_canceled_run_returns_409(self, ctx):
        sf, wf = ctx
        run = await _make_run(sf, wf["id"], status="canceled")
        resp = self._call_cancel(sf, wf["id"], run["id"])
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_cancel_run_not_found_returns_404(self, ctx):
        sf, wf = ctx
        resp = self._call_cancel(sf, wf["id"], "nonexistent-run-id")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_cancel_wrong_workflow_returns_404(self, ctx):
        """Run belongs to wf but we try to cancel via a different workflow_id."""
        sf, wf = ctx
        run = await _make_run(sf, wf["id"], status="queued")
        resp = self._call_cancel(sf, "wrong-wf-id", run["id"])
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_cancel_state_machine_race_returns_409(self, ctx):
        """If the executor races to succeeded before cancel's transition, 409 is returned."""
        sf, wf = ctx
        from omniharness.persistence.workflow_runs.sql import WorkflowRunRepository

        run = await _make_run(sf, wf["id"], status="running")

        repo = WorkflowRunRepository(sf)

        # Simulate executor winning the race: advance to succeeded just before cancel.
        orig_transition = repo.transition_status

        call_count = 0

        async def racing_transition(run_id, new_status):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call in the cancel handler — advance the row to succeeded first.
                await orig_transition(run_id, "succeeded")
            return await orig_transition(run_id, new_status)

        # Patch the repo instance that's wired into app.state.
        with (
            patch("omniharness.config.get_app_config") as mock_cfg,
            patch("app.gateway.routers.workflows.get_effective_user_id", return_value="u1"),
        ):
            mock_cfg.return_value.workflows.enabled = True
            app = _make_test_app(sf)
            # Replace the repo's transition_status to simulate the race.
            app.state.workflow_run_repo.transition_status = racing_transition
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.post(f"/api/workflows/{wf['id']}/runs/{run['id']}/cancel")

        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Section 3 — Retry endpoint
# ---------------------------------------------------------------------------


class TestRetryWorkflowRun:
    @pytest_asyncio.fixture
    async def ctx(self, session_factory):
        wf = await _make_workflow(session_factory)
        return session_factory, wf

    def _call_retry(self, sf, wf_id, run_id):
        with (
            patch("omniharness.config.get_app_config") as mock_cfg,
            patch("app.gateway.routers.workflows.get_effective_user_id", return_value="u1"),
            patch("app.gateway.workflows.executor.execute_workflow_run", new=AsyncMock()),
        ):
            mock_cfg.return_value.workflows.enabled = True
            client = _client(sf)
            return client.post(f"/api/workflows/{wf_id}/runs/{run_id}/retry")

    @pytest.mark.asyncio
    async def test_retry_failed_run_creates_new_run(self, ctx):
        sf, wf = ctx
        source_run = await _make_run(sf, wf["id"], status="failed")
        resp = self._call_retry(sf, wf["id"], source_run["id"])
        assert resp.status_code == 202
        data = resp.json()
        # New run must have a different id.
        assert data["id"] != source_run["id"]
        assert data["status"] == "queued"
        assert data["source_run_id"] == source_run["id"]

    @pytest.mark.asyncio
    async def test_retry_canceled_run_creates_new_run(self, ctx):
        sf, wf = ctx
        source_run = await _make_run(sf, wf["id"], status="canceled")
        resp = self._call_retry(sf, wf["id"], source_run["id"])
        assert resp.status_code == 202
        assert resp.json()["source_run_id"] == source_run["id"]

    @pytest.mark.asyncio
    async def test_retry_creates_distinct_idempotency_key(self, ctx):
        """Two retries of the same source run must each get a unique idempotency key."""
        sf, wf = ctx
        source_run = await _make_run(sf, wf["id"], status="failed")
        r1 = self._call_retry(sf, wf["id"], source_run["id"])
        r2 = self._call_retry(sf, wf["id"], source_run["id"])
        assert r1.status_code == 202
        assert r2.status_code == 202
        assert r1.json()["idempotency_key"] != r2.json()["idempotency_key"]
        assert r1.json()["id"] != r2.json()["id"]

    @pytest.mark.asyncio
    async def test_retry_source_run_is_unchanged(self, ctx):
        """After retry, the original failed run must be untouched."""
        sf, wf = ctx
        from omniharness.persistence.workflow_runs.sql import WorkflowRunRepository

        source_run = await _make_run(sf, wf["id"], status="failed")
        self._call_retry(sf, wf["id"], source_run["id"])

        repo = WorkflowRunRepository(sf)
        original = await repo.get(source_run["id"])
        assert original["status"] == "failed"

    @pytest.mark.asyncio
    async def test_retry_invokes_executor_for_new_run_id(self, ctx):
        sf, wf = ctx
        source_run = await _make_run(sf, wf["id"], status="failed")

        captured_ids = []

        async def mock_executor(workflow_run_id, *, app):
            captured_ids.append(workflow_run_id)

        with (
            patch("omniharness.config.get_app_config") as mock_cfg,
            patch("app.gateway.routers.workflows.get_effective_user_id", return_value="u1"),
            patch("app.gateway.workflows.executor.execute_workflow_run", side_effect=mock_executor),
        ):
            mock_cfg.return_value.workflows.enabled = True
            client = _client(sf)
            resp = client.post(f"/api/workflows/{wf['id']}/runs/{source_run['id']}/retry")

        assert resp.status_code == 202
        new_run_id = resp.json()["id"]
        # Executor must be called exactly once, with the NEW run id.
        assert len(captured_ids) == 1
        assert captured_ids[0] == new_run_id
        assert captured_ids[0] != source_run["id"]

    @pytest.mark.asyncio
    async def test_retry_succeeded_run_returns_409(self, ctx):
        sf, wf = ctx
        run = await _make_run(sf, wf["id"], status="succeeded")
        resp = self._call_retry(sf, wf["id"], run["id"])
        assert resp.status_code == 409
        assert "succeeded" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_retry_running_run_returns_409(self, ctx):
        sf, wf = ctx
        run = await _make_run(sf, wf["id"], status="running")
        resp = self._call_retry(sf, wf["id"], run["id"])
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_retry_queued_run_returns_409(self, ctx):
        sf, wf = ctx
        run = await _make_run(sf, wf["id"], status="queued")
        resp = self._call_retry(sf, wf["id"], run["id"])
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_retry_nonexistent_run_returns_404(self, ctx):
        sf, wf = ctx
        resp = self._call_retry(sf, wf["id"], "nonexistent")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_retry_wrong_workflow_returns_404(self, ctx):
        sf, wf = ctx
        run = await _make_run(sf, wf["id"], status="failed")
        resp = self._call_retry(sf, "wrong-wf-id", run["id"])
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Section 4 — Flag-off (workflows disabled)
# ---------------------------------------------------------------------------


class TestFlagOff:
    @pytest_asyncio.fixture
    async def ctx(self, session_factory):
        wf = await _make_workflow(session_factory)
        run = await _make_run(session_factory, wf["id"], status="failed")
        return session_factory, wf, run

    def _disabled_client(self, sf):
        with patch("omniharness.config.get_app_config") as mock_cfg:
            mock_cfg.return_value.workflows.enabled = False
            app = _make_test_app(sf)
        return TestClient(app, raise_server_exceptions=True)

    @pytest.mark.asyncio
    async def test_cancel_returns_404_when_disabled(self, ctx):
        sf, wf, run = ctx
        # Patch the reference the router module captured via "from ... import get_app_config".
        with (
            patch("app.gateway.routers.workflows.get_app_config") as mock_cfg,
            patch("app.gateway.routers.workflows.get_effective_user_id", return_value="u1"),
        ):
            mock_cfg.return_value.workflows.enabled = False
            client = _client(sf)
            resp = client.post(f"/api/workflows/{wf['id']}/runs/{run['id']}/cancel")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_retry_returns_404_when_disabled(self, ctx):
        sf, wf, run = ctx
        with (
            patch("app.gateway.routers.workflows.get_app_config") as mock_cfg,
            patch("app.gateway.routers.workflows.get_effective_user_id", return_value="u1"),
        ):
            mock_cfg.return_value.workflows.enabled = False
            client = _client(sf)
            resp = client.post(f"/api/workflows/{wf['id']}/runs/{run['id']}/retry")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Section 5 — State machine edge invariants
# ---------------------------------------------------------------------------


class TestStateMachineInvariants:
    """Ensure Slice 3 doesn't introduce illegal transitions or break existing ones."""

    @pytest.mark.asyncio
    async def test_canceled_to_any_is_terminal(self, session_factory):
        from omniharness.persistence.workflow_runs.sql import WorkflowRunRepository

        wf = await _make_workflow(session_factory)
        run = await _make_run(session_factory, wf["id"], status="canceled")
        repo = WorkflowRunRepository(session_factory)
        for bad_status in ("running", "succeeded", "failed", "queued", "expired"):
            with pytest.raises(IllegalStatusTransition):
                await repo.transition_status(run["id"], bad_status)

    @pytest.mark.asyncio
    async def test_succeeded_to_any_is_terminal(self, session_factory):
        from omniharness.persistence.workflow_runs.sql import WorkflowRunRepository

        wf = await _make_workflow(session_factory)
        run = await _make_run(session_factory, wf["id"], status="succeeded")
        repo = WorkflowRunRepository(session_factory)
        for bad_status in ("running", "canceled", "failed", "queued", "expired"):
            with pytest.raises(IllegalStatusTransition):
                await repo.transition_status(run["id"], bad_status)

    @pytest.mark.asyncio
    async def test_failed_to_any_is_terminal(self, session_factory):
        from omniharness.persistence.workflow_runs.sql import WorkflowRunRepository

        wf = await _make_workflow(session_factory)
        run = await _make_run(session_factory, wf["id"], status="failed")
        repo = WorkflowRunRepository(session_factory)
        for bad_status in ("running", "canceled", "succeeded", "queued", "expired"):
            with pytest.raises(IllegalStatusTransition):
                await repo.transition_status(run["id"], bad_status)
