"""Per-conversation skill removal (Feature 006, the chat bar's skill chips).

Endpoints:
- GET /api/threads/{thread_id}/skills — the skills removed from this thread
- PUT /api/threads/{thread_id}/skills — set them

Works before the thread has a run: the new-chat page writes against its
client-generated thread id, exactly as it does for /tools. The exclusion is
loaded server-side at run launch (services.py) into the runtime context as
``excluded_skills``; it is never accepted from a run's request body.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission
from app.gateway.deps import get_thread_skill_exclusion_repo

router = APIRouter(prefix="/api", tags=["thread-skills"])


def _get_user_id(request: Request) -> str:
    auth = getattr(request.state, "auth", None)
    if auth and auth.user:
        return str(auth.user.id)
    raise HTTPException(status_code=401, detail="Authentication required")


class SkillExclusionResponse(BaseModel):
    thread_id: str
    excluded: list[str] = Field(default_factory=list, description="Skill names removed from this conversation")


class SkillExclusionUpdateRequest(BaseModel):
    excluded: list[str] = Field(default_factory=list, max_length=500)


@router.get("/threads/{thread_id}/skills", response_model=SkillExclusionResponse)
@require_permission("threads", "read")
async def get_thread_skills(thread_id: str, request: Request) -> SkillExclusionResponse:
    user_id = _get_user_id(request)
    repo = get_thread_skill_exclusion_repo(request)
    return SkillExclusionResponse(thread_id=thread_id, excluded=await repo.get_excluded(thread_id=thread_id, user_id=user_id))


@router.put("/threads/{thread_id}/skills", response_model=SkillExclusionResponse)
@require_permission("threads", "write")
async def put_thread_skills(thread_id: str, body: SkillExclusionUpdateRequest, request: Request) -> SkillExclusionResponse:
    from omniharness.persistence.thread_skill_exclusion.sql import ThreadOwnedElsewhere

    user_id = _get_user_id(request)
    repo = get_thread_skill_exclusion_repo(request)
    try:
        saved = await repo.set_excluded(thread_id=thread_id, user_id=user_id, excluded=body.excluded)
    except ThreadOwnedElsewhere as exc:
        raise HTTPException(status_code=404, detail="no such thread") from exc
    return SkillExclusionResponse(thread_id=thread_id, excluded=saved)
