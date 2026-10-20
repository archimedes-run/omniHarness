"""/api/home — what Home reads and remembers that no other route serves (Feature 006).

- GET  /api/home/dismissals -> {"alert_keys": [...], "name_prompt_dismissed": bool}
- POST /api/home/dismissals {"kind": "alert", "keys": ["<rule_id>:<event_id>", ...]}
                            {"kind": "name-prompt"}
- GET  /api/home/upcoming   -> the next run of each enabled cron automation, and
                               the next 7 days of Google Calendar (read-only)
- GET  /api/home/today?since=<ISO> -> what moved since the start of the user's day
                               (ledger, deliveries, sessions, GitHub; read-only)

Dismissals are per user, on the server: a dismissed alert stays dismissed on
every device, and /api/inbox/alerts leaves it out of the New chat badge. The
name prompt is asked once; "Not now" is a dismissal of kind "name-prompt".
A database that is not available is a 503, never a silent "nothing dismissed".
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission
from app.gateway.deps import get_home_dismissal_repo
from app.gateway.home_sources import SourceState, calendar_events, github_items, session_items
from app.gateway.home_view import MovedView, UpcomingView, describe_moved, describe_upcoming
from omniharness.persistence.home_dismissals import KEY_MAX

router = APIRouter(prefix="/api/home", tags=["home"])

NAME_PROMPT = "name-prompt"


class DismissalsView(BaseModel):
    alert_keys: list[str]
    name_prompt_dismissed: bool


class DismissIn(BaseModel):
    kind: Literal["alert", "name-prompt"]
    keys: list[str] = Field(default_factory=list, max_length=500)


def _user(request: Request) -> str:
    auth = getattr(request.state, "auth", None)
    if auth and auth.user:
        return str(auth.user.id)
    raise HTTPException(status_code=401, detail="Authentication required")


async def _dismissals(request: Request) -> DismissalsView:
    repo = get_home_dismissal_repo(request)
    user_id = _user(request)
    alerts = await repo.keys(user_id=user_id, kind="alert")
    prompt = await repo.keys(user_id=user_id, kind=NAME_PROMPT)
    return DismissalsView(alert_keys=sorted(alerts), name_prompt_dismissed=bool(prompt))


@router.get("/dismissals", response_model=DismissalsView)
@require_permission("threads", "read")
async def get_dismissals(request: Request) -> DismissalsView:
    return await _dismissals(request)


@router.post("/dismissals", response_model=DismissalsView)
@require_permission("threads", "write")
async def post_dismissals(body: DismissIn, request: Request) -> DismissalsView:
    keys = [NAME_PROMPT] if body.kind == NAME_PROMPT else body.keys
    if body.kind == "alert" and not keys:
        raise HTTPException(status_code=422, detail="name at least one alert to dismiss")
    if any(len(k) > KEY_MAX or not k for k in keys):
        raise HTTPException(status_code=422, detail=f"each key is 1 to {KEY_MAX} characters")
    await get_home_dismissal_repo(request).dismiss(user_id=_user(request), kind=body.kind, keys=keys)
    return await _dismissals(request)


def _rules(cfg):
    """The rule file as the engine reads it (rules and quiet hours), and why it
    could not be read."""
    from app.gateway.trigger_engine_wiring import _quiet_hours, _resolve_rules_path
    from app.trigger_engine.config import ConfigLoader

    loader = ConfigLoader(path=_resolve_rules_path(cfg))
    config = loader.load()
    # The engine's own adapter, so the window is the one it enforces.
    return list(config.rules), _quiet_hours(config), loader.last_error


@router.get("/upcoming", response_model=UpcomingView)
@require_permission("threads", "read")
async def upcoming(request: Request) -> UpcomingView:
    now = datetime.now(UTC)
    calendar = await calendar_events(request.app.state, _user(request), now)
    cfg = request.app.state.config.trigger_engine
    if not cfg.enabled:
        return UpcomingView(engine_enabled=False, runs=[], calendar=calendar)
    rules, quiet, error = _rules(cfg)
    view = describe_upcoming(rules, now=now, engine_enabled=True, rules_error=error, quiet=quiet)
    return view.model_copy(update={"calendar": calendar})


@router.get("/today", response_model=MovedView)
@require_permission("threads", "read")
async def today(request: Request, since: datetime = Query(..., description="The start of the user's day, with its offset")) -> MovedView:
    if since.tzinfo is None:
        raise HTTPException(status_code=422, detail="since needs a time zone offset")
    since = since.astimezone(UTC)
    now = datetime.now(UTC)
    user_id = _user(request)

    changes: list[dict] | None = None
    names: dict[str, str] = {}
    service = getattr(request.app.state, "ledger_service", None)
    if service is not None:

        def read_ledger():
            return service.repo.changes_since(user_id, since), {p["id"]: p["name"] for p in service.repo.projects(user_id)}

        try:
            changes, names = await asyncio.to_thread(read_ledger)
        except Exception:  # noqa: BLE001 — reported as unavailable, never as "nothing moved"
            changes = None

    cfg = request.app.state.config.trigger_engine
    audit: list[dict] | None = None
    automations: SourceState = "off"
    if cfg.enabled:
        from app.trigger_engine.audit import AuditLog

        try:
            audit = AuditLog(path=Path(cfg.state_dir) / "audit.jsonl", actor=cfg.actor).entries()
            automations = "ok"
        except Exception:  # noqa: BLE001
            audit, automations = None, "unavailable"
    sessions, github = await asyncio.gather(session_items(since), github_items(request.app.state, user_id, since))
    return describe_moved(changes=changes, project_names=names, audit=audit, since=since, now=now, automations=automations, outside={"sessions": sessions, "github": github})
