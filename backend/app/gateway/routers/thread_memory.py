"""Memory off in a chat (live chat 2026-11-14; omniharness.agents.memory_switch).

Endpoints:
- GET /api/threads/{thread_id}/memory: {"memory_off": bool, "source": ...}
- PUT /api/threads/{thread_id}/memory {"memory_off": bool}: the composer's
  "Don't use memory in this chat" toggle and the "Memory off in this chat"
  chip's undo. Only the chat's owner; per chat, never global.

The switch is stored on the chat's record (threads_meta metadata, a
server-reserved key no thread create or patch can set) and read by the
server at every run launch (services.start_run), which puts the server-owned
run key `memory_off` in the run's context. A chat that has no record yet (a
new chat before its first message) passes the toggle with its first message;
the server can only turn memory OFF from a run request, never on.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.gateway.authz import require_permission

router = APIRouter(prefix="/api", tags=["thread-memory"])

#: Thread metadata key (threads router: _SERVER_RESERVED_METADATA_KEYS).
MEMORY_OFF_META = "memory_off"
#: Why it is off: "toggle" (the owner's switch) or "message" (their words).
MEMORY_OFF_SOURCE_META = "memory_off_source"


class MemorySwitch(BaseModel):
    thread_id: str
    memory_off: bool
    source: str | None = None


class MemorySwitchUpdate(BaseModel):
    memory_off: bool


async def chat_memory_off(thread_store: Any, thread_id: str) -> tuple[bool, str | None]:
    """The chat's stored switch, whoever reads it (access decided by the caller)."""
    if thread_store is None:
        return False, None
    try:
        record = await thread_store.get(thread_id, user_id=None)
    except Exception:  # noqa: BLE001 - unreadable: memory stays as configured
        return False, None
    metadata = (record or {}).get("metadata") or {}
    return metadata.get(MEMORY_OFF_META) is True, metadata.get(MEMORY_OFF_SOURCE_META)


async def set_chat_memory_off(thread_store: Any, thread_id: str, off: bool, source: str) -> bool:
    """Store the switch on the chat's record; False when it has none yet."""
    if thread_store is None:
        return False
    record = await thread_store.get(thread_id, user_id=None)
    if record is None:
        return False
    await thread_store.update_metadata(thread_id, {MEMORY_OFF_META: off, MEMORY_OFF_SOURCE_META: source if off else None}, user_id=None)
    return True


@router.get("/threads/{thread_id}/memory", response_model=MemorySwitch)
@require_permission("threads", "read", owner_check=True)
async def get_thread_memory(thread_id: str, request: Request) -> MemorySwitch:
    from app.gateway.deps import get_thread_store

    off, source = await chat_memory_off(get_thread_store(request), thread_id)
    return MemorySwitch(thread_id=thread_id, memory_off=off, source=source if off else None)


@router.put("/threads/{thread_id}/memory", response_model=MemorySwitch)
@require_permission("threads", "write", owner_check=True)
async def put_thread_memory(thread_id: str, body: MemorySwitchUpdate, request: Request) -> MemorySwitch:
    from app.gateway.deps import get_thread_store
    from app.gateway.ownership import require_thread_access

    await require_thread_access(request, thread_id, require_existing=True)
    store = get_thread_store(request)
    if not await set_chat_memory_off(store, thread_id, body.memory_off, "toggle"):
        raise HTTPException(status_code=404, detail="no such chat yet: send the toggle with the first message")
    return MemorySwitch(thread_id=thread_id, memory_off=body.memory_off, source="toggle" if body.memory_off else None)
