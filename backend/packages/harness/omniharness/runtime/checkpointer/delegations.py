"""The checkpoints of a chat's delegations (Feature 006).

A delegated or @-called agent checkpoints under its OWN key,
``<chat thread id>/subagent/<call id>/<random>`` (subagents.executor
.subagent_checkpoint_key), so deleting the chat's own thread left every
delegation's full message history behind (review of PR #58).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def delegation_sqlite_path(database_file: str) -> str:
    """Where delegations checkpoint on a SQLite install: a file of their own
    next to the app's database.

    NOT THE APP'S FILE. A delegation runs INSIDE its lead's run, and the lead's
    connection to that file can hold the write lock while it waits for the
    delegation; the delegation's checkpoint writes then waited behind it, and
    were intermittently lost when its connection closed (review of PR #58).
    """
    from pathlib import Path

    path = Path(database_file)
    return str(path.with_name(f"{path.stem}-delegations{path.suffix or '.db'}"))


def delegation_prefix(thread_id: str) -> str:
    return f"{thread_id}/subagent/"


async def delegation_thread_ids(checkpointer: Any, thread_id: str) -> list[str]:
    """Every delegation checkpoint key under a chat, read from the store."""
    prefix = delegation_prefix(thread_id)
    found: set[str] = set()
    conn = getattr(checkpointer, "conn", None)
    module = type(checkpointer).__module__
    if conn is not None and "sqlite" in module:
        # LIKE with an escape: a thread id's "_" must not act as a wildcard.
        pattern = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        async with conn.execute("SELECT DISTINCT thread_id FROM checkpoints WHERE thread_id LIKE ? ESCAPE '\\'", (pattern,)) as cursor:
            found.update(row[0] for row in await cursor.fetchall())
    elif conn is not None and "postgres" in module:
        pattern = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        async with conn.cursor() as cursor:
            await cursor.execute("SELECT DISTINCT thread_id FROM checkpoints WHERE thread_id LIKE %s", (pattern,))
            found.update(row[0] if isinstance(row, tuple) else row["thread_id"] for row in await cursor.fetchall())
    else:
        storage = getattr(checkpointer, "storage", None)
        if isinstance(storage, dict):
            found.update(key for key in storage if isinstance(key, str))
        else:
            async for item in checkpointer.alist(None):
                found.add(str(item.config.get("configurable", {}).get("thread_id", "")))
    return sorted(t for t in found if t.startswith(prefix))


async def delete_delegation_checkpoints(checkpointer: Any, thread_id: str, *, app_config: Any = None) -> int:
    """Delete every delegation checkpoint of a chat, wherever it is stored
    (the app's checkpointer, and a SQLite install's delegations file).
    Returns how many delegation keys were deleted."""
    keys = await delegation_thread_ids(checkpointer, thread_id)
    for key in keys:
        await checkpointer.adelete_thread(key)
    database = getattr(app_config, "database", None)
    if getattr(app_config, "checkpointer", None) is None and getattr(database, "backend", None) == "sqlite":
        import os

        path = delegation_sqlite_path(database.checkpointer_sqlite_path)
        if os.path.exists(path):
            import aiosqlite
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

            async with aiosqlite.connect(path, timeout=30) as conn:
                saver = AsyncSqliteSaver(conn)
                await saver.setup()
                own = await delegation_thread_ids(saver, thread_id)
                for key in own:
                    await saver.adelete_thread(key)
                keys += own
    return len(keys)
