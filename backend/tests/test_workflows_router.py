"""Tests for the Workflows API router.

Uses FastAPI TestClient (sync). Builds a minimal app with just the
workflows router. Tests both flag-off (→ 404) and flag-on paths.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.gateway.routers.workflows as workflows_router
from omniharness.config.app_config import AppConfig
from omniharness.config.workflows_config import WorkflowsConfig
from omniharness.persistence.engine import close_engine, get_session_factory, init_engine
from omniharness.persistence.workflows.sql import WorkflowRepository

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(enabled: bool) -> AppConfig:
    """Build a minimal AppConfig with the workflows flag set."""
    from omniharness.config.database_config import DatabaseConfig
    from omniharness.config.sandbox_config import SandboxConfig

    return AppConfig(
        sandbox=SandboxConfig(use="omniharness.sandbox.local:LocalSandboxProvider"),
        database=DatabaseConfig(),
        workflows=WorkflowsConfig(enabled=enabled),
    )


def _make_app(repo, *, enabled: bool) -> FastAPI:
    """Build a minimal FastAPI app with the workflows router and a real (or None) repo."""
    app = FastAPI()
    app.state.workflow_repo = repo
    app.include_router(workflows_router.router)
    return app


async def _make_repo(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'wf_test.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    return WorkflowRepository(get_session_factory())


# ---------------------------------------------------------------------------
# Tests: flag OFF
# ---------------------------------------------------------------------------


class TestWorkflowsRouterFlagOff:
    """All endpoints should return 404 when workflows.enabled=False."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        config = _make_config(enabled=False)
        self._app = _make_app(repo=None, enabled=False)

        # Patch get_app_config to return our disabled config
        patcher = patch.object(workflows_router, "get_app_config", return_value=config)
        patcher.start()
        self.client = TestClient(self._app, raise_server_exceptions=False)
        yield
        patcher.stop()

    def test_post_returns_404(self):
        res = self.client.post("/api/workflows", json={"title": "Foo"})
        assert res.status_code == 404

    def test_get_list_returns_404(self):
        res = self.client.get("/api/workflows")
        assert res.status_code == 404

    def test_get_by_id_returns_404(self):
        res = self.client.get("/api/workflows/some-id")
        assert res.status_code == 404

    def test_patch_returns_404(self):
        res = self.client.patch("/api/workflows/some-id", json={"title": "New"})
        assert res.status_code == 404

    def test_archive_returns_404(self):
        res = self.client.post("/api/workflows/some-id/archive")
        assert res.status_code == 404


# ---------------------------------------------------------------------------
# Tests: flag ON
# ---------------------------------------------------------------------------


class TestWorkflowsRouterFlagOn:
    """Full CRUD round-trips when workflows.enabled=True."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        config = _make_config(enabled=True)

        # Create a real repo backed by a temp SQLite database using a fresh event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._repo = loop.run_until_complete(_make_repo(tmp_path))
        self._app = _make_app(repo=self._repo, enabled=True)

        # Patch get_app_config and get_effective_user_id for all tests
        patcher_config = patch.object(workflows_router, "get_app_config", return_value=config)
        patcher_user = patch.object(workflows_router, "get_effective_user_id", return_value="test-owner")
        patcher_config.start()
        patcher_user.start()

        self.client = TestClient(self._app, raise_server_exceptions=True)
        yield
        patcher_config.stop()
        patcher_user.stop()
        loop.run_until_complete(close_engine())
        loop.close()

    def test_create_returns_201(self):
        res = self.client.post(
            "/api/workflows",
            json={"title": "My Workflow", "description": "A test workflow"},
        )
        assert res.status_code == 201
        data = res.json()
        assert data["title"] == "My Workflow"
        assert data["description"] == "A test workflow"
        assert data["status"] == "draft"
        assert data["owner_id"] == "test-owner"
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" in data

    def test_list_returns_created_item(self):
        self.client.post("/api/workflows", json={"title": "Listed Workflow"})
        res = self.client.get("/api/workflows")
        assert res.status_code == 200
        items = res.json()
        assert len(items) >= 1
        assert any(i["title"] == "Listed Workflow" for i in items)

    def test_get_by_id_returns_workflow(self):
        create_res = self.client.post("/api/workflows", json={"title": "Get Me"})
        workflow_id = create_res.json()["id"]

        res = self.client.get(f"/api/workflows/{workflow_id}")
        assert res.status_code == 200
        assert res.json()["id"] == workflow_id

    def test_get_missing_returns_404(self):
        res = self.client.get("/api/workflows/does-not-exist")
        assert res.status_code == 404

    def test_patch_updates_title(self):
        create_res = self.client.post("/api/workflows", json={"title": "Old"})
        workflow_id = create_res.json()["id"]

        res = self.client.patch(f"/api/workflows/{workflow_id}", json={"title": "New"})
        assert res.status_code == 200
        assert res.json()["title"] == "New"

    def test_patch_missing_returns_404(self):
        res = self.client.patch("/api/workflows/ghost", json={"title": "X"})
        assert res.status_code == 404

    def test_archive_sets_status(self):
        create_res = self.client.post("/api/workflows", json={"title": "Archive Me"})
        workflow_id = create_res.json()["id"]

        res = self.client.post(f"/api/workflows/{workflow_id}/archive")
        assert res.status_code == 200
        assert res.json()["status"] == "archived"

    def test_archive_missing_returns_404(self):
        res = self.client.post("/api/workflows/ghost/archive")
        assert res.status_code == 404
