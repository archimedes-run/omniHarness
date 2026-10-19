"""Trigger engine status — why the engine is or is not doing anything.

Before this, a trigger engine that refused to start recorded why in
`handle.error` and nowhere a person could read it; the gateway then dropped the
handle. A calendar rule rejected for having no calendar feed, a rule file that
failed to reload, an unreachable watcher: each was a log line.

Read-only. It describes THIS worker's view, and says so: under several uvicorn
workers one runs the engine and the rest are standby, and a standby worker
reports that rather than guessing at another process's state. Feature 004's
triggers surface (T051) extends this router with rules and firings.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission

router = APIRouter(prefix="/api/triggers", tags=["triggers"])


class EngineStatus(BaseModel):
    #: disabled | runner | standby | failed
    role: str
    running: bool = False
    #: Why the engine did not start — e.g. a rule whose feed is not connected.
    error: str | None = None
    #: Why the most recent rule-file reload was rejected; the previous rules
    #: stay in force meanwhile.
    rules_error: str | None = None
    rules: list[dict[str, Any]] = Field(default_factory=list)
    #: Per trigger type, whether its source could be read on the last attempt.
    sources: dict[str, dict[str, Any]] = Field(default_factory=dict)


def describe_engine(app_state: Any) -> EngineStatus:
    """The status, from what the lifespan left on app.state. Pure read."""
    config = getattr(app_state, "config", None)
    if config is None or not config.trigger_engine.enabled:
        return EngineStatus(role="disabled")
    handle = getattr(app_state, "trigger_engine", None)
    if handle is None:
        return EngineStatus(role="standby", error=None)
    if handle.error:
        return EngineStatus(role="failed", error=handle.error)
    loop = handle.loop
    return EngineStatus(
        role="runner",
        running=handle.running,
        rules_error=loop.loader.last_error,
        rules=[{"id": r.id, "type": str(r.type), "enabled": r.enabled} for r in loop.loader.config.rules],
        sources={str(kind): source.describe() for kind, source in loop.runner.sources.items() if hasattr(source, "describe")},
    )


@router.get("/status", response_model=EngineStatus)
@require_permission("threads", "read")
async def engine_status(request: Request) -> EngineStatus:
    return describe_engine(request.app.state)
