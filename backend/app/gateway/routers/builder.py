"""Builder mode for a chat (Spec 010 FR-002, FR-003, FR-004): the "Building: <name>" chip.

Endpoints:
- GET    /api/threads/{thread_id}/builder  what this chat is building, or null
- DELETE /api/threads/{thread_id}/builder  the chip's x: drop the draft

Builder mode starts when the assistant calls a builder tool (never on
keywords) and is recorded beside the chat (app/gateway/builder/drafts.py).
Dropping it writes NOTHING to the config store: the draft is discarded, and
the chat's open builder save cards are refused (never run), so a dropped
draft cannot be saved by a later press.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission
from app.gateway.builder import drafts

router = APIRouter(prefix="/api", tags=["builder"])


class Building(BaseModel):
    kind: str = Field(..., description="agent, skill or automation")
    name: str = Field(..., description="Its slug, skill name or rule id")
    title: str = Field(..., description="What the chip shows")
    draft_id: str
    saved_version: int | None = Field(None, description="Set once the build was saved; the chip stays until x")


class BuilderState(BaseModel):
    thread_id: str
    building: Building | None = None


class BuilderStatus(BaseModel):
    available: bool
    reason: str | None = Field(None, description="Why the assistant is not offered the builder tools on this install")


class DropResult(BaseModel):
    thread_id: str
    dropped: bool
    refused_cards: int = 0


def _user_id(request: Request) -> str:
    auth = getattr(request.state, "auth", None)
    if auth and auth.user:
        return str(auth.user.id)
    raise HTTPException(status_code=401, detail="Authentication required")


def _view(active: dict | None) -> Building | None:
    if not active:
        return None
    return Building(kind=str(active.get("kind") or ""), name=str(active.get("name") or ""), title=str(active.get("title") or active.get("name") or ""), draft_id=str(active.get("draft_id") or ""), saved_version=active.get("saved_version"))


@router.get("/threads/{thread_id}/builder", response_model=BuilderState, summary="What this chat is building")
@require_permission("threads", "read", owner_check=True)
async def get_builder(thread_id: str, request: Request) -> BuilderState:
    try:
        active = drafts.active(_user_id(request), thread_id)
    except ValueError as exc:  # an unsafe thread id never reaches the filesystem
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return BuilderState(thread_id=thread_id, building=_view(active))


@router.delete("/threads/{thread_id}/builder", response_model=DropResult, summary="Drop this chat's draft (writes nothing to the config store)")
@require_permission("threads", "write", owner_check=True)
async def drop_builder(thread_id: str, request: Request) -> DropResult:
    user_id = _user_id(request)
    try:
        was = drafts.drop(user_id, thread_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    refused = 0
    if was is not None:
        from app.policy.builder_cards import refuse_open_builder_cards
        from app.policy.pending import PendingStore
        from omniharness.config import get_app_config

        policy = getattr(get_app_config(), "policy", None)
        if policy is not None and getattr(policy, "enabled", True):
            store = PendingStore(directory=Path(policy.state_dir) / "pending")
            refused = len(refuse_open_builder_cards(store, thread_id, user_id, reason="The draft was dropped, so it was not saved.", include_grants=True))
    return DropResult(thread_id=thread_id, dropped=was is not None, refused_cards=refused)


@router.get("/builder/status", response_model=BuilderStatus, summary="Whether the chat builder is offered on this install")
async def builder_status(request: Request) -> BuilderStatus:
    """Shown on Settings > Safety: the builder is not offered when the policy
    is off or the rules file in force names none of its tools, and that is
    said where the owner looks, not only in the log."""
    _user_id(request)
    from omniharness.runtime.builder.controller import get_builder_controller

    controller = get_builder_controller()
    if controller is None:
        return BuilderStatus(available=False, reason="the builder is not running in this process.")
    reason = controller.unavailable_reason()
    return BuilderStatus(available=reason is None, reason=reason)
