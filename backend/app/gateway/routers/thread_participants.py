"""Which agents are in a chat (Feature 006, Phase 2: multi-agent chat).

Endpoints:
- GET    /api/threads/{thread_id}/participants          the agents in this chat
- POST   /api/threads/{thread_id}/participants          call one in: {"agent": name}
- DELETE /api/threads/{thread_id}/participants/{agent}  take it out

THIS IS THE STATE, NOT A HINT. The lead agent is always in a chat. Other
members are the user's own custom agents, stored on the thread
(`threads_meta.metadata_json["participants"]`). A user turn that @-mentions a
member calls it in (services.start_run); an agent that is not a member, or no
longer one, is never called, whatever the text says. Only the user's own turn
is read for mentions (Article III): a mention inside a tool result or another
agent's reply calls nobody.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.gateway.authz import require_permission
from app.gateway.deps import get_thread_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["thread-participants"])

LEAD = "lead_agent"
PARTICIPANTS_KEY = "participants"
#: More members than this is not a conversation anyone can follow.
MAX_PARTICIPANTS = 8


class Participant(BaseModel):
    name: str
    description: str = ""
    lead: bool = False


class ParticipantsResponse(BaseModel):
    thread_id: str
    participants: list[Participant] = Field(default_factory=list)


class AddParticipantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent: str = Field(min_length=1, max_length=128)


def _user_id(request: Request) -> str:
    auth = getattr(request.state, "auth", None)
    if auth and auth.user:
        return str(auth.user.id)
    raise HTTPException(status_code=401, detail="Authentication required")


async def stored_participants(thread_store: Any, thread_id: str, user_id: str | None) -> list[str]:
    """The thread's members other than the lead, in the order they were added."""
    row = await thread_store.get(thread_id, user_id=user_id)
    if row is None:
        return []
    raw = (row.get("metadata") or {}).get(PARTICIPANTS_KEY)
    return [name for name in raw if isinstance(name, str)] if isinstance(raw, list) else []


def _agent(name: str, user_id: str) -> Any:
    from omniharness.config.agents_config import load_agent_config, validate_agent_name

    try:
        valid = validate_agent_name(name)
        return load_agent_config(valid, user_id=user_id) if valid else None
    except (FileNotFoundError, ValueError):
        return None


def _view(thread_id: str, names: list[str], user_id: str) -> ParticipantsResponse:
    members = [Participant(name=LEAD, description="Leads this chat", lead=True)]
    for name in names:
        agent = _agent(name, user_id)
        # An agent deleted since it was called in is still listed, so removing
        # it stays possible; it is never called (start_run checks again).
        members.append(Participant(name=name, description=(agent.description if agent else "")))
    return ParticipantsResponse(thread_id=thread_id, participants=members)


@router.get("/threads/{thread_id}/participants", response_model=ParticipantsResponse)
@require_permission("threads", "read")
async def get_participants(thread_id: str, request: Request) -> ParticipantsResponse:
    user_id = _user_id(request)
    names = await stored_participants(get_thread_store(request), thread_id, user_id)
    return _view(thread_id, names, user_id)


@router.post("/threads/{thread_id}/participants", response_model=ParticipantsResponse)
@require_permission("threads", "write")
async def add_participant(thread_id: str, body: AddParticipantRequest, request: Request) -> ParticipantsResponse:
    user_id = _user_id(request)
    store = get_thread_store(request)
    agent = _agent(body.agent, user_id)
    if agent is None or agent.name == LEAD:
        raise HTTPException(status_code=404, detail=f"no agent named {body.agent!r}")
    row = await store.get(thread_id, user_id=user_id)
    if row is None:
        # A chat with no run yet (the new-chat page writes before its first send).
        if await store.get(thread_id, user_id=None) is not None:
            raise HTTPException(status_code=404, detail="no such thread")
        await store.create(thread_id, user_id=user_id, metadata={})
    names = await stored_participants(store, thread_id, user_id)
    if agent.name not in names:
        if len(names) >= MAX_PARTICIPANTS:
            raise HTTPException(status_code=409, detail=f"a chat can have at most {MAX_PARTICIPANTS} called-in agents")
        names.append(agent.name)
        await store.update_metadata(thread_id, {PARTICIPANTS_KEY: names}, user_id=user_id)
    return _view(thread_id, names, user_id)


@router.delete("/threads/{thread_id}/participants/{agent}", response_model=ParticipantsResponse)
@require_permission("threads", "write")
async def remove_participant(thread_id: str, agent: str, request: Request) -> ParticipantsResponse:
    user_id = _user_id(request)
    store = get_thread_store(request)
    if agent == LEAD:
        raise HTTPException(status_code=409, detail="the lead agent leads every chat and cannot be removed")
    names = [name for name in await stored_participants(store, thread_id, user_id) if name != agent]
    if await store.get(thread_id, user_id=user_id) is not None:
        await store.update_metadata(thread_id, {PARTICIPANTS_KEY: names}, user_id=user_id)
    return _view(thread_id, names, user_id)
