"""Question cards (specs/009-orchestration/question-card.md): list and answer.

`GET /api/threads/{thread_id}/questions`: the caller's questions in a thread,
newest first. `GET /api/questions?state=open`: the caller's open questions in
every thread (Home's waiting list). `POST /api/questions/{id}/answer` with
`{"option": i}` or `{"text": "..."}`: the owner's click or typed box; 409 when
the question is no longer open.

Only the question's owner answers, and only as a person: the internal token
(channels, the trigger engine) is refused here; a channel's owner answers by
replying, through the typed-reply path (service.answer_from_turn).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.gateway.authz import require_permission

logger = logging.getLogger(__name__)

router = APIRouter(tags=["questions"])


class AnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option: int | None = Field(default=None, ge=0, le=3)
    text: str | None = Field(default=None, max_length=2000)


async def _caller_id(request: Request) -> str:
    from app.gateway.deps import get_current_user

    user_id = await get_current_user(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return str(user_id)


@router.get("/api/threads/{thread_id}/questions")
@require_permission("threads", "read", owner_check=True)
async def list_thread_questions(thread_id: str, request: Request) -> dict[str, Any]:
    from app.gateway.questions import get_store, public_view

    user_id = await _caller_id(request)
    now = datetime.now(UTC)
    questions = [q for q in get_store().in_thread(thread_id) if q.owner_id == user_id]
    questions.sort(key=lambda q: q.created_at, reverse=True)
    return {"questions": [public_view(q, now) for q in questions]}


@router.get("/api/questions")
@require_permission("threads", "read")
async def list_questions(request: Request, state: str = Query(default="open", pattern="^(open|all)$")) -> dict[str, Any]:
    from app.gateway.questions import get_store, public_view

    user_id = await _caller_id(request)
    now = datetime.now(UTC)
    questions = [q for q in get_store().all() if q.owner_id == user_id and (state == "all" or q.is_open(now))]
    questions.sort(key=lambda q: q.created_at, reverse=True)
    return {"questions": [public_view(q, now) for q in questions]}


@router.post("/api/questions/{question_id}/answer")
@require_permission("threads", "write")
async def answer_question(question_id: str, body: AnswerRequest, request: Request) -> dict[str, Any]:
    from app.gateway.ownership import require_person
    from app.gateway.questions import AnswerRefused, answer_by_owner, dispatch, public_view

    require_person(request)
    user_id = await _caller_id(request)
    try:
        answered = answer_by_owner(question_id, user_id, option=body.option, text=body.text)
    except AnswerRefused as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
    result = await dispatch(answered, app=request.app, request=request) or {}
    return {"question": public_view(answered), "resume_run_id": result.get("resume_run_id")}
