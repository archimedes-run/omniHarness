"""Workflows API router — Phase 1 Slice 2."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field

from omniharness.config import get_app_config
from omniharness.runtime.user_context import get_effective_user_id

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class WorkflowCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    instruction_prompt: str | None = None
    trigger_type: str | None = "manual"  # manual|scheduled|event|api
    approval_policy: str | None = "draft_only"  # draft_only|approval_required|execute_low_risk
    created_by: str | None = "user"  # user|agent|import|template


class WorkflowPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    status: str | None = None  # draft|active|paused|archived


class WorkflowResponse(BaseModel):
    id: str
    owner_id: str | None
    title: str
    description: str | None
    status: str
    instruction_prompt: str | None = None
    trigger_type: str | None = None
    approval_policy: str | None = None
    created_by: str | None = None
    current_version_id: str | None = None
    required_capability_ids: list | None = None
    created_at: str
    updated_at: str


def _dt(v) -> str:
    return v.isoformat() if isinstance(v, datetime) else str(v)


def _serialize(row: dict) -> WorkflowResponse:
    return WorkflowResponse(
        id=row["id"],
        owner_id=row.get("owner_id"),
        title=row["title"],
        description=row.get("description"),
        status=row["status"],
        instruction_prompt=row.get("instruction_prompt"),
        trigger_type=row.get("trigger_type"),
        approval_policy=row.get("approval_policy"),
        created_by=row.get("created_by"),
        current_version_id=row.get("current_version_id"),
        required_capability_ids=row.get("required_capability_ids"),
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
    )


def _check_enabled() -> None:
    config = get_app_config()
    if not config.workflows.enabled:
        raise HTTPException(status_code=404, detail="Workflows feature is not enabled")


def _get_repo(request: Request):
    repo = getattr(request.app.state, "workflow_repo", None)
    if repo is None:
        raise HTTPException(status_code=503, detail="Workflow repository not available")
    return repo


def _get_version_repo(request: Request):
    repo = getattr(request.app.state, "workflow_version_repo", None)
    if repo is None:
        raise HTTPException(status_code=503, detail="Workflow version repository not available")
    return repo


def _get_run_repo(request: Request):
    repo = getattr(request.app.state, "workflow_run_repo", None)
    if repo is None:
        raise HTTPException(status_code=503, detail="Workflow run repository not available")
    return repo


# ---------------------------------------------------------------------------
# Workflow-run request / response models
# ---------------------------------------------------------------------------


class WorkflowRunCreate(BaseModel):
    trigger_payload: dict[str, Any] | None = None


class WorkflowRunResponse(BaseModel):
    id: str
    workflow_id: str
    trigger_type: str
    trigger_payload: dict | None
    status: str
    started_at: str | None
    completed_at: str | None
    error_summary: str | None
    thread_id: str | None
    run_id: str | None
    idempotency_key: str
    initiated_by: str | None
    created_at: str
    updated_at: str


def _dt_opt(v) -> str | None:
    if v is None:
        return None
    return v.isoformat() if isinstance(v, datetime) else str(v)


def _serialize_run(row: dict) -> WorkflowRunResponse:
    return WorkflowRunResponse(
        id=row["id"],
        workflow_id=row["workflow_id"],
        trigger_type=row.get("trigger_type", "manual"),
        trigger_payload=row.get("trigger_payload"),
        status=row["status"],
        started_at=_dt_opt(row.get("started_at")),
        completed_at=_dt_opt(row.get("completed_at")),
        error_summary=row.get("error_summary"),
        thread_id=row.get("thread_id"),
        run_id=row.get("run_id"),
        idempotency_key=row.get("idempotency_key", ""),
        initiated_by=row.get("initiated_by"),
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("", status_code=201, response_model=WorkflowResponse, summary="Create Workflow")
async def create_workflow(body: WorkflowCreate, request: Request) -> WorkflowResponse:
    """Create a new workflow in draft status. If instruction_prompt is supplied, creates v1."""
    _check_enabled()
    repo = _get_repo(request)
    owner_id = get_effective_user_id()
    workflow_id = str(uuid.uuid4())

    row = await repo.create(
        id=workflow_id,
        owner_id=owner_id,
        title=body.title,
        description=body.description,
        instruction_prompt=body.instruction_prompt,
        trigger_type=body.trigger_type,
        approval_policy=body.approval_policy,
        created_by=body.created_by,
    )

    # If an instruction_prompt was supplied, create v1 and link it back.
    if body.instruction_prompt:
        version_repo = _get_version_repo(request)
        version_id = str(uuid.uuid4())
        await version_repo.create(
            id=version_id,
            workflow_id=workflow_id,
            version_number=1,
            instruction_prompt=body.instruction_prompt,
            created_by=body.created_by or "user",
        )
        row = await repo.set_current_version(workflow_id, version_id) or row

    return _serialize(row)


@router.get("", response_model=list[WorkflowResponse], summary="List Workflows")
async def list_workflows(request: Request) -> list[WorkflowResponse]:
    """List all workflows owned by the current user."""
    _check_enabled()
    repo = _get_repo(request)
    owner_id = get_effective_user_id()
    rows = await repo.list_by_owner(owner_id)
    return [_serialize(r) for r in rows]


@router.get("/{workflow_id}", response_model=WorkflowResponse, summary="Get Workflow")
async def get_workflow(workflow_id: str, request: Request) -> WorkflowResponse:
    """Get a workflow by ID (scoped to the current user)."""
    _check_enabled()
    repo = _get_repo(request)
    owner_id = get_effective_user_id()
    row = await repo.get(workflow_id, owner_id=owner_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return _serialize(row)


@router.patch("/{workflow_id}", response_model=WorkflowResponse, summary="Patch Workflow")
async def patch_workflow(workflow_id: str, body: WorkflowPatch, request: Request) -> WorkflowResponse:
    """Partially update a workflow (title, description, or status)."""
    _check_enabled()
    repo = _get_repo(request)
    owner_id = get_effective_user_id()
    row = await repo.update(
        workflow_id,
        owner_id=owner_id,
        title=body.title,
        description=body.description,
        status=body.status,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return _serialize(row)


@router.post("/{workflow_id}/archive", response_model=WorkflowResponse, summary="Archive Workflow")
async def archive_workflow(workflow_id: str, request: Request) -> WorkflowResponse:
    """Archive a workflow (sets status to 'archived')."""
    _check_enabled()
    repo = _get_repo(request)
    owner_id = get_effective_user_id()
    row = await repo.archive(workflow_id, owner_id=owner_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return _serialize(row)


# ---------------------------------------------------------------------------
# Manual-run API (Phase 1 Slice 2)
# ---------------------------------------------------------------------------


@router.post("/{workflow_id}/run", status_code=202, response_model=WorkflowRunResponse, summary="Trigger Manual Workflow Run")
async def trigger_workflow_run(
    workflow_id: str,
    body: WorkflowRunCreate,
    request: Request,
    background_tasks: BackgroundTasks,
) -> WorkflowRunResponse:
    """Trigger a manual workflow run.

    Creates a WorkflowRun record immediately (status=queued) and kicks off
    execute_workflow_run() as a FastAPI background task.  Returns 202 with the
    WorkflowRunResponse so callers can poll GET /runs/{run_id} for status.

    Manual runs never deduplicate — each call produces a fresh run.
    """
    _check_enabled()
    owner_id = get_effective_user_id()

    # Confirm workflow exists (scoped to owner)
    wf_repo = _get_repo(request)
    wf = await wf_repo.get(workflow_id, owner_id=owner_id)
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    run_repo = _get_run_repo(request)

    # Manual runs always use a unique idempotency key — never deduplicate.
    idempotency_key = f"wf:{workflow_id}:manual:{uuid.uuid4()}"
    run_id = str(uuid.uuid4())

    run_row, _ = await run_repo.create_or_get_by_key(
        workflow_id=workflow_id,
        idempotency_key=idempotency_key,
        id=run_id,
        trigger_type="manual",
        trigger_payload=body.trigger_payload or {},
        initiated_by=owner_id,
    )

    # Import here to avoid circular import at module load time.
    from app.gateway.workflows.executor import execute_workflow_run

    background_tasks.add_task(execute_workflow_run, run_row["id"], app=request.app)

    return _serialize_run(run_row)


@router.get("/{workflow_id}/runs", response_model=list[WorkflowRunResponse], summary="List Workflow Runs")
async def list_workflow_runs(workflow_id: str, request: Request) -> list[WorkflowRunResponse]:
    """List all runs for a workflow (most recent first)."""
    _check_enabled()
    owner_id = get_effective_user_id()

    # Gate on workflow ownership before exposing run list.
    wf_repo = _get_repo(request)
    wf = await wf_repo.get(workflow_id, owner_id=owner_id)
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    run_repo = _get_run_repo(request)
    rows = await run_repo.list_by_workflow(workflow_id)
    return [_serialize_run(r) for r in rows]


@router.get("/{workflow_id}/runs/{run_id}", response_model=WorkflowRunResponse, summary="Get Workflow Run")
async def get_workflow_run(workflow_id: str, run_id: str, request: Request) -> WorkflowRunResponse:
    """Get a specific workflow run by ID."""
    _check_enabled()
    owner_id = get_effective_user_id()

    # Gate on workflow ownership.
    wf_repo = _get_repo(request)
    wf = await wf_repo.get(workflow_id, owner_id=owner_id)
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    run_repo = _get_run_repo(request)
    row = await run_repo.get(run_id)
    if row is None or row.get("workflow_id") != workflow_id:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    return _serialize_run(row)
