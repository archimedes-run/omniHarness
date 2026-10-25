"""Coding jobs API (spec 009, Slice 1): what the chat's job card reads, and Stop.

Owner-only, through the thread's own permission check. Steps are the
worker's commands and outputs, already redacted when stored; they are shown
as plain text, never rendered as markup.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.gateway.authz import require_permission

router = APIRouter(prefix="/api", tags=["code-jobs"])


def _store(request: Request):
    store = getattr(request.app.state, "code_job_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Coding jobs are not available")
    # A job whose runner died with its process (a gateway restart) is shown
    # as interrupted, never left "running".
    store.reap_stale()
    return store


def _payload(request: Request, job, after: int) -> dict:
    store = _store(request)
    config = getattr(request.app.state, "config", None)
    cap = config.code_jobs.monthly_cap_usd if config is not None else None
    return {"job": job.public(), "steps": store.steps(job.id, after=max(0, after)), "month": {"spent_usd": round(store.month_spend(), 4), "cap_usd": cap}}


@router.get("/threads/{thread_id}/code-jobs")
@require_permission("threads", "read", owner_check=True)
async def list_code_jobs(thread_id: str, request: Request) -> dict:
    return {"jobs": [job.public() for job in _store(request).for_thread(thread_id)]}


@router.get("/threads/{thread_id}/code-jobs/by-call/{tool_call_id}")
@require_permission("threads", "read", owner_check=True)
async def code_job_by_call(thread_id: str, tool_call_id: str, request: Request, after: int = 0) -> dict:
    job = _store(request).by_call(thread_id, tool_call_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No coding job for this tool call yet")
    return _payload(request, job, after)


@router.get("/threads/{thread_id}/code-jobs/{job_id}")
@require_permission("threads", "read", owner_check=True)
async def get_code_job(thread_id: str, job_id: str, request: Request, after: int = 0) -> dict:
    job = _store(request).get(job_id)
    if job is None or job.thread_id != thread_id:
        raise HTTPException(status_code=404, detail="Coding job not found")
    return _payload(request, job, after)


@router.post("/threads/{thread_id}/code-jobs/{job_id}/stop")
@require_permission("threads", "write", owner_check=True, require_existing=True)
async def stop_code_job(thread_id: str, job_id: str, request: Request) -> dict:
    store = _store(request)
    job = store.get(job_id)
    if job is None or job.thread_id != thread_id:
        raise HTTPException(status_code=404, detail="Coding job not found")
    manager = getattr(request.app.state, "code_job_manager", None)
    stopping = bool(manager is not None and await manager.stop(job_id))
    job = store.get(job_id)
    return {"stopping": stopping, "job": job.public() if job else None}
