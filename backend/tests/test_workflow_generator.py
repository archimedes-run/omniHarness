"""Tests for Phase 1 Slice 4a — Workflow spec generator.

Covers:
- WorkflowSpec schema: valid parse, empty-title rejection, zero-steps rejection,
  bad approval_policy rejection
- generate_workflow_spec(): valid model output, retry on first failure, persistent
  failure → WorkflowGenerationError, timeout → WorkflowGenerationError
- POST /api/workflows/{id}/generate: valid flow (stores + returns spec),
  no-instruction → 409, model failure → 422, regenerate overwrites prior spec
- GET /api/workflows/{id}: spec_json surfaced after generation
- Generation does NOT invoke the run pipeline (no thread/run created)
- Flag-off → 404; ownership rejection → 404
- Harness boundary: router imports generator from app.*, not harness.*
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from omniharness.persistence.base import Base

# ---------------------------------------------------------------------------
# Fixtures
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


async def _make_workflow(sf, *, instruction_prompt: str | None = "Send a weekly summary email") -> dict:
    from omniharness.persistence.workflow_versions.sql import WorkflowVersionRepository
    from omniharness.persistence.workflows.sql import WorkflowRepository

    wf_repo = WorkflowRepository(sf)
    ver_repo = WorkflowVersionRepository(sf)

    wf = await wf_repo.create(
        id=str(uuid.uuid4()),
        owner_id="u1",
        title="Test Workflow",
        instruction_prompt=instruction_prompt,
    )
    if instruction_prompt:
        vid = str(uuid.uuid4())
        await ver_repo.create(
            id=vid,
            workflow_id=wf["id"],
            version_number=1,
            instruction_prompt=instruction_prompt,
        )
        wf = await wf_repo.set_current_version(wf["id"], vid) or wf
    return wf


def _make_test_app(sf):
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


def _client(sf):
    return TestClient(_make_test_app(sf), raise_server_exceptions=True)


def _mock_generate(spec):
    """Patch generate_workflow_spec to return spec without calling the LLM."""
    return patch(
        "app.gateway.routers.workflows.generate_workflow_spec",
        new=AsyncMock(return_value=spec),
    )


def _cfg_patch(*, enabled: bool = True):
    mock = MagicMock()
    mock.workflows.enabled = enabled
    return patch("app.gateway.routers.workflows.get_app_config", return_value=mock)


def _user_patch(user_id: str = "u1"):
    return patch("app.gateway.routers.workflows.get_effective_user_id", return_value=user_id)


def _make_valid_spec():
    from app.gateway.workflows.generator import WorkflowSpec, WorkflowSpecStep

    return WorkflowSpec(
        title="Weekly Summary Email",
        description="Compiles and sends a weekly summary email to stakeholders.",
        steps=[
            WorkflowSpecStep(
                title="Gather data",
                description="Pull metrics from the data warehouse.",
                suggested_tools=["bash"],
            ),
            WorkflowSpecStep(
                title="Send email",
                description="Format and dispatch the summary via SMTP.",
                suggested_tools=["bash"],
            ),
        ],
        required_capabilities=["network_access"],
        risks=["Email sent to wrong recipients if config is wrong"],
        approval_policy="approval_required",
    )


# ---------------------------------------------------------------------------
# Section 1 — WorkflowSpec schema validation
# ---------------------------------------------------------------------------


class TestWorkflowSpecSchema:
    def test_valid_spec_parses(self):
        spec = _make_valid_spec()
        assert spec.title == "Weekly Summary Email"
        assert len(spec.steps) == 2
        assert spec.approval_policy == "approval_required"

    def test_empty_title_rejected(self):
        from app.gateway.workflows.generator import WorkflowSpec, WorkflowSpecStep

        with pytest.raises(ValidationError):
            WorkflowSpec(
                title="",
                description="d",
                steps=[WorkflowSpecStep(title="s", description="d", suggested_tools=[])],
                approval_policy="draft_only",
            )

    def test_zero_steps_rejected(self):
        from app.gateway.workflows.generator import WorkflowSpec

        with pytest.raises(ValidationError):
            WorkflowSpec(
                title="Valid title",
                description="d",
                steps=[],
                approval_policy="draft_only",
            )

    def test_bad_approval_policy_rejected(self):
        from app.gateway.workflows.generator import WorkflowSpec, WorkflowSpecStep

        with pytest.raises(ValidationError):
            WorkflowSpec(
                title="Valid",
                description="d",
                steps=[WorkflowSpecStep(title="s", description="d", suggested_tools=[])],
                approval_policy="auto_approve",  # not in Literal
            )

    def test_suggested_tools_defaults_to_empty(self):
        from app.gateway.workflows.generator import WorkflowSpecStep

        step = WorkflowSpecStep(title="s", description="d")
        assert step.suggested_tools == []

    def test_optional_lists_default_empty(self):
        from app.gateway.workflows.generator import WorkflowSpec, WorkflowSpecStep

        spec = WorkflowSpec(
            title="t",
            description="d",
            steps=[WorkflowSpecStep(title="s", description="d")],
            approval_policy="draft_only",
        )
        assert spec.required_capabilities == []
        assert spec.risks == []


# ---------------------------------------------------------------------------
# Section 2 — generate_workflow_spec() unit tests (no FastAPI, no HTTP)
# ---------------------------------------------------------------------------


class TestGenerateWorkflowSpec:
    def _make_mock_model(self, return_value=None, side_effects=None):
        """Return a mock create_chat_model that produces structured output."""
        mock_model = MagicMock()
        mock_runnable = MagicMock()
        mock_model.with_structured_output.return_value = mock_runnable
        if side_effects is not None:
            mock_runnable.ainvoke = AsyncMock(side_effect=side_effects)
        else:
            mock_runnable.ainvoke = AsyncMock(return_value=return_value)
        return mock_model

    @pytest.mark.asyncio
    async def test_valid_model_output_returns_spec(self):
        from app.gateway.workflows.generator import generate_workflow_spec

        spec = _make_valid_spec()
        mock_model = self._make_mock_model(return_value=spec)

        with patch("app.gateway.workflows.generator.create_chat_model", return_value=mock_model):
            result = await generate_workflow_spec("Send weekly summary email")

        assert result is spec
        assert mock_model.with_structured_output.called
        # ainvoke called exactly once (no retry needed)
        assert mock_model.with_structured_output.return_value.ainvoke.call_count == 1

    @pytest.mark.asyncio
    async def test_first_failure_retries_once_then_succeeds(self):
        from app.gateway.workflows.generator import generate_workflow_spec

        spec = _make_valid_spec()
        mock_model = self._make_mock_model(side_effects=[ValueError("parse error"), spec])

        with patch("app.gateway.workflows.generator.create_chat_model", return_value=mock_model):
            result = await generate_workflow_spec("do something")

        assert result is spec
        assert mock_model.with_structured_output.return_value.ainvoke.call_count == 2

    @pytest.mark.asyncio
    async def test_persistent_failure_raises_typed_error(self):
        from app.gateway.workflows.generator import WorkflowGenerationError, generate_workflow_spec

        mock_model = self._make_mock_model(side_effects=[ValueError("bad json"), ValueError("still bad")])

        with patch("app.gateway.workflows.generator.create_chat_model", return_value=mock_model):
            with pytest.raises(WorkflowGenerationError) as exc_info:
                await generate_workflow_spec("do something")

        assert "2 attempts" in str(exc_info.value)
        assert mock_model.with_structured_output.return_value.ainvoke.call_count == 2

    @pytest.mark.asyncio
    async def test_timeout_raises_typed_error_without_retry(self):
        from app.gateway.workflows.generator import WorkflowGenerationError, generate_workflow_spec

        call_count = 0

        async def _slow(*_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(1000)

        mock_model = self._make_mock_model()
        mock_model.with_structured_output.return_value.ainvoke = _slow

        with patch("app.gateway.workflows.generator.create_chat_model", return_value=mock_model):
            with patch("app.gateway.workflows.generator._GENERATION_TIMEOUT_SECONDS", 0.01):
                with pytest.raises(WorkflowGenerationError) as exc_info:
                    await generate_workflow_spec("do something")

        assert "timed out" in str(exc_info.value).lower()
        # Only one attempt before timeout — no retry on timeouts
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_wrong_return_type_triggers_retry(self):
        """If the model returns something other than WorkflowSpec, retry."""
        from app.gateway.workflows.generator import WorkflowGenerationError, generate_workflow_spec

        mock_model = self._make_mock_model(side_effects=[{"wrong": "type"}, {"still": "wrong"}])

        with patch("app.gateway.workflows.generator.create_chat_model", return_value=mock_model):
            with pytest.raises(WorkflowGenerationError):
                await generate_workflow_spec("do something")

        assert mock_model.with_structured_output.return_value.ainvoke.call_count == 2

    @pytest.mark.asyncio
    async def test_no_thread_run_or_sandbox_created(self):
        """Generation must not touch the run pipeline at all."""
        from app.gateway.workflows.generator import generate_workflow_spec

        spec = _make_valid_spec()
        mock_model = self._make_mock_model(return_value=spec)

        launch_mock = MagicMock()
        execute_mock = MagicMock()

        with (
            patch("app.gateway.workflows.generator.create_chat_model", return_value=mock_model),
            patch("app.gateway.services.launch_agent_run_detached", launch_mock),
            patch("app.gateway.workflows.executor.execute_workflow_run", execute_mock),
        ):
            await generate_workflow_spec("do something")

        launch_mock.assert_not_called()
        execute_mock.assert_not_called()


# ---------------------------------------------------------------------------
# Section 3 — POST /api/workflows/{id}/generate endpoint
# ---------------------------------------------------------------------------


class TestGenerateEndpoint:
    @pytest.mark.asyncio
    async def test_valid_generate_returns_spec_and_stores_it(self, session_factory):
        wf = await _make_workflow(session_factory)
        spec = _make_valid_spec()

        with _cfg_patch(), _user_patch(), _mock_generate(spec):
            resp = _client(session_factory).post(f"/api/workflows/{wf['id']}/generate")

        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == spec.title
        assert len(data["steps"]) == 2
        assert data["approval_policy"] == "approval_required"

        # Confirm stored on the version
        from omniharness.persistence.workflow_versions.sql import WorkflowVersionRepository

        ver_repo = WorkflowVersionRepository(session_factory)
        version = await ver_repo.get(wf["current_version_id"])
        assert version is not None
        assert version["spec_json"] is not None
        assert version["spec_json"]["title"] == spec.title

    @pytest.mark.asyncio
    async def test_no_instruction_returns_409_no_model_call(self, session_factory):
        # Workflow with no instruction_prompt → no current_version_id
        from omniharness.persistence.workflows.sql import WorkflowRepository

        repo = WorkflowRepository(session_factory)
        wf = await repo.create(
            id=str(uuid.uuid4()),
            owner_id="u1",
            title="Empty",
        )

        generate_mock = AsyncMock()
        with _cfg_patch(), _user_patch(), patch("app.gateway.routers.workflows.generate_workflow_spec", generate_mock):
            resp = _client(session_factory).post(f"/api/workflows/{wf['id']}/generate")

        assert resp.status_code == 409
        assert "no instruction" in resp.json()["detail"].lower()
        generate_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_instruction_returns_409_no_model_call(self, session_factory):
        wf = await _make_workflow(session_factory, instruction_prompt="")

        generate_mock = AsyncMock()
        with _cfg_patch(), _user_patch(), patch("app.gateway.routers.workflows.generate_workflow_spec", generate_mock):
            resp = _client(session_factory).post(f"/api/workflows/{wf['id']}/generate")

        assert resp.status_code == 409
        generate_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_model_failure_returns_422_stores_nothing(self, session_factory):
        from app.gateway.workflows.generator import WorkflowGenerationError

        wf = await _make_workflow(session_factory)

        failing_generate = AsyncMock(side_effect=WorkflowGenerationError("Model returned invalid spec after 2 attempts: ValueError"))
        with _cfg_patch(), _user_patch(), patch("app.gateway.routers.workflows.generate_workflow_spec", failing_generate):
            resp = _client(session_factory).post(f"/api/workflows/{wf['id']}/generate")

        assert resp.status_code == 422
        assert "2 attempts" in resp.json()["detail"]

        # spec_json must remain None — nothing stored
        from omniharness.persistence.workflow_versions.sql import WorkflowVersionRepository

        ver_repo = WorkflowVersionRepository(session_factory)
        version = await ver_repo.get(wf["current_version_id"])
        assert version["spec_json"] is None

    @pytest.mark.asyncio
    async def test_regenerate_overwrites_prior_spec(self, session_factory):
        from app.gateway.workflows.generator import WorkflowSpec, WorkflowSpecStep

        wf = await _make_workflow(session_factory)

        spec_v1 = _make_valid_spec()
        spec_v2 = WorkflowSpec(
            title="Revised spec",
            description="Updated after regeneration.",
            steps=[WorkflowSpecStep(title="Only step", description="Do the thing.", suggested_tools=[])],
            approval_policy="draft_only",
        )

        client = _client(session_factory)
        with _cfg_patch(), _user_patch(), _mock_generate(spec_v1):
            r1 = client.post(f"/api/workflows/{wf['id']}/generate")
        assert r1.status_code == 200
        assert r1.json()["title"] == spec_v1.title

        with _cfg_patch(), _user_patch(), _mock_generate(spec_v2):
            r2 = client.post(f"/api/workflows/{wf['id']}/generate")
        assert r2.status_code == 200
        assert r2.json()["title"] == "Revised spec"

        # DB reflects v2 — same current_version row, no new version created
        from omniharness.persistence.workflow_versions.sql import WorkflowVersionRepository

        ver_repo = WorkflowVersionRepository(session_factory)
        all_versions = await ver_repo.list_by_workflow(wf["id"])
        assert len(all_versions) == 1, "Regenerate must NOT create a new version row"
        assert all_versions[0]["spec_json"]["title"] == "Revised spec"

    @pytest.mark.asyncio
    async def test_wrong_owner_returns_404(self, session_factory):
        wf = await _make_workflow(session_factory)
        spec = _make_valid_spec()

        with _cfg_patch(), patch("app.gateway.routers.workflows.get_effective_user_id", return_value="OTHER"), _mock_generate(spec):
            resp = _client(session_factory).post(f"/api/workflows/{wf['id']}/generate")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_flag_off_returns_404(self, session_factory):
        wf = await _make_workflow(session_factory)

        with _cfg_patch(enabled=False), _user_patch():
            resp = _client(session_factory).post(f"/api/workflows/{wf['id']}/generate")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_run_pipeline_never_invoked(self, session_factory):
        """Generating a spec must not touch execute_workflow_run or launch_agent_run_detached."""
        wf = await _make_workflow(session_factory)
        spec = _make_valid_spec()

        execute_mock = MagicMock()
        launch_mock = MagicMock()

        with (
            _cfg_patch(),
            _user_patch(),
            _mock_generate(spec),
            patch("app.gateway.workflows.executor.execute_workflow_run", execute_mock),
            patch("app.gateway.services.launch_agent_run_detached", launch_mock),
        ):
            resp = _client(session_factory).post(f"/api/workflows/{wf['id']}/generate")

        assert resp.status_code == 200
        execute_mock.assert_not_called()
        launch_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_manager_never_invoked(self, session_factory):
        """run_manager must stay untouched during generation."""
        wf = await _make_workflow(session_factory)
        spec = _make_valid_spec()

        app = _make_test_app(session_factory)
        run_mgr_mock = MagicMock()
        app.state.run_manager = run_mgr_mock
        client = TestClient(app, raise_server_exceptions=True)

        with _cfg_patch(), _user_patch(), _mock_generate(spec):
            resp = client.post(f"/api/workflows/{wf['id']}/generate")

        assert resp.status_code == 200
        run_mgr_mock.cancel.assert_not_called()


# ---------------------------------------------------------------------------
# Section 4 — GET /api/workflows/{id} surfaces spec_json
# ---------------------------------------------------------------------------


class TestGetWorkflowSurfacesSpec:
    @pytest.mark.asyncio
    async def test_spec_json_is_none_before_generation(self, session_factory):
        wf = await _make_workflow(session_factory)

        with _cfg_patch(), _user_patch():
            resp = _client(session_factory).get(f"/api/workflows/{wf['id']}")

        assert resp.status_code == 200
        assert resp.json()["spec_json"] is None

    @pytest.mark.asyncio
    async def test_spec_json_surfaced_after_generation(self, session_factory):
        wf = await _make_workflow(session_factory)
        spec = _make_valid_spec()

        client = _client(session_factory)
        with _cfg_patch(), _user_patch(), _mock_generate(spec):
            client.post(f"/api/workflows/{wf['id']}/generate")

        with _cfg_patch(), _user_patch():
            resp = client.get(f"/api/workflows/{wf['id']}")

        assert resp.status_code == 200
        data = resp.json()
        assert data["spec_json"] is not None
        assert data["spec_json"]["title"] == spec.title
        assert len(data["spec_json"]["steps"]) == 2


# ---------------------------------------------------------------------------
# Section 5 — Harness boundary and module structure
# ---------------------------------------------------------------------------


class TestBoundaryAndStructure:
    def test_generator_importable_without_app_config(self):
        """Generator must be importable without a live config (model not called at import)."""
        import importlib

        mod = importlib.import_module("app.gateway.workflows.generator")
        assert hasattr(mod, "WorkflowSpec")
        assert hasattr(mod, "generate_workflow_spec")
        assert hasattr(mod, "WorkflowGenerationError")

    def test_generator_does_not_import_from_app_routers(self):
        """generator.py must not import from app.gateway.routers.* (no circular dep)."""
        import sys

        mod = sys.modules.get("app.gateway.workflows.generator")
        if mod is None:
            import importlib

            mod = importlib.import_module("app.gateway.workflows.generator")
        src = mod.__file__ or ""
        # Read source and check for router import
        with open(src) as f:
            source = f.read()
        assert "from app.gateway.routers" not in source
        assert "import app.gateway.routers" not in source

    def test_router_workflow_spec_import_comes_from_generator(self):
        """The WorkflowSpec used in the router is the same class from generator.py."""
        from app.gateway.routers.workflows import WorkflowSpec as RouterSpec
        from app.gateway.workflows.generator import WorkflowSpec as GenSpec

        assert RouterSpec is GenSpec

    def test_harness_boundary_still_green(self):
        """omniharness.* must never import from app.* — verify generator.py doesn't break this."""
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/test_harness_boundary.py", "-q", "--tb=short"],
            capture_output=True,
            text=True,
            cwd="/Users/rishabh.sharma/Documents/GitHub/omniHarness/backend",
        )
        assert result.returncode == 0, f"Harness boundary test failed:\n{result.stdout}\n{result.stderr}"


# ---------------------------------------------------------------------------
# Section 6 — Alembic migration and additive column registration
# ---------------------------------------------------------------------------


class TestMigrationRegistration:
    def test_spec_json_in_additive_migrations(self):
        """engine._NEW_COLUMNS must include workflow_versions.spec_json."""
        # Access the module-level constant
        import inspect

        from omniharness.persistence import engine as eng_mod

        src = inspect.getsource(eng_mod._run_additive_migrations)
        # The column tuple must appear in the function source
        assert "spec_json" in src

    @pytest.mark.asyncio
    async def test_spec_json_column_exists_after_create_all(self, session_factory):
        """create_all (used by the fixture) must create spec_json on workflow_versions."""
        from omniharness.persistence.workflow_versions.sql import WorkflowVersionRepository

        repo = WorkflowVersionRepository(session_factory)
        # Create a version and call set_spec_json — will fail if column missing
        from omniharness.persistence.workflows.sql import WorkflowRepository

        wf_repo = WorkflowRepository(session_factory)
        wf = await wf_repo.create(id=str(uuid.uuid4()), owner_id="u1", title="t")
        vid = str(uuid.uuid4())
        await repo.create(id=vid, workflow_id=wf["id"], version_number=1)
        updated = await repo.set_spec_json(vid, {"title": "t", "steps": []})
        assert updated is not None
        assert updated["spec_json"] == {"title": "t", "steps": []}

    @pytest.mark.asyncio
    async def test_set_spec_json_returns_none_for_missing_version(self, session_factory):
        from omniharness.persistence.workflow_versions.sql import WorkflowVersionRepository

        repo = WorkflowVersionRepository(session_factory)
        result = await repo.set_spec_json("nonexistent-id", {"title": "x"})
        assert result is None
