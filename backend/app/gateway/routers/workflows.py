"""Workflows API router — Phase 0 skeleton.

All endpoints return 404 when the workflows feature flag is disabled.
"""

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
    created_at: str
    updated_at: str


def _serialize(row: dict) -> WorkflowResponse:
    """Convert a repository dict to WorkflowResponse, serializing datetimes."""
    return WorkflowResponse(
        id=row["id"],
        owner_id=row.get("owner_id"),
        title=row["title"],
        description=row.get("description"),
        status=row["status"],
        created_at=row["created_at"].isoformat() if isinstance(row["created_at"], datetime) else row["created_at"],
        updated_at=row["updated_at"].isoformat() if isinstance(row["updated_at"], datetime) else row["updated_at"],
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


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("", status_code=201, response_model=WorkflowResponse, summary="Create Workflow")
async def create_workflow(body: WorkflowCreate, request: Request) -> WorkflowResponse:
    """Create a new workflow in draft status."""
    _check_enabled()
    repo = _get_repo(request)
    owner_id = get_effective_user_id()
    row = await repo.create(
        id=str(uuid.uuid4()),
        owner_id=owner_id,
        title=body.title,
        description=body.description,
    )
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
