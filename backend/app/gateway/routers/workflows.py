"""Workflows API router — Phase 1 Slice 1."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
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
