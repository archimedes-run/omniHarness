"""GET /api/inbox/alerts — what the trigger engine tried to tell the user (Phase 2.5).

Read-only. Reads the engine's audit log from disk (any worker can answer) and
the alerts this user dismissed on Home, and hands both to `describe_alerts`.
Pending confirmations are /api/confirmations.
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
    dismissed, readable = await _dismissed(request)
    audit = AuditLog(path=Path(cfg.state_dir) / "audit.jsonl", actor=cfg.actor).entries()
    return describe_alerts(audit, now=datetime.now(UTC), dismissed=dismissed, dismissals_readable=readable)


async def _dismissed(request: Request) -> tuple[set[str], bool]:
    """The alert keys this user dismissed on Home, and whether they could be read."""
    repo = getattr(request.app.state, "home_dismissal_repo", None)
    auth = getattr(request.state, "auth", None)
    if repo is None or not (auth and auth.user):
        return set(), False
    try:
        return await repo.keys(user_id=str(auth.user.id), kind="alert"), True
    except Exception:  # noqa: BLE001 — unreadable is reported, never a silent "none"
        return set(), False
