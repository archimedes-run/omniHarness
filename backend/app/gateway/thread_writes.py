"""Server writes to a thread's messages, as a proper new checkpoint.

The earlier pattern (`checkpointer.aput(config, same_checkpoint_with_new_values,
metadata, {})`) kept the checkpoint's id and declared no new channel
versions. Savers that store channel values per version (InMemorySaver keeps
blobs keyed by (channel, version) and writes only `new_versions`;
the Postgres saver does the same in its blobs table) never stored the new
messages, so the write could be silently lost; the SQLite saver happened to
keep them because it serialises the whole checkpoint. Here the messages
channel gets the saver's next version and the checkpoint a new id, with the
current one as its parent: the same shape a graph step writes.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


async def write_thread_messages(checkpointer: Any, thread_id: str, change: Callable[[list[Any]], list[Any] | None]) -> bool | None:
    """Apply `change` to the thread's messages and save the result as a new
    checkpoint. `change` returns the new list, or None for no change.
    Returns True when written, False when `change` made no change, None
    when the thread has no saved state."""
    from langgraph.checkpoint.base import copy_checkpoint, create_checkpoint

    from omniharness.utils.time import now_iso

    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    current = await checkpointer.aget_tuple(config)
    if current is None:
        return None
    checkpoint = copy_checkpoint(current.checkpoint)
    values = dict(checkpoint.get("channel_values") or {})
    updated = change(list(values.get("messages") or []))
    if updated is None:
        return False
    values["messages"] = updated
    versions = dict(checkpoint.get("channel_versions") or {})
    version = checkpointer.get_next_version(versions.get("messages"), None)
    versions["messages"] = version
    checkpoint["channel_values"] = values
    checkpoint["channel_versions"] = versions
    metadata = dict(getattr(current, "metadata", {}) or {})
    step = int(metadata.get("step", 0) or 0) + 1
    metadata.update({"updated_at": now_iso(), "source": "update", "step": step})
    new = create_checkpoint(checkpoint, None, step)
    parent = getattr(current, "config", None) or config
    await checkpointer.aput(parent, new, metadata, {"messages": version})
    return True
