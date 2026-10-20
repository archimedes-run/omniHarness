"""GET /api/sessions — what the coding sessions are doing, and whether we can see them.

Thin: asks Feature 001's watcher through the same client the trigger engine
uses (app.gateway.watcher_client), and hands the answer — or the reason there
is none — to `describe_sessions`. Read-only.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request

from app.gateway.authz import require_permission
from app.gateway.ownership import require_owner_account

# The local Claude/Codex sessions on this machine: the owner account only.
from app.gateway.sessions_view import SessionsView, describe_sessions
from app.gateway.watcher_client import WatcherClient, WatcherTimedOut, WatcherUnavailable

router = APIRouter(prefix="/api", tags=["sessions"], dependencies=[Depends(require_owner_account)])

#: How long a page waits for the watcher. It was the client's 10 s default, and
#: a watcher busy re-reading transcripts made every visit wait the full 10 s.
SESSIONS_TIMEOUT_S = 2.0

#: The last answer the watcher gave this process: (monotonic time, payload).
_last_good: tuple[float, dict] | None = None


@router.get("/sessions", response_model=SessionsView)
@require_permission("threads", "read")
async def sessions(request: Request) -> SessionsView:
    global _last_good
    try:
        payload = await WatcherClient(timeout=SESSIONS_TIMEOUT_S).list_sessions()
    except WatcherTimedOut as exc:
        # Configured, connected, and did not answer in time: busy, not down. Show what it last said,
        # labelled with how old it is and why, rather than make the user wait
        # or show nothing. Never for a refused connection, not-configured or
        # disabled: a watcher that is down reads as "cannot see" (SC-006).
        if _last_good is not None:
            at, cached = _last_good
            view = describe_sessions(cached)
            return view.model_copy(update={"reachable": False, "unreachable_kind": "unreachable", "unreachable_detail": str(exc), "last_known_age_seconds": int(time.monotonic() - at)})
        return describe_sessions(None, exc)
    except WatcherUnavailable as exc:
        return describe_sessions(None, exc)
    _last_good = (time.monotonic(), payload)
    return describe_sessions(payload)
