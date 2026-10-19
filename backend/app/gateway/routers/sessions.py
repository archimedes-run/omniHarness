"""GET /api/sessions — what the coding sessions are doing, and whether we can see them.

Thin: asks Feature 001's watcher through the same client the trigger engine
uses (app.gateway.watcher_client), and hands the answer — or the reason there
is none — to `describe_sessions`. Read-only.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.gateway.authz import require_permission
from app.gateway.sessions_view import SessionsView, describe_sessions
from app.gateway.watcher_client import WatcherClient, WatcherUnavailable

router = APIRouter(prefix="/api", tags=["sessions"])


@router.get("/sessions", response_model=SessionsView)
@require_permission("threads", "read")
async def sessions(request: Request) -> SessionsView:
    try:
        payload = await WatcherClient().list_sessions()
    except WatcherUnavailable as exc:
        return describe_sessions(None, exc)
    return describe_sessions(payload)
