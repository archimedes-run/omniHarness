"""A chat's tool selection as every reader sees it, new chats included.

A chat that has never stored a selection (a new chat) starts with the pinned
local sources AND the connector toolkits its owner has connected (an ACTIVE
connection), so "check my calendar" works in a new chat without a trip to the
tool menu. A selection the user has stored is used exactly as stored: a
connector they switched off in that chat stays off.

The default is computed, not written: every reader (the run's launch, the
chat's tool menu and its count, the tool-sources view, a confirmation's
rebuild of the proposing surface) calls `thread_sources`, so they cannot
disagree, and connecting or disconnecting an app is reflected in every chat
that has not chosen for itself. The first change the user makes in the menu
stores the whole selection, and from then on it is theirs.

Whose connections seed a chat: the chat's OWNER's, never another person's and
never the system user's. A scheduled run's chat is the system user's (the
trigger engine creates it), so automations keep exactly the tools their rule
configures (`default_tools`), as before.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def active_connector_slugs(app_state: Any, user_id: str | None) -> list[str]:
    """The connector toolkits `user_id` has an ACTIVE connection to, in the
    catalog's order. Empty for no user, the system user, or no repository; an
    unreadable repository is logged and read as none (the chat then starts
    with the pinned sources only, as before)."""
    from app.gateway.ownership import SYSTEM_OWNERS
    from omniharness.tools.connector_tools import CONNECTOR_TOOLKITS

    if not user_id or str(user_id) in SYSTEM_OWNERS:
        return []
    repo = getattr(app_state, "composio_connection_repo", None)
    if repo is None:
        return []
    try:
        rows = await repo.list_by_user(user_id=str(user_id))
    except Exception:  # noqa: BLE001 — a new chat without connectors, never a failed run
        logger.warning("connected apps could not be read; a new chat starts with the pinned sources only", exc_info=True)
        return []
    active = {str(row.get("toolkit", "")).upper() for row in rows if row.get("status") == "active"}
    return [tk["slug"] for tk in CONNECTOR_TOOLKITS if tk["slug"] in active]


async def thread_sources(app_state: Any, thread_id: str, *, owner_id: str | None, active: list[str] | None = None) -> list[str]:
    """The chat's selection: what it stored, or for a chat that stored none,
    the pinned sources plus `owner_id`'s connected toolkits.

    `owner_id` is the chat's owner (the caller, where the route already
    checked the caller owns the chat). `active` is `active_connector_slugs`
    when the caller already has it. Raises what the selection repository
    raises: each caller keeps its own failure handling.
    """
    repo = getattr(app_state, "thread_tool_selection_repo", None)
    if repo is None:
        raise LookupError("no thread tool-selection repository")
    read_stored = getattr(repo, "get_stored_sources", None)
    if read_stored is None:  # a repository without the distinction: as stored
        return list(await repo.get_sources(thread_id=thread_id))
    stored = await read_stored(thread_id=thread_id)
    if stored is not None:
        return stored
    slugs = active if active is not None else await active_connector_slugs(app_state, owner_id)
    return await repo.get_sources(thread_id=thread_id, default_sources=[f"connector:{slug}" for slug in slugs])


def connectors_switched_off(active: list[str], selected: list[str] | None) -> list[str]:
    """The connected toolkits this chat has switched off, in catalog order."""
    chosen = {sid.split(":", 1)[1].upper() for sid in (selected or []) if isinstance(sid, str) and sid.startswith("connector:")}
    return [slug for slug in active if slug not in chosen]
