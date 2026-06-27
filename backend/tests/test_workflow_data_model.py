"""Tests for Phase 1 Slice 1 — Workflow data model.

Covers:
- WorkflowRunRow state machine (legal and illegal transitions)
- create_or_get_by_key idempotency
- WorkflowVersionRepository CRUD
- WorkflowStepRunRepository CRUD + status transitions
- WorkflowArtifactLinkRepository CRUD
- engine.py _NEW_COLUMNS parity for workflow table
- models/__init__.py registers all 4 new tables
- Harness boundary: new packages do not import from app.*
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from omniharness.persistence.base import Base

# ---------------------------------------------------------------------------
# In-memory SQLite fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        # Import models so Base.metadata includes all tables
        import omniharness.persistence.models  # noqa: F401

        await conn.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    yield sf
    await engine.dispose()


# ---------------------------------------------------------------------------
# WorkflowVersionRepository
# ---------------------------------------------------------------------------


class TestWorkflowVersionRepository:
    @pytest_asyncio.fixture
    async def repo_and_wf(self, session_factory):
        from omniharness.persistence.workflow_versions.sql import WorkflowVersionRepository
        from omniharness.persistence.workflows.sql import WorkflowRepository

        wf_repo = WorkflowRepository(session_factory)
        wf = await wf_repo.create(id=str(uuid.uuid4()), owner_id="u1", title="Wf A")
        return WorkflowVersionRepository(session_factory), wf["id"]

    @pytest.mark.asyncio
    async def test_create_and_get(self, repo_and_wf):
        repo, wf_id = repo_and_wf
        vid = str(uuid.uuid4())
        v = await repo.create(id=vid, workflow_id=wf_id, version_number=1, instruction_prompt="do x")
        assert v["id"] == vid
        assert v["version_number"] == 1
        assert v["instruction_prompt"] == "do x"

        fetched = await repo.get(vid)
        assert fetched is not None
        assert fetched["workflow_id"] == wf_id

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self, repo_and_wf):
        repo, _ = repo_and_wf
        assert await repo.get("nonexistent") is None

    @pytest.mark.asyncio
    async def test_list_by_workflow_ordered(self, repo_and_wf):
        repo, wf_id = repo_and_wf
        await repo.create(id=str(uuid.uuid4()), workflow_id=wf_id, version_number=2)
        await repo.create(id=str(uuid.uuid4()), workflow_id=wf_id, version_number=1)
        versions = await repo.list_by_workflow(wf_id)
        assert [v["version_number"] for v in versions] == [1, 2]

    @pytest.mark.asyncio
    async def test_list_by_workflow_empty(self, repo_and_wf):
        repo, _ = repo_and_wf
        assert await repo.list_by_workflow("no-such-wf") == []


# ---------------------------------------------------------------------------
# WorkflowRunRepository — create_or_get_by_key
# ---------------------------------------------------------------------------


class TestWorkflowRunIdempotency:
    @pytest_asyncio.fixture
    async def repo_and_wf_id(self, session_factory):
        from omniharness.persistence.workflow_runs.sql import WorkflowRunRepository
        from omniharness.persistence.workflows.sql import WorkflowRepository

        wf = await WorkflowRepository(session_factory).create(id=str(uuid.uuid4()), owner_id="u1", title="Wf B")
        return WorkflowRunRepository(session_factory), wf["id"]

    @pytest.mark.asyncio
    async def test_first_create_returns_true(self, repo_and_wf_id):
        repo, wf_id = repo_and_wf_id
        key = f"wf:{wf_id}:sched:abc123"
        run, created = await repo.create_or_get_by_key(id=str(uuid.uuid4()), workflow_id=wf_id, idempotency_key=key)
        assert created is True
        assert run["status"] == "queued"
        assert run["workflow_id"] == wf_id

    @pytest.mark.asyncio
    async def test_duplicate_key_returns_false(self, repo_and_wf_id):
        repo, wf_id = repo_and_wf_id
        key = f"wf:{wf_id}:sched:dupe"
        run1, _ = await repo.create_or_get_by_key(id=str(uuid.uuid4()), workflow_id=wf_id, idempotency_key=key)
        run2, created = await repo.create_or_get_by_key(id=str(uuid.uuid4()), workflow_id=wf_id, idempotency_key=key)
        assert created is False
        assert run1["id"] == run2["id"]

    @pytest.mark.asyncio
    async def test_get_returns_run(self, repo_and_wf_id):
        repo, wf_id = repo_and_wf_id
        run, _ = await repo.create_or_get_by_key(id=str(uuid.uuid4()), workflow_id=wf_id, idempotency_key="k1")
        fetched = await repo.get(run["id"])
        assert fetched is not None
        assert fetched["id"] == run["id"]

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self, repo_and_wf_id):
        repo, _ = repo_and_wf_id
        assert await repo.get("no-such-run") is None

    @pytest.mark.asyncio
    async def test_list_by_workflow_newest_first(self, repo_and_wf_id):
        repo, wf_id = repo_and_wf_id
        for i in range(3):
            await repo.create_or_get_by_key(id=str(uuid.uuid4()), workflow_id=wf_id, idempotency_key=f"k{i}")
        runs = await repo.list_by_workflow(wf_id)
        assert len(runs) == 3
        # newest first — created_at desc
        timestamps = [r["created_at"] for r in runs]
        assert timestamps == sorted(timestamps, reverse=True)


# ---------------------------------------------------------------------------
# WorkflowRunRepository — state machine
# ---------------------------------------------------------------------------


class TestWorkflowRunStateMachine:
    @pytest_asyncio.fixture
    async def repo_and_run(self, session_factory):
        from omniharness.persistence.workflow_runs.sql import WorkflowRunRepository
        from omniharness.persistence.workflows.sql import WorkflowRepository

        wf = await WorkflowRepository(session_factory).create(id=str(uuid.uuid4()), owner_id="u1", title="SM Wf")
        repo = WorkflowRunRepository(session_factory)
        run, _ = await repo.create_or_get_by_key(id=str(uuid.uuid4()), workflow_id=wf["id"], idempotency_key="sm-key")
        return repo, run["id"]

    @pytest.mark.asyncio
    async def test_queued_to_running(self, repo_and_run):
        repo, run_id = repo_and_run
        updated = await repo.transition_status(run_id, "running")
        assert updated["status"] == "running"
        assert updated["started_at"] is not None

    @pytest.mark.asyncio
    async def test_queued_to_canceled(self, repo_and_run):
        repo, run_id = repo_and_run
        updated = await repo.cancel(run_id)
        assert updated["status"] == "canceled"
        assert updated["completed_at"] is not None

    @pytest.mark.asyncio
    async def test_running_to_succeeded(self, repo_and_run):
        repo, run_id = repo_and_run
        await repo.transition_status(run_id, "running")
        updated = await repo.transition_status(run_id, "succeeded")
        assert updated["status"] == "succeeded"
        assert updated["completed_at"] is not None

    @pytest.mark.asyncio
    async def test_running_to_failed(self, repo_and_run):
        repo, run_id = repo_and_run
        await repo.transition_status(run_id, "running")
        updated = await repo.transition_status(run_id, "failed")
        assert updated["status"] == "failed"

    @pytest.mark.asyncio
    async def test_running_to_expired(self, repo_and_run):
        repo, run_id = repo_and_run
        await repo.transition_status(run_id, "running")
        updated = await repo.transition_status(run_id, "expired")
        assert updated["status"] == "expired"

    @pytest.mark.asyncio
    async def test_illegal_queued_to_succeeded(self, repo_and_run):
        from omniharness.persistence.workflow_runs.sql import IllegalStatusTransition

        repo, run_id = repo_and_run
        with pytest.raises(IllegalStatusTransition):
            await repo.transition_status(run_id, "succeeded")

    @pytest.mark.asyncio
    async def test_illegal_running_to_queued(self, repo_and_run):
        from omniharness.persistence.workflow_runs.sql import IllegalStatusTransition

        repo, run_id = repo_and_run
        await repo.transition_status(run_id, "running")
        with pytest.raises(IllegalStatusTransition):
            await repo.transition_status(run_id, "queued")

    @pytest.mark.asyncio
    async def test_illegal_succeeded_to_running(self, repo_and_run):
        from omniharness.persistence.workflow_runs.sql import IllegalStatusTransition

        repo, run_id = repo_and_run
        await repo.transition_status(run_id, "running")
        await repo.transition_status(run_id, "succeeded")
        with pytest.raises(IllegalStatusTransition):
            await repo.transition_status(run_id, "running")

    @pytest.mark.asyncio
    async def test_transition_missing_run_raises_value_error(self, repo_and_run):
        repo, _ = repo_and_run
        with pytest.raises(ValueError, match="not found"):
            await repo.transition_status("ghost-id", "running")

    @pytest.mark.asyncio
    async def test_waiting_approval_is_terminal_no_transitions(self, repo_and_run):
        """waiting_approval has no outgoing transitions — reserved for Phase 6."""
        from omniharness.persistence.workflow_runs.sql import _LEGAL_TRANSITIONS

        assert _LEGAL_TRANSITIONS["waiting_approval"] == frozenset()


# ---------------------------------------------------------------------------
# WorkflowStepRunRepository
# ---------------------------------------------------------------------------


class TestWorkflowStepRunRepository:
    @pytest_asyncio.fixture
    async def repo_and_run_id(self, session_factory):
        from omniharness.persistence.workflow_runs.sql import WorkflowRunRepository
        from omniharness.persistence.workflow_step_runs.sql import WorkflowStepRunRepository
        from omniharness.persistence.workflows.sql import WorkflowRepository

        wf = await WorkflowRepository(session_factory).create(id=str(uuid.uuid4()), owner_id="u1", title="Step Wf")
        wf_run, _ = await WorkflowRunRepository(session_factory).create_or_get_by_key(id=str(uuid.uuid4()), workflow_id=wf["id"], idempotency_key="step-key")
        return WorkflowStepRunRepository(session_factory), wf_run["id"]

    @pytest.mark.asyncio
    async def test_create_and_list(self, repo_and_run_id):
        repo, run_id = repo_and_run_id
        s1 = await repo.create(id=str(uuid.uuid4()), workflow_run_id=run_id, step_key="step_a", step_index=0)
        s2 = await repo.create(id=str(uuid.uuid4()), workflow_run_id=run_id, step_key="step_b", step_index=1)
        steps = await repo.list_by_run(run_id)
        assert len(steps) == 2
        assert steps[0]["step_key"] == "step_a"
        assert steps[1]["step_key"] == "step_b"
        _ = s1, s2  # referenced

    @pytest.mark.asyncio
    async def test_update_status_running(self, repo_and_run_id):
        repo, run_id = repo_and_run_id
        step = await repo.create(id=str(uuid.uuid4()), workflow_run_id=run_id, step_key="step_x")
        updated = await repo.update_status(step["id"], "running")
        assert updated["status"] == "running"
        assert updated["started_at"] is not None

    @pytest.mark.asyncio
    async def test_update_status_failed_with_error(self, repo_and_run_id):
        repo, run_id = repo_and_run_id
        step = await repo.create(id=str(uuid.uuid4()), workflow_run_id=run_id, step_key="step_y")
        updated = await repo.update_status(step["id"], "failed", error_summary="boom")
        assert updated["status"] == "failed"
        assert updated["error_summary"] == "boom"
        assert updated["completed_at"] is not None

    @pytest.mark.asyncio
    async def test_update_status_missing_returns_none(self, repo_and_run_id):
        repo, _ = repo_and_run_id
        result = await repo.update_status("ghost", "running")
        assert result is None


# ---------------------------------------------------------------------------
# WorkflowArtifactLinkRepository
# ---------------------------------------------------------------------------


class TestWorkflowArtifactLinkRepository:
    @pytest_asyncio.fixture
    async def repo_and_run_id(self, session_factory):
        from omniharness.persistence.workflow_artifact_links.sql import WorkflowArtifactLinkRepository
        from omniharness.persistence.workflow_runs.sql import WorkflowRunRepository
        from omniharness.persistence.workflows.sql import WorkflowRepository

        wf = await WorkflowRepository(session_factory).create(id=str(uuid.uuid4()), owner_id="u1", title="Artifact Wf")
        wf_run, _ = await WorkflowRunRepository(session_factory).create_or_get_by_key(id=str(uuid.uuid4()), workflow_id=wf["id"], idempotency_key="artifact-key")
        return WorkflowArtifactLinkRepository(session_factory), wf_run["id"]

    @pytest.mark.asyncio
    async def test_create_and_list(self, repo_and_run_id):
        repo, run_id = repo_and_run_id
        a1 = await repo.create(id=str(uuid.uuid4()), workflow_run_id=run_id, artifact_path="/out/report.pdf", artifact_type="file")
        a2 = await repo.create(id=str(uuid.uuid4()), workflow_run_id=run_id, artifact_path="/out/summary.md")
        links = await repo.list_by_run(run_id)
        assert len(links) == 2
        assert links[0]["artifact_path"] == "/out/report.pdf"
        assert links[0]["artifact_type"] == "file"
        assert links[1]["artifact_type"] is None
        _ = a1, a2

    @pytest.mark.asyncio
    async def test_list_empty_run(self, repo_and_run_id):
        repo, _ = repo_and_run_id
        assert await repo.list_by_run("no-run") == []


# ---------------------------------------------------------------------------
# engine.py _NEW_COLUMNS parity
# ---------------------------------------------------------------------------


class TestEngineNewColumnsParity:
    def test_workflow_columns_in_new_columns(self):
        import inspect

        from omniharness.persistence import engine as eng

        src = inspect.getsource(eng._run_additive_migrations)
        expected = [
            "instruction_prompt",
            "trigger_type",
            "approval_policy",
            "created_by",
            "current_version_id",
            "required_capability_ids",
        ]
        for col in expected:
            assert col in src, f"Missing column {col!r} in _NEW_COLUMNS"


# ---------------------------------------------------------------------------
# models/__init__.py registration
# ---------------------------------------------------------------------------


class TestModelsRegistration:
    def test_all_four_new_tables_in_metadata(self):
        import omniharness.persistence.models  # noqa: F401
        from omniharness.persistence.base import Base

        tables = set(Base.metadata.tables.keys())
        for expected in ("workflow_versions", "workflow_runs", "workflow_step_runs", "workflow_artifact_links"):
            assert expected in tables, f"Table {expected!r} not in Base.metadata"

    def test_all_new_rows_exported(self):
        import omniharness.persistence.models as m

        assert hasattr(m, "WorkflowVersionRow")
        assert hasattr(m, "WorkflowRunRow")
        assert hasattr(m, "WorkflowStepRunRow")
        assert hasattr(m, "WorkflowArtifactLinkRow")


# ---------------------------------------------------------------------------
# Harness boundary
# ---------------------------------------------------------------------------


class TestHarnessBoundary:
    def _source(self, module_path: str) -> str:
        import importlib
        import inspect

        mod = importlib.import_module(module_path)
        return inspect.getsource(mod)

    def _check_no_app_import(self, module_path: str) -> None:
        src = self._source(module_path)
        assert "from app." not in src and "import app." not in src, f"{module_path} imports from app.* — harness boundary violation"

    def test_workflow_versions_model(self):
        self._check_no_app_import("omniharness.persistence.workflow_versions.model")

    def test_workflow_versions_sql(self):
        self._check_no_app_import("omniharness.persistence.workflow_versions.sql")

    def test_workflow_runs_model(self):
        self._check_no_app_import("omniharness.persistence.workflow_runs.model")

    def test_workflow_runs_sql(self):
        self._check_no_app_import("omniharness.persistence.workflow_runs.sql")

    def test_workflow_step_runs_model(self):
        self._check_no_app_import("omniharness.persistence.workflow_step_runs.model")

    def test_workflow_step_runs_sql(self):
        self._check_no_app_import("omniharness.persistence.workflow_step_runs.sql")

    def test_workflow_artifact_links_model(self):
        self._check_no_app_import("omniharness.persistence.workflow_artifact_links.model")

    def test_workflow_artifact_links_sql(self):
        self._check_no_app_import("omniharness.persistence.workflow_artifact_links.sql")
