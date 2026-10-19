"""GET /api/inbox/alerts — what the trigger engine tried to tell the user (Phase 2.5).

Read-only. Reads the engine's audit log from disk (any worker can answer) and
hands it to `describe_alerts`. Pending confirmations are /api/confirmations.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Request

from app.gateway.authz import require_permission
from app.gateway.inbox_view import InboxAlerts, describe_alerts

router = APIRouter(prefix="/api/inbox", tags=["inbox"])


@router.get("/alerts", response_model=InboxAlerts)
@require_permission("threads", "read")
async def inbox_alerts(request: Request) -> InboxAlerts:
    from app.trigger_engine.audit import AuditLog

    cfg = request.app.state.config.trigger_engine
    if not cfg.enabled:
        return InboxAlerts(alerts=[], waiting_count=0)
    audit = AuditLog(path=Path(cfg.state_dir) / "audit.jsonl", actor=cfg.actor).entries()
    return describe_alerts(audit, now=datetime.now(UTC))
