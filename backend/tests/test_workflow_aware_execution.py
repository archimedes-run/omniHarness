"""Tests for Phase 1 Slice 4b — workflow-aware execution.

Covers:
- _build_workflow_awareness_context: correct framing, steps, risks, no suggested_tools exposure
- execute_workflow_run with spec present: awareness context prepended to HumanMessage content
- execute_workflow_run with spec absent: raw instruction_prompt unchanged (backward compat)
- execute_workflow_run with invalid spec_json: graceful fallback to raw prompt, no exception
- suggested_tools in spec are advisory only — no tool filtering, not passed to launch
- No extra workflow_step_run rows beyond the single coarse step (spec-present)
- GET /api/workflows/{id}/runs/{run_id}: final_summary populated when succeeded + run_id
- GET /api/workflows/{id}/runs/{run_id}: final_summary=None for non-succeeded status
- GET /api/workflows/{id}/runs/{run_id}: final_summary=None when no run_store on app.state
- GET /api/workflows/{id}/runs/{run_id}: final_summary=None when underlying run not found
- GET /api/workflows/{id}/runs/{run_id}: run_store.get raises → final_summary=None (non-fatal)
- Boundary: executor imports WorkflowSpec from app.gateway.workflows.generator, not harness
"""

from __future__ import annotations

import asyncio
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
        import omniharness.persistence.models  # noqa: F401

        await conn.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    yield sf
    await engine.dispose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_valid_spec():
    from app.gateway.workflows.generator import WorkflowSpec, WorkflowSpecStep

    return WorkflowSpec(
        title="ATS Resume Optimizer",
        description="Rewrites a resume to maximize ATS score for a target job description.",
        steps=[
            WorkflowSpecStep(title="Parse resume", description="Extract text from the uploaded PDF.", suggested_tools=["read_file"]),
            WorkflowSpecStep(title="Score resume", description="Run the ATS scoring heuristic.", suggested_tools=["bash"]),
            WorkflowSpecStep(title="Rewrite resume", description="Apply targeted improvements.", suggested_tools=["write_file"]),
        ],
        required_capabilities=["file_io"],
        risks=["May produce inaccurate ATS scores if the heuristic config is stale"],
        approval_policy="draft_only",
    )


async def _make_workflow(sf, *, instruction_prompt: str = "Optimize my resume", spec_json: dict | None = None) -> dict:
    from omniharness.persistence.workflow_versions.sql import WorkflowVersionRepository
    from omniharness.persistence.workflows.sql import WorkflowRepository

    wf_repo = WorkflowRepository(sf)
    ver_repo = WorkflowVersionRepository(sf)

    wf = await wf_repo.create(id=str(uuid.uuid4()), owner_id="u1", title="Resume Wf", instruction_prompt=instruction_prompt)
    vid = str(uuid.uuid4())
    await ver_repo.create(id=vid, workflow_id=wf["id"], version_number=1, instruction_prompt=instruction_prompt)
    wf = await wf_repo.set_current_version(wf["id"], vid) or wf
    if spec_json is not None:
        await ver_repo.set_spec_json(vid, spec_json)
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
        await repo.transition_status(row["id"], status)
        row = await repo.get(row["id"])
    return row


def _make_app_state(sf, *, run_store=None):
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
        stream_bridge=MagicMock(),
        run_manager=MagicMock(),
        run_event_store=None,
        checkpointer=None,
        store=None,
        thread_store=None,
        preview_controller=None,
        config=MagicMock(run_events=None),
        run_store=run_store,
    )
    return types.SimpleNamespace(state=state)


def _make_fake_record(run_id: str | None = None):
    from omniharness.runtime import RunRecord, RunStatus

    task = asyncio.ensure_future(asyncio.sleep(0))
    record = MagicMock(spec=RunRecord)
    record.task = task
    record.run_id = run_id or str(uuid.uuid4())
    record.status = RunStatus.success
    return record


# ---------------------------------------------------------------------------
# Section 1 — _build_workflow_awareness_context helper
# ---------------------------------------------------------------------------


class TestBuildWorkflowAwarenessContext:
    def test_framing_header_present(self):
        from app.gateway.workflows.executor import _build_workflow_awareness_context

        spec = _make_valid_spec()
        ctx = _build_workflow_awareness_context(spec)
        assert "[WORKFLOW EXECUTION CONTEXT]" in ctx
        assert "[END WORKFLOW CONTEXT]" in ctx

    def test_objective_includes_title_and_description(self):
        from app.gateway.workflows.executor import _build_workflow_awareness_context

        spec = _make_valid_spec()
        ctx = _build_workflow_awareness_context(spec)
        assert "ATS Resume Optimizer" in ctx
        assert "maximize ATS score" in ctx

    def test_all_steps_present_in_order(self):
        from app.gateway.workflows.executor import _build_workflow_awareness_context

        spec = _make_valid_spec()
        ctx = _build_workflow_awareness_context(spec)
        assert "1. Parse resume" in ctx
        assert "2. Score resume" in ctx
        assert "3. Rewrite resume" in ctx

    def test_risks_section_present_when_risks_exist(self):
        from app.gateway.workflows.executor import _build_workflow_awareness_context

        spec = _make_valid_spec()
        ctx = _build_workflow_awareness_context(spec)
        assert "RISKS TO AVOID" in ctx
        assert "ATS scores if the heuristic config is stale" in ctx

    def test_no_risks_section_when_risks_empty(self):
        from app.gateway.workflows.executor import _build_workflow_awareness_context
        from app.gateway.workflows.generator import WorkflowSpec, WorkflowSpecStep

        spec = WorkflowSpec(
            title="Simple task",
            description="A straightforward read-only task.",
            steps=[WorkflowSpecStep(title="Read data", description="Fetch data.", suggested_tools=[])],
            required_capabilities=[],
            risks=[],
            approval_policy="execute_low_risk",
        )
        ctx = _build_workflow_awareness_context(spec)
        assert "RISKS TO AVOID" not in ctx

    def test_suggested_tools_not_exposed_in_context(self):
        """suggested_tools is advisory only — must never appear in the injected framing."""
        from app.gateway.workflows.executor import _build_workflow_awareness_context

        spec = _make_valid_spec()
        ctx = _build_workflow_awareness_context(spec)
        # None of the suggested tool names should appear (they are internal metadata)
        assert "read_file" not in ctx
        assert "write_file" not in ctx
        assert "suggested_tools" not in ctx

    def test_autonomy_language_present(self):
        from app.gateway.workflows.executor import _build_workflow_awareness_context

        spec = _make_valid_spec()
        ctx = _build_workflow_awareness_context(spec)
        assert "autonomously" in ctx.lower()
        assert "No human is available" in ctx


# ---------------------------------------------------------------------------
# Section 2 — execute_workflow_run injection
# ---------------------------------------------------------------------------


class TestExecutorInjection:
    @pytest.mark.asyncio
    async def test_spec_present_prepends_awareness_context(self, session_factory):
        """When spec_json is set, HumanMessage content includes awareness framing."""
        spec = _make_valid_spec()
        wf = await _make_workflow(session_factory, spec_json=spec.model_dump())
        run_row = await _make_run(session_factory, wf["id"])

        fake_app = _make_app_state(session_factory)
        captured_inputs = []

        async def _mock_launch(*, bridge, run_mgr, run_ctx, thread_id, graph_input, **kwargs):
            captured_inputs.append(graph_input)
            return _make_fake_record()

        with patch("app.gateway.workflows.executor.launch_agent_run_detached", new=_mock_launch):
            with patch("app.gateway.workflows.executor.build_run_config", return_value={"configurable": {}}):
                from app.gateway.workflows.executor import execute_workflow_run

                await execute_workflow_run(run_row["id"], app=fake_app)

        assert len(captured_inputs) == 1
        content = captured_inputs[0]["messages"][0].content
        assert "[WORKFLOW EXECUTION CONTEXT]" in content
        assert "ATS Resume Optimizer" in content
        assert "Optimize my resume" in content  # original instruction still present

    @pytest.mark.asyncio
    async def test_spec_present_includes_separator(self, session_factory):
        """The separator '---' clearly divides framing from original prompt."""
        spec = _make_valid_spec()
        wf = await _make_workflow(session_factory, spec_json=spec.model_dump())
        run_row = await _make_run(session_factory, wf["id"])

        fake_app = _make_app_state(session_factory)
        captured_inputs = []

        async def _mock_launch(*, bridge, run_mgr, run_ctx, thread_id, graph_input, **kwargs):
            captured_inputs.append(graph_input)
            return _make_fake_record()

        with patch("app.gateway.workflows.executor.launch_agent_run_detached", new=_mock_launch):
            with patch("app.gateway.workflows.executor.build_run_config", return_value={"configurable": {}}):
                from app.gateway.workflows.executor import execute_workflow_run

                await execute_workflow_run(run_row["id"], app=fake_app)

        content = captured_inputs[0]["messages"][0].content
        assert "---" in content

    @pytest.mark.asyncio
    async def test_spec_absent_uses_raw_instruction_prompt(self, session_factory):
        """When no spec_json, HumanMessage content is the raw instruction_prompt unchanged."""
        wf = await _make_workflow(session_factory)  # no spec_json
        run_row = await _make_run(session_factory, wf["id"])

        fake_app = _make_app_state(session_factory)
        captured_inputs = []

        async def _mock_launch(*, bridge, run_mgr, run_ctx, thread_id, graph_input, **kwargs):
            captured_inputs.append(graph_input)
            return _make_fake_record()

        with patch("app.gateway.workflows.executor.launch_agent_run_detached", new=_mock_launch):
            with patch("app.gateway.workflows.executor.build_run_config", return_value={"configurable": {}}):
                from app.gateway.workflows.executor import execute_workflow_run

                await execute_workflow_run(run_row["id"], app=fake_app)

        assert len(captured_inputs) == 1
        content = captured_inputs[0]["messages"][0].content
        assert content == "Optimize my resume"
        assert "[WORKFLOW EXECUTION CONTEXT]" not in content

    @pytest.mark.asyncio
    async def test_invalid_spec_json_falls_back_to_raw_prompt(self, session_factory):
        """Malformed spec_json is caught, logs warning, falls back to raw prompt — no exception."""
        wf = await _make_workflow(session_factory, spec_json={"bad": "data", "no_title": True})
        run_row = await _make_run(session_factory, wf["id"])

        fake_app = _make_app_state(session_factory)
        captured_inputs = []

        async def _mock_launch(*, bridge, run_mgr, run_ctx, thread_id, graph_input, **kwargs):
            captured_inputs.append(graph_input)
            return _make_fake_record()

        with patch("app.gateway.workflows.executor.launch_agent_run_detached", new=_mock_launch):
            with patch("app.gateway.workflows.executor.build_run_config", return_value={"configurable": {}}):
                from app.gateway.workflows.executor import execute_workflow_run

                # Must not raise
                await execute_workflow_run(run_row["id"], app=fake_app)

        assert len(captured_inputs) == 1
        content = captured_inputs[0]["messages"][0].content
        assert content == "Optimize my resume"

    @pytest.mark.asyncio
    async def test_suggested_tools_not_passed_to_launch(self, session_factory):
        """suggested_tools in spec are never forwarded to launch_agent_run_detached as tool filters."""
        spec = _make_valid_spec()
        wf = await _make_workflow(session_factory, spec_json=spec.model_dump())
        run_row = await _make_run(session_factory, wf["id"])

        fake_app = _make_app_state(session_factory)
        captured_kwargs: list[dict] = []

        async def _mock_launch(*, bridge, run_mgr, run_ctx, thread_id, graph_input, **kwargs):
            captured_kwargs.append(kwargs)
            return _make_fake_record()

        with patch("app.gateway.workflows.executor.launch_agent_run_detached", new=_mock_launch):
            with patch("app.gateway.workflows.executor.build_run_config", return_value={"configurable": {}}):
                from app.gateway.workflows.executor import execute_workflow_run

                await execute_workflow_run(run_row["id"], app=fake_app)

        kw = captured_kwargs[0]
        # No tool-filtering key should be present
        assert "tools" not in kw
        assert "allowed_tools" not in kw
        assert "tool_filter" not in kw

    @pytest.mark.asyncio
    async def test_spec_present_still_produces_one_coarse_step_run(self, session_factory):
        """Spec-aware execution keeps Approach A: exactly one workflow_execution step_run."""
        from omniharness.persistence.workflow_step_runs.sql import WorkflowStepRunRepository

        spec = _make_valid_spec()
        wf = await _make_workflow(session_factory, spec_json=spec.model_dump())
        run_row = await _make_run(session_factory, wf["id"])

        fake_app = _make_app_state(session_factory)

        async def _mock_launch(*, bridge, run_mgr, run_ctx, thread_id, graph_input, **kwargs):
            return _make_fake_record()

        with patch("app.gateway.workflows.executor.launch_agent_run_detached", new=_mock_launch):
            with patch("app.gateway.workflows.executor.build_run_config", return_value={"configurable": {}}):
                from app.gateway.workflows.executor import execute_workflow_run

                await execute_workflow_run(run_row["id"], app=fake_app)

        step_repo = WorkflowStepRunRepository(session_factory)
        steps = await step_repo.list_by_run(run_row["id"])
        assert len(steps) == 1
        assert steps[0]["step_key"] == "workflow_execution"
        assert steps[0]["step_index"] == 0


# ---------------------------------------------------------------------------
# Section 3 — GET run-detail: final_summary
# ---------------------------------------------------------------------------


def _make_test_app_with_run_store(sf, run_store=None):
    from omniharness.persistence.workflow_artifact_links.sql import WorkflowArtifactLinkRepository
    from omniharness.persistence.workflow_runs.sql import WorkflowRunRepository
    from omniharness.persistence.workflow_step_runs.sql import WorkflowStepRunRepository
    from omniharness.persistence.workflow_versions.sql import WorkflowVersionRepository
    from omniharness.persistence.workflows.sql import WorkflowRepository

    fastapi_app = FastAPI()
    fastapi_app.state.workflow_repo = WorkflowRepository(sf)
    fastapi_app.state.workflow_version_repo = WorkflowVersionRepository(sf)
    fastapi_app.state.workflow_run_repo = WorkflowRunRepository(sf)
    fastapi_app.state.workflow_step_run_repo = WorkflowStepRunRepository(sf)
    fastapi_app.state.workflow_artifact_link_repo = WorkflowArtifactLinkRepository(sf)
    fastapi_app.state.stream_bridge = MagicMock()
    fastapi_app.state.run_manager = MagicMock()
    fastapi_app.state.run_event_store = None
    fastapi_app.state.checkpointer = None
    fastapi_app.state.store = None
    fastapi_app.state.thread_store = None
    fastapi_app.state.preview_controller = None
    fastapi_app.state.config = MagicMock(run_events=None)
    fastapi_app.state.run_store = run_store  # None by default

    from app.gateway.routers.workflows import router

    fastapi_app.include_router(router)
    return fastapi_app


def _cfg_patch(enabled: bool = True):
    mock = MagicMock()
    mock.workflows.enabled = enabled
    return patch("app.gateway.routers.workflows.get_app_config", return_value=mock)


def _user_patch(user_id: str = "u1"):
    return patch("app.gateway.routers.workflows.get_effective_user_id", return_value=user_id)


class TestFinalSummaryOnRunDetail:
    @pytest.mark.asyncio
    async def test_final_summary_returned_when_succeeded(self, session_factory):
        """GET run-detail: succeeded run with run_id → final_summary from run_store.last_ai_message."""
        wf = await _make_workflow(session_factory)
        run_row = await _make_run(session_factory, wf["id"])

        # Advance to succeeded + set run_id
        from omniharness.persistence.workflow_runs.sql import WorkflowRunRepository

        repo = WorkflowRunRepository(session_factory)
        underlying_run_id = str(uuid.uuid4())
        await repo.transition_status(run_row["id"], "running")
        await repo.set_thread_run(run_row["id"], thread_id=str(uuid.uuid4()), run_id=underlying_run_id)
        await repo.transition_status(run_row["id"], "succeeded")

        mock_run_store = AsyncMock()
        mock_run_store.get = AsyncMock(return_value={"last_ai_message": "I rewrote the resume and improved the ATS score."})

        app = _make_test_app_with_run_store(session_factory, run_store=mock_run_store)

        with _cfg_patch(), _user_patch():
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.get(f"/api/workflows/{wf['id']}/runs/{run_row['id']}")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "succeeded"
        assert data["final_summary"] == "I rewrote the resume and improved the ATS score."

    @pytest.mark.asyncio
    async def test_final_summary_none_for_running_status(self, session_factory):
        """GET run-detail: still-running run → final_summary=None."""
        wf = await _make_workflow(session_factory)
        run_row = await _make_run(session_factory, wf["id"])

        from omniharness.persistence.workflow_runs.sql import WorkflowRunRepository

        repo = WorkflowRunRepository(session_factory)
        await repo.transition_status(run_row["id"], "running")

        mock_run_store = AsyncMock()
        mock_run_store.get = AsyncMock(return_value={"last_ai_message": "Should not be seen"})

        app = _make_test_app_with_run_store(session_factory, run_store=mock_run_store)

        with _cfg_patch(), _user_patch():
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.get(f"/api/workflows/{wf['id']}/runs/{run_row['id']}")

        assert resp.status_code == 200
        assert resp.json()["final_summary"] is None

    @pytest.mark.asyncio
    async def test_final_summary_none_when_no_run_store(self, session_factory):
        """GET run-detail: no run_store on app.state → final_summary=None, no exception."""
        wf = await _make_workflow(session_factory)
        run_row = await _make_run(session_factory, wf["id"])

        from omniharness.persistence.workflow_runs.sql import WorkflowRunRepository

        repo = WorkflowRunRepository(session_factory)
        underlying_run_id = str(uuid.uuid4())
        await repo.transition_status(run_row["id"], "running")
        await repo.set_thread_run(run_row["id"], thread_id=str(uuid.uuid4()), run_id=underlying_run_id)
        await repo.transition_status(run_row["id"], "succeeded")

        app = _make_test_app_with_run_store(session_factory, run_store=None)

        with _cfg_patch(), _user_patch():
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.get(f"/api/workflows/{wf['id']}/runs/{run_row['id']}")

        assert resp.status_code == 200
        assert resp.json()["final_summary"] is None

    @pytest.mark.asyncio
    async def test_final_summary_none_when_underlying_run_not_found(self, session_factory):
        """GET run-detail: run_store.get returns None → final_summary=None."""
        wf = await _make_workflow(session_factory)
        run_row = await _make_run(session_factory, wf["id"])

        from omniharness.persistence.workflow_runs.sql import WorkflowRunRepository

        repo = WorkflowRunRepository(session_factory)
        underlying_run_id = str(uuid.uuid4())
        await repo.transition_status(run_row["id"], "running")
        await repo.set_thread_run(run_row["id"], thread_id=str(uuid.uuid4()), run_id=underlying_run_id)
        await repo.transition_status(run_row["id"], "succeeded")

        mock_run_store = AsyncMock()
        mock_run_store.get = AsyncMock(return_value=None)

        app = _make_test_app_with_run_store(session_factory, run_store=mock_run_store)

        with _cfg_patch(), _user_patch():
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.get(f"/api/workflows/{wf['id']}/runs/{run_row['id']}")

        assert resp.status_code == 200
        assert resp.json()["final_summary"] is None

    @pytest.mark.asyncio
    async def test_final_summary_none_when_run_store_raises(self, session_factory):
        """GET run-detail: run_store.get raises → final_summary=None, request still 200."""
        wf = await _make_workflow(session_factory)
        run_row = await _make_run(session_factory, wf["id"])

        from omniharness.persistence.workflow_runs.sql import WorkflowRunRepository

        repo = WorkflowRunRepository(session_factory)
        underlying_run_id = str(uuid.uuid4())
        await repo.transition_status(run_row["id"], "running")
        await repo.set_thread_run(run_row["id"], thread_id=str(uuid.uuid4()), run_id=underlying_run_id)
        await repo.transition_status(run_row["id"], "succeeded")

        mock_run_store = AsyncMock()
        mock_run_store.get = AsyncMock(side_effect=RuntimeError("db connection lost"))

        app = _make_test_app_with_run_store(session_factory, run_store=mock_run_store)

        with _cfg_patch(), _user_patch():
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.get(f"/api/workflows/{wf['id']}/runs/{run_row['id']}")

        assert resp.status_code == 200
        assert resp.json()["final_summary"] is None

    @pytest.mark.asyncio
    async def test_final_summary_none_when_succeeded_but_no_run_id(self, session_factory):
        """GET run-detail: succeeded with no run_id → final_summary=None (pre-run failure path)."""
        wf = await _make_workflow(session_factory)
        run_row = await _make_run(session_factory, wf["id"])

        from omniharness.persistence.workflow_runs.sql import WorkflowRunRepository

        repo = WorkflowRunRepository(session_factory)
        # Directly transition to succeeded without setting run_id (edge case)
        await repo.transition_status(run_row["id"], "running")
        await repo.transition_status(run_row["id"], "succeeded")

        mock_run_store = AsyncMock()
        mock_run_store.get = AsyncMock(return_value={"last_ai_message": "Unreachable"})

        app = _make_test_app_with_run_store(session_factory, run_store=mock_run_store)

        with _cfg_patch(), _user_patch():
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.get(f"/api/workflows/{wf['id']}/runs/{run_row['id']}")

        assert resp.status_code == 200
        assert resp.json()["final_summary"] is None
        mock_run_store.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_final_summary_field_present_on_non_succeeded(self, session_factory):
        """WorkflowRunResponse always includes final_summary field, even when None."""
        wf = await _make_workflow(session_factory)
        run_row = await _make_run(session_factory, wf["id"])

        app = _make_test_app_with_run_store(session_factory)

        with _cfg_patch(), _user_patch():
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.get(f"/api/workflows/{wf['id']}/runs/{run_row['id']}")

        assert resp.status_code == 200
        assert "final_summary" in resp.json()
        assert resp.json()["final_summary"] is None


# ---------------------------------------------------------------------------
# Section 4 — Backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    @pytest.mark.asyncio
    async def test_spec_absent_run_completes_as_before(self, session_factory):
        """Workflow with no spec_json still runs and transitions to succeeded unchanged."""
        from omniharness.persistence.workflow_runs.sql import WorkflowRunRepository

        wf = await _make_workflow(session_factory)  # no spec
        run_row = await _make_run(session_factory, wf["id"])
        repo = WorkflowRunRepository(session_factory)

        fake_app = _make_app_state(session_factory)

        async def _mock_launch(*, bridge, run_mgr, run_ctx, thread_id, graph_input, **kwargs):
            return _make_fake_record()

        with patch("app.gateway.workflows.executor.launch_agent_run_detached", new=_mock_launch):
            with patch("app.gateway.workflows.executor.build_run_config", return_value={"configurable": {}}):
                from app.gateway.workflows.executor import execute_workflow_run

                await execute_workflow_run(run_row["id"], app=fake_app)

        after = await repo.get(run_row["id"])
        assert after["status"] == "succeeded"

    def test_final_summary_absent_for_spec_absent_run_list(self, session_factory):
        """List-runs response never includes final_summary (only run-detail does)."""
        import asyncio as _aio

        wf = _aio.get_event_loop().run_until_complete(_make_workflow(session_factory))

        app = _make_test_app_with_run_store(session_factory)

        with (
            _cfg_patch(),
            _user_patch(),
            patch("app.gateway.workflows.executor.execute_workflow_run", new=AsyncMock()),
        ):
            client = TestClient(app, raise_server_exceptions=True)
            client.post(f"/api/workflows/{wf['id']}/run", json={})
            resp = client.get(f"/api/workflows/{wf['id']}/runs")

        assert resp.status_code == 200
        # List serialization uses _serialize_run which never sets final_summary
        # (final_summary defaults to None in the model)
        for item in resp.json():
            assert item.get("final_summary") is None


# ---------------------------------------------------------------------------
# Section 5 — Boundary check
# ---------------------------------------------------------------------------


class TestBoundary:
    def test_executor_imports_workflow_spec_from_app_not_harness(self):
        """WorkflowSpec imported into executor must come from app.gateway.workflows.generator."""
        import importlib

        mod = importlib.import_module("app.gateway.workflows.executor")
        spec_cls = getattr(mod, "WorkflowSpec", None)
        assert spec_cls is not None
        assert spec_cls.__module__ == "app.gateway.workflows.generator"

    def test_build_workflow_awareness_context_exported(self):
        from app.gateway.workflows.executor import _build_workflow_awareness_context

        assert callable(_build_workflow_awareness_context)
