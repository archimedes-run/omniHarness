"""Workflows API router — Phase 1 Slice 4a."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field

from app.gateway.workflows.generator import WorkflowGenerationError, WorkflowSpec, generate_workflow_spec
from omniharness.config import get_app_config
from omniharness.persistence.workflow_runs.sql import IllegalStatusTransition
from omniharness.platform.events import EventSource
from omniharness.platform.writer import emit_platform_event
from omniharness.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)

# Statuses from which a user may request retry.
_RETRYABLE_STATUSES: frozenset[str] = frozenset({"failed", "canceled"})
# Statuses that represent a completed (terminal) workflow run.
_TERMINAL_STATUSES: frozenset[str] = frozenset({"succeeded", "failed", "canceled", "expired"})

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
    # Slice 4a: spec generated from instruction_prompt; None until POST /generate is called.
    spec_json: dict | None = None
    created_at: str
    updated_at: str


def _dt(v) -> str:
    return v.isoformat() if isinstance(v, datetime) else str(v)


def _serialize(row: dict, spec_json: dict | None = None) -> WorkflowResponse:
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
        spec_json=spec_json,
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
    # Lineage: set when this run is a retry of another run (source stored in trigger_payload).
    source_run_id: str | None = None
    # Populated on GET run-detail when status=succeeded; reads last_ai_message from the underlying run.
    final_summary: str | None = None
    created_at: str
    updated_at: str


def _dt_opt(v) -> str | None:
    if v is None:
        return None
    return v.isoformat() if isinstance(v, datetime) else str(v)


def _serialize_run(row: dict) -> WorkflowRunResponse:
    payload = row.get("trigger_payload") or {}
    return WorkflowRunResponse(
        id=row["id"],
        workflow_id=row["workflow_id"],
        trigger_type=row.get("trigger_type", "manual"),
        trigger_payload=payload,
        status=row["status"],
        started_at=_dt_opt(row.get("started_at")),
        completed_at=_dt_opt(row.get("completed_at")),
        error_summary=row.get("error_summary"),
        thread_id=row.get("thread_id"),
        run_id=row.get("run_id"),
        idempotency_key=row.get("idempotency_key", ""),
        initiated_by=row.get("initiated_by"),
        source_run_id=payload.get("source_run_id"),
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
    """Get a workflow by ID (scoped to the current user). Includes spec_json when generated."""
    _check_enabled()
    repo = _get_repo(request)
    owner_id = get_effective_user_id()
    row = await repo.get(workflow_id, owner_id=owner_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    spec_json: dict | None = None
    version_id = row.get("current_version_id")
    if version_id:
        version_repo = _get_version_repo(request)
        version = await version_repo.get(version_id)
        if version:
            spec_json = version.get("spec_json")

    return _serialize(row, spec_json=spec_json)


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
# Spec generation (Phase 1 Slice 4a)
# ---------------------------------------------------------------------------


@router.post("/{workflow_id}/generate", response_model=WorkflowSpec, summary="Generate Workflow Spec")
async def generate_workflow(workflow_id: str, request: Request) -> WorkflowSpec:
    """Generate a structured WorkflowSpec from the workflow's instruction_prompt.

    Makes a single constrained LLM call (with one automatic retry on failure).
    Validates the output against WorkflowSpec before storing.  Overwrites any
    prior spec on the current version (regenerate = overwrite, no new version).
    Returns the validated spec immediately in the response body.

    Does NOT create a thread, run, or sandbox — this is pure planning.

    Returns 409 when the workflow has no current version or empty instruction.
    Returns 422 when the model cannot produce a valid spec after one retry.
    Returns 502 on unexpected upstream model errors.
    """
    _check_enabled()
    owner_id = get_effective_user_id()

    wf_repo = _get_repo(request)
    wf = await wf_repo.get(workflow_id, owner_id=owner_id)
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    version_id = wf.get("current_version_id")
    if not version_id:
        raise HTTPException(status_code=409, detail="Workflow has no instruction to generate from")

    version_repo = _get_version_repo(request)
    version = await version_repo.get(version_id)
    if version is None:
        raise HTTPException(status_code=409, detail="Workflow has no instruction to generate from")

    instruction_prompt = (version.get("instruction_prompt") or "").strip()
    if not instruction_prompt:
        raise HTTPException(status_code=409, detail="Workflow has no instruction to generate from")

    try:
        spec = await generate_workflow_spec(instruction_prompt)
    except WorkflowGenerationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected error during workflow spec generation for %s", workflow_id)
        raise HTTPException(status_code=502, detail="Upstream model error during spec generation") from exc

    await version_repo.set_spec_json(version_id, spec.model_dump())

    return spec


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

    final_summary: str | None = None
    if row.get("status") == "succeeded" and row.get("run_id"):
        run_store = getattr(request.app.state, "run_store", None)
        if run_store is not None:
            try:
                underlying = await run_store.get(row["run_id"], user_id=None)
                if underlying:
                    final_summary = underlying.get("last_ai_message")
            except Exception:
                logger.debug("get_workflow_run: could not fetch final_summary for %s (non-fatal)", run_id, exc_info=True)

    response = _serialize_run(row)
    response.final_summary = final_summary
    return response


# ---------------------------------------------------------------------------
# Artifact links (Phase 1 Slice 5b)
# ---------------------------------------------------------------------------


class WorkflowArtifactLinkResponse(BaseModel):
    id: str
    workflow_run_id: str
    artifact_path: str
    artifact_type: str | None
    created_at: str


def _serialize_artifact_link(row: dict) -> WorkflowArtifactLinkResponse:
    return WorkflowArtifactLinkResponse(
        id=row["id"],
        workflow_run_id=row["workflow_run_id"],
        artifact_path=row["artifact_path"],
        artifact_type=row.get("artifact_type"),
        created_at=_dt(row["created_at"]),
    )


@router.get(
    "/{workflow_id}/runs/{run_id}/artifacts",
    response_model=list[WorkflowArtifactLinkResponse],
    summary="List Workflow Run Artifacts",
)
async def list_workflow_run_artifacts(
    workflow_id: str,
    run_id: str,
    request: Request,
) -> list[WorkflowArtifactLinkResponse]:
    """List artifact links produced by a workflow run."""
    _check_enabled()
    owner_id = get_effective_user_id()

    wf_repo = _get_repo(request)
    wf = await wf_repo.get(workflow_id, owner_id=owner_id)
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    run_repo = _get_run_repo(request)
    run_row = await run_repo.get(run_id)
    if run_row is None or run_row.get("workflow_id") != workflow_id:
        raise HTTPException(status_code=404, detail="Workflow run not found")

    artifact_repo = getattr(request.app.state, "workflow_artifact_link_repo", None)
    if artifact_repo is None:
        return []

    rows = await artifact_repo.list_by_run(run_id)
    return [_serialize_artifact_link(r) for r in rows]


# ---------------------------------------------------------------------------
# Cancel / Retry (Phase 1 Slice 3)
# ---------------------------------------------------------------------------


@router.post("/{workflow_id}/runs/{run_id}/cancel", response_model=WorkflowRunResponse, summary="Cancel Workflow Run")
async def cancel_workflow_run(workflow_id: str, run_id: str, request: Request) -> WorkflowRunResponse:
    """Cancel a queued or running workflow run.

    If the underlying agent run is in flight, cancels it via RunManager before
    transitioning the workflow_run row to 'canceled'.  Idempotent: returns 409
    if the run is already in a terminal state.
    """
    _check_enabled()
    owner_id = get_effective_user_id()

    wf_repo = _get_repo(request)
    wf = await wf_repo.get(workflow_id, owner_id=owner_id)
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    run_repo = _get_run_repo(request)
    wf_run = await run_repo.get(run_id)
    if wf_run is None or wf_run.get("workflow_id") != workflow_id:
        raise HTTPException(status_code=404, detail="Workflow run not found")

    if wf_run["status"] in _TERMINAL_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Workflow run is already terminal (status={wf_run['status']}); cannot cancel",
        )

    # Set a human-readable note before touching status.
    await run_repo.set_error_summary(run_id, "Cancelled by user")

    # If the underlying agent run is in flight, cancel it.
    underlying_run_id = wf_run.get("run_id")
    if underlying_run_id:
        run_mgr = getattr(request.app.state, "run_manager", None)
        if run_mgr is not None:
            try:
                await run_mgr.cancel(underlying_run_id)
            except Exception:
                logger.warning("Failed to cancel underlying run %s (non-fatal)", underlying_run_id, exc_info=True)

    # Transition the workflow_run row.  If the executor raced us to a terminal
    # state, IllegalStatusTransition is raised and we surface a 409.
    try:
        updated = await run_repo.transition_status(run_id, "canceled")
    except IllegalStatusTransition as exc:
        # Executor beat us — fetch the current row and return a 409.
        current = await run_repo.get(run_id) or wf_run
        raise HTTPException(
            status_code=409,
            detail=f"Run transitioned to {current['status']!r} before cancel could complete: {exc}",
        ) from exc

    event_store = getattr(request.app.state, "run_event_store", None)
    if event_store:
        try:
            await emit_platform_event(
                event_store,
                thread_id=f"plat-workflow-{workflow_id}",
                event_type="workflow.run.canceled",
                source=EventSource.WORKFLOW,
                metadata={"workflow_id": workflow_id, "workflow_run_id": run_id},
            )
        except Exception:
            logger.debug("Failed to emit workflow.run.canceled (non-fatal)", exc_info=True)

    return _serialize_run(updated)


@router.post("/{workflow_id}/runs/{run_id}/retry", status_code=202, response_model=WorkflowRunResponse, summary="Retry Workflow Run")
async def retry_workflow_run(
    workflow_id: str,
    run_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
) -> WorkflowRunResponse:
    """Retry a failed or canceled workflow run by creating a brand-new run.

    The source run is left untouched.  The new run records the source run ID
    inside its trigger_payload so the lineage is traceable.  Returns 202 with
    the new WorkflowRunResponse.  Returns 409 if the source run is not in a
    retryable state (failed or canceled).
    """
    _check_enabled()
    owner_id = get_effective_user_id()

    wf_repo = _get_repo(request)
    wf = await wf_repo.get(workflow_id, owner_id=owner_id)
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    run_repo = _get_run_repo(request)
    source_run = await run_repo.get(run_id)
    if source_run is None or source_run.get("workflow_id") != workflow_id:
        raise HTTPException(status_code=404, detail="Workflow run not found")

    if source_run["status"] not in _RETRYABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot retry a run with status={source_run['status']!r}; only failed or canceled runs may be retried",
        )

    # Create a brand-new run — fresh id, fresh unique idempotency key.
    # Source lineage stored inside trigger_payload; no new column required.
    new_run_id = str(uuid.uuid4())
    new_idempotency_key = f"wf:{workflow_id}:retry:{run_id}:{uuid.uuid4()}"

    new_run, _ = await run_repo.create_or_get_by_key(
        workflow_id=workflow_id,
        idempotency_key=new_idempotency_key,
        id=new_run_id,
        trigger_type="manual",
        trigger_payload={"source_run_id": run_id},
        initiated_by=owner_id,
    )

    from app.gateway.workflows.executor import execute_workflow_run

    background_tasks.add_task(execute_workflow_run, new_run["id"], app=request.app)

    return _serialize_run(new_run)
