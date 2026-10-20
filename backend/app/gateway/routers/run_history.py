"""Run history (Feature 006 slice 0): read runs, set retention, delete it all.

Local only. Every run was redacted before it was stored (app/run_history).
Deleting the whole history names what it deletes (`confirm=delete-all`) so a
stray request cannot do it.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission

router = APIRouter(prefix="/api/run-history", tags=["run-history"])


class RetentionSettings(BaseModel):
    retention_days: int = Field(ge=1, le=3650)


class HistorySettings(RetentionSettings):
    runs: int
    #: Where it lives, so the person can see it is on this machine.
    location: str


class RunSummaryView(BaseModel):
    id: str
    kind: str
    source_id: str
    event_id: str | None = None
    thread_id: str | None = None
    started_at: str
    finished_at: str | None = None
    status: str
    error: str | None = None
    size: int


class RunDetail(RunSummaryView):
    body: Any = None


class Deleted(BaseModel):
    deleted: int


def _history(request: Request):
    history = getattr(request.app.state, "run_history", None)
    if history is None:
        raise HTTPException(status_code=503, detail="The run history is not available on this gateway (it could not be opened at startup; see the gateway log).")
    return history


@router.get("/settings", response_model=HistorySettings)
@require_permission("threads", "read")
async def get_settings(request: Request) -> HistorySettings:
    h = _history(request)
    return HistorySettings(retention_days=h.retention_days(), runs=h.count(), location=str(h.root))


@router.put("/settings", response_model=HistorySettings)
@require_permission("threads", "write")
async def put_settings(body: RetentionSettings, request: Request) -> HistorySettings:
    h = _history(request)
    h.set_retention_days(body.retention_days)
    h.purge()  # a shorter retention applies now, not at the next hourly run
    return HistorySettings(retention_days=h.retention_days(), runs=h.count(), location=str(h.root))


@router.delete("/runs", response_model=Deleted)
@require_permission("threads", "write")
async def delete_all(confirm: str, request: Request) -> Deleted:
    if confirm != "delete-all":
        raise HTTPException(status_code=422, detail="Deleting the run history needs confirm=delete-all.")
    return Deleted(deleted=_history(request).delete_all())


@router.get("/runs", response_model=list[RunSummaryView])
@require_permission("threads", "read")
async def list_runs(request: Request, kind: str | None = None, source_id: str | None = None, limit: int = 50) -> list[RunSummaryView]:
    return [RunSummaryView(**r.__dict__) for r in _history(request).list(kind=kind, source_id=source_id, limit=min(max(limit, 1), 500))]


@router.get("/runs/{run_id}", response_model=RunDetail)
@require_permission("threads", "read")
async def get_run(run_id: str, request: Request) -> RunDetail:
    run = _history(request).get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="No such run (it may have been purged).")
    return RunDetail(**run)
