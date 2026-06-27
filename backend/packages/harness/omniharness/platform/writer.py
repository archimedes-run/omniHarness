"""Thin platform event writer.

emit_platform_event() is the single entry point for product objects to
record events.  It builds a PlatformEvent, maps it to the existing
RunEventStore.put() interface, and returns the enriched dict (with seq
and created_at assigned by the store).

Design invariants
-----------------
- Uses the EXISTING store instance passed by the caller.  No second store
  or second table is ever created here.
- Per-thread seq assignment and the uq_events_thread_seq uniqueness
  constraint are reused verbatim — this function adds no seq logic.
- For no-run-yet events, pass run_id=None; the store receives the
  sentinel string "platform" so run_id remains NOT NULL in the DB.
"""

from __future__ import annotations

from omniharness.platform.events import EventSource, PlatformEvent
from omniharness.runtime.events.store.base import RunEventStore


async def emit_platform_event(
    store: RunEventStore,
    *,
    thread_id: str,
    event_type: str,
    source: EventSource = EventSource.RUN,
    run_id: str | None = None,
    user_id: str | None = None,
    category: str = "lifecycle",
    content: str = "",
    metadata: dict | None = None,
) -> PlatformEvent:
    """Append a platform event via the existing event store.

    Args:
        store:      The RunEventStore instance (db / memory / jsonl).
        thread_id:  Real chat thread_id, or a synthetic key for no-run-yet
                    events: ``f"plat-{object_type}-{object_id}"``.
        event_type: Free string, e.g. ``"workflow.step.started"``.
        source:     EventSource discriminator (default: EventSource.RUN).
        run_id:     Real run_id, or None when no run exists yet.
        user_id:    Owner; if None the store's contextvar resolution applies.
        category:   "lifecycle" | "message" | "trace" (default: "lifecycle").
        content:    Human-readable summary string (default: "").
        metadata:   Object references, e.g. {"workflow_id": "..."}.

    Returns:
        PlatformEvent with seq and created_at filled in by the store.
    """
    event = PlatformEvent(
        thread_id=thread_id,
        run_id=run_id,
        user_id=user_id,
        source=source,
        event_type=event_type,
        category=category,
        content=content,
        metadata=metadata or {},
    )
    result = await store.put(**event.to_store_kwargs())
    return PlatformEvent.from_dict(result)
