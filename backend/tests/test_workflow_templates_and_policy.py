"""Tests for Phase 1 Slice 6 — workflow templates catalog + approval-policy guardrail.

Covers:
- GET /api/workflows/templates returns 3 templates with expected ids/titles
- Templates endpoint returns 404 when feature flag is off
- Templates are NOT user rows (GET /api/workflows returns empty)
- requires_approval() decision function correctness
- trigger_workflow_run: 409 when approval_required and confirmed=False
- trigger_workflow_run: 202 when approval_required and confirmed=True
- trigger_workflow_run: 202 for non-approval_required workflow without confirmed
- generate_workflow propagates approval_policy to workflow row
- PATCH /{id} with approval_policy updates the field
- POST /api/workflows with spec_json stores spec on version
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.gateway.routers.workflows as workflows_router
from omniharness.config.app_config import AppConfig
from omniharness.config.workflows_config import WorkflowsConfig
from omniharness.persistence.base import Base
from omniharness.persistence.workflow_versions.sql import WorkflowVersionRepository
from omniharness.persistence.workflows.sql import WorkflowRepository

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_config(enabled: bool = True) -> AppConfig:
    from omniharness.config.database_config import DatabaseConfig
    from omniharness.config.sandbox_config import SandboxConfig

    return AppConfig(
        sandbox=SandboxConfig(use="omniharness.sandbox.local:LocalSandboxProvider"),
        database=DatabaseConfig(),
        workflows=WorkflowsConfig(enabled=enabled),
    )


def _make_app(*, wf_repo=None, version_repo=None, run_repo=None, enabled: bool = True) -> FastAPI:
    app = FastAPI()
    app.state.workflow_repo = wf_repo
    app.state.workflow_version_repo = version_repo
    app.state.workflow_run_repo = run_repo
    app.include_router(workflows_router.router)
    return app


async def _init_repos():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        import omniharness.persistence.models  # noqa: F401

        await conn.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    return WorkflowRepository(sf), WorkflowVersionRepository(sf), sf


# ---------------------------------------------------------------------------
# Unit tests: requires_approval()
# ---------------------------------------------------------------------------


class TestRequiresApproval:
    def test_true_for_approval_required(self):
        from app.gateway.workflows.policy import requires_approval

        assert requires_approval({"approval_policy": "approval_required"}) is True

    def test_false_for_draft_only(self):
        from app.gateway.workflows.policy import requires_approval

        assert requires_approval({"approval_policy": "draft_only"}) is False

    def test_false_for_execute_low_risk(self):
        from app.gateway.workflows.policy import requires_approval

        assert requires_approval({"approval_policy": "execute_low_risk"}) is False

    def test_false_for_none(self):
        from app.gateway.workflows.policy import requires_approval

        assert requires_approval({"approval_policy": None}) is False

    def test_false_for_missing_key(self):
        from app.gateway.workflows.policy import requires_approval

        assert requires_approval({}) is False


# ---------------------------------------------------------------------------
# Integration tests: templates endpoint
# ---------------------------------------------------------------------------


class TestTemplatesEndpoint:
    @pytest.fixture(autouse=True)
    def setup(self):
        config = _make_config(enabled=True)
        self._app = _make_app(enabled=True)
        patcher_config = patch.object(workflows_router, "get_app_config", return_value=config)
        patcher_config.start()
        self.client = TestClient(self._app, raise_server_exceptions=True)
        yield
        patcher_config.stop()

    def test_list_templates_returns_three(self):
        res = self.client.get("/api/workflows/templates")
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 3
        ids = {t["id"] for t in data}
        assert "tpl-daily-brief" in ids
        assert "tpl-meeting-prep" in ids
        assert "tpl-weekly-summary" in ids
        titles = {t["title"] for t in data}
        assert "Daily Brief" in titles
        assert "Meeting Prep" in titles
        assert "Weekly Project Summary" in titles

    def test_templates_have_spec_json(self):
        res = self.client.get("/api/workflows/templates")
        assert res.status_code == 200
        for tpl in res.json():
            assert tpl["spec_json"] is not None
            assert "steps" in tpl["spec_json"]


class TestTemplatesEndpointFlagOff:
    @pytest.fixture(autouse=True)
    def setup(self):
        config = _make_config(enabled=False)
        self._app = _make_app(enabled=False)
        patcher_config = patch.object(workflows_router, "get_app_config", return_value=config)
        patcher_config.start()
        self.client = TestClient(self._app, raise_server_exceptions=False)
        yield
        patcher_config.stop()

    def test_templates_flag_off_returns_404(self):
        res = self.client.get("/api/workflows/templates")
        assert res.status_code == 404


class TestTemplatesNotInWorkflowsTable:
    """Templates are static — they must NOT appear as user workflow rows."""

    @pytest.fixture(autouse=True)
    def setup(self):
        config = _make_config(enabled=True)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        wf_repo, version_repo, sf = loop.run_until_complete(_init_repos())
        self._app = _make_app(wf_repo=wf_repo, version_repo=version_repo, enabled=True)
        patcher_config = patch.object(workflows_router, "get_app_config", return_value=config)
        patcher_user = patch.object(workflows_router, "get_effective_user_id", return_value="user-1")
        patcher_config.start()
        patcher_user.start()
        self.client = TestClient(self._app, raise_server_exceptions=True)
        yield
        patcher_config.stop()
        patcher_user.stop()
        loop.close()

    def test_template_ids_not_in_workflows_table(self):
        # Fetching templates doesn't create DB rows
        self.client.get("/api/workflows/templates")
        res = self.client.get("/api/workflows")
        assert res.status_code == 200
        ids = {wf["id"] for wf in res.json()}
        assert "tpl-daily-brief" not in ids
        assert "tpl-meeting-prep" not in ids
        assert "tpl-weekly-summary" not in ids
        # The list should be empty (no user workflows exist)
        assert len(res.json()) == 0


# ---------------------------------------------------------------------------
# Integration tests: approval-policy guardrail on /run
# ---------------------------------------------------------------------------


class TestApprovalGuardrail:
    """Tests for the approval-required guardrail on POST /{id}/run."""

    @pytest.fixture(autouse=True)
    def setup(self):
        config = _make_config(enabled=True)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        wf_repo, version_repo, sf = loop.run_until_complete(_init_repos())

        # Build a minimal run repo mock
        from omniharness.persistence.workflow_runs.sql import WorkflowRunRepository

        run_repo = WorkflowRunRepository(sf)

        self._wf_repo = wf_repo
        self._version_repo = version_repo
        self._run_repo = run_repo
        self._sf = sf
        self._loop = loop

        self._app = _make_app(wf_repo=wf_repo, version_repo=version_repo, run_repo=run_repo, enabled=True)

        patcher_config = patch.object(workflows_router, "get_app_config", return_value=config)
        patcher_user = patch.object(workflows_router, "get_effective_user_id", return_value="u1")
        # Mock execute_workflow_run so no real background work happens
        patcher_exec = patch("app.gateway.workflows.executor.execute_workflow_run", new_callable=AsyncMock)
        patcher_config.start()
        patcher_user.start()
        patcher_exec.start()
        self.client = TestClient(self._app, raise_server_exceptions=True)
        yield
        patcher_config.stop()
        patcher_user.stop()
        patcher_exec.stop()
        loop.close()

    def _create_workflow(self, approval_policy: str) -> str:
        res = self.client.post(
            "/api/workflows",
            json={
                "title": f"Wf {approval_policy}",
                "instruction_prompt": "Do something",
                "approval_policy": approval_policy,
            },
        )
        assert res.status_code == 201
        return res.json()["id"]

    def test_trigger_approval_required_without_confirmed_returns_409(self):
        wf_id = self._create_workflow("approval_required")
        res = self.client.post(f"/api/workflows/{wf_id}/run", json={})
        assert res.status_code == 409
        assert res.json()["detail"] == "approval_required"

    def test_trigger_approval_required_with_confirmed_proceeds(self):
        wf_id = self._create_workflow("approval_required")
        res = self.client.post(f"/api/workflows/{wf_id}/run", json={"confirmed": True})
        assert res.status_code == 202

    def test_trigger_normal_workflow_proceeds_without_confirmed(self):
        wf_id = self._create_workflow("draft_only")
        res = self.client.post(f"/api/workflows/{wf_id}/run", json={})
        assert res.status_code == 202

    def test_trigger_execute_low_risk_proceeds_without_confirmed(self):
        wf_id = self._create_workflow("execute_low_risk")
        res = self.client.post(f"/api/workflows/{wf_id}/run", json={})
        assert res.status_code == 202


# ---------------------------------------------------------------------------
# Integration tests: generate propagates approval_policy
# ---------------------------------------------------------------------------


class TestGeneratePropagatesApprovalPolicy:
    @pytest.fixture(autouse=True)
    def setup(self):
        config = _make_config(enabled=True)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        wf_repo, version_repo, sf = loop.run_until_complete(_init_repos())
        self._app = _make_app(wf_repo=wf_repo, version_repo=version_repo, enabled=True)

        patcher_config = patch.object(workflows_router, "get_app_config", return_value=config)
        patcher_user = patch.object(workflows_router, "get_effective_user_id", return_value="u1")
        patcher_config.start()
        patcher_user.start()
        self.client = TestClient(self._app, raise_server_exceptions=True)
        yield
        patcher_config.stop()
        patcher_user.stop()
        loop.close()

    def test_generate_propagates_approval_policy(self):
        from app.gateway.workflows.generator import WorkflowSpec, WorkflowSpecStep

        # Create a workflow with an instruction prompt
        create_res = self.client.post(
            "/api/workflows",
            json={"title": "Gen Wf", "instruction_prompt": "Do something complex"},
        )
        assert create_res.status_code == 201
        wf_id = create_res.json()["id"]

        # Mock generate_workflow_spec to return an approval_required spec
        mock_spec = WorkflowSpec(
            title="Gen Wf",
            description="Complex workflow",
            steps=[WorkflowSpecStep(title="Step 1", description="Do it", suggested_tools=[])],
            required_capabilities=[],
            risks=["may cause side effects"],
            approval_policy="approval_required",
        )

        with patch.object(workflows_router, "generate_workflow_spec", new_callable=AsyncMock, return_value=mock_spec):
            gen_res = self.client.post(f"/api/workflows/{wf_id}/generate", json={})
            assert gen_res.status_code == 200

        # Fetch the workflow — approval_policy should be updated
        get_res = self.client.get(f"/api/workflows/{wf_id}")
        assert get_res.status_code == 200
        assert get_res.json()["approval_policy"] == "approval_required"


# ---------------------------------------------------------------------------
# Integration tests: PATCH approval_policy
# ---------------------------------------------------------------------------


class TestPatchApprovalPolicy:
    @pytest.fixture(autouse=True)
    def setup(self):
        config = _make_config(enabled=True)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        wf_repo, version_repo, sf = loop.run_until_complete(_init_repos())
        self._app = _make_app(wf_repo=wf_repo, version_repo=version_repo, enabled=True)

        patcher_config = patch.object(workflows_router, "get_app_config", return_value=config)
        patcher_user = patch.object(workflows_router, "get_effective_user_id", return_value="u1")
        patcher_config.start()
        patcher_user.start()
        self.client = TestClient(self._app, raise_server_exceptions=True)
        yield
        patcher_config.stop()
        patcher_user.stop()
        loop.close()

    def test_patch_approval_policy(self):
        create_res = self.client.post("/api/workflows", json={"title": "Patch Me"})
        assert create_res.status_code == 201
        wf_id = create_res.json()["id"]
        # Initially draft_only (default)
        assert create_res.json()["approval_policy"] == "draft_only"

        patch_res = self.client.patch(f"/api/workflows/{wf_id}", json={"approval_policy": "approval_required"})
        assert patch_res.status_code == 200
        assert patch_res.json()["approval_policy"] == "approval_required"

    def test_patch_approval_policy_to_execute_low_risk(self):
        create_res = self.client.post("/api/workflows", json={"title": "Patch Me 2"})
        wf_id = create_res.json()["id"]

        patch_res = self.client.patch(f"/api/workflows/{wf_id}", json={"approval_policy": "execute_low_risk"})
        assert patch_res.status_code == 200
        assert patch_res.json()["approval_policy"] == "execute_low_risk"


# ---------------------------------------------------------------------------
# Integration tests: create workflow with spec_json
# ---------------------------------------------------------------------------


class TestCreateWithSpecJson:
    @pytest.fixture(autouse=True)
    def setup(self):
        config = _make_config(enabled=True)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        wf_repo, version_repo, sf = loop.run_until_complete(_init_repos())
        self._app = _make_app(wf_repo=wf_repo, version_repo=version_repo, enabled=True)

        patcher_config = patch.object(workflows_router, "get_app_config", return_value=config)
        patcher_user = patch.object(workflows_router, "get_effective_user_id", return_value="u1")
        patcher_config.start()
        patcher_user.start()
        self.client = TestClient(self._app, raise_server_exceptions=True)
        yield
        patcher_config.stop()
        patcher_user.stop()
        loop.close()

    def test_create_with_spec_json_stores_on_version(self):
        spec_json = {
            "title": "My Spec",
            "description": "A pre-built spec",
            "steps": [
                {"title": "Step 1", "description": "Do step 1", "suggested_tools": []},
            ],
            "required_capabilities": [],
            "risks": [],
            "approval_policy": "execute_low_risk",
        }
        create_res = self.client.post(
            "/api/workflows",
            json={
                "title": "Template Workflow",
                "instruction_prompt": "Do something",
                "spec_json": spec_json,
            },
        )
        assert create_res.status_code == 201
        wf_id = create_res.json()["id"]

        # GET /{id} should return spec_json
        get_res = self.client.get(f"/api/workflows/{wf_id}")
        assert get_res.status_code == 200
        returned_spec = get_res.json().get("spec_json")
        assert returned_spec is not None
        assert returned_spec["title"] == "My Spec"
        assert len(returned_spec["steps"]) == 1
