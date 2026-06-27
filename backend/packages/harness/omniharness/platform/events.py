"""Platform event envelope.

Defines the shared event shape all product objects (Workflows, Triggers,
Watchers, …) emit via the existing run_events table.  There is exactly
ONE physical representation: a RunEventRow.  PlatformEvent is a typed
VIEW over that row — it is not a second persistence path.

Back-compat rule
----------------
``source = NULL`` in the DB means "run" (all pre-existing chat / agent /
trace events).  Code that reads events from the store should treat a
missing or NULL ``source`` as ``EventSource.RUN``.

No-run-yet convention
---------------------
Some product events fire before a run exists (e.g. a Workflow receiving
an external trigger).  For those cases the caller supplies:

    thread_id = f"plat-{object_type}-{object_id}"   # synthetic, scoped
    run_id    = None   →  stored as sentinel "platform"

The synthetic thread_id keeps the per-thread ``uq_events_thread_seq``
constraint isolated from real chat-thread events.  Use only chars in
``[A-Za-z0-9_-]`` so the JSONL backend's path-safety check passes.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from omniharness.persistence.models.run_event import RunEventRow

_PLATFORM_RUN_SENTINEL = "platform"


class EventSource(StrEnum):
    """Discriminator values for run_events.source.

    This enum is the single source of truth.  The DB column docs and the
    PlatformEvent type both import from here.
    """

    RUN = "run"
    """Default — all existing chat/agent/trace events (also back-compat for NULL)."""
    WORKFLOW = "workflow"
    TRIGGER = "trigger"
    WATCHER = "watcher"
    NOTIFICATION = "notification"
    APPROVAL = "approval"
    CAPABILITY = "capability"
    CHANNEL = "channel"


class PlatformEvent(BaseModel):
    """Typed view over a run_events row for platform product objects.

    Callers build a PlatformEvent, then persist it via emit_platform_event()
    which delegates to the existing RunEventStore.  No second store is ever
    instantiated.
    """

    thread_id: str
    run_id: str | None = None
    """None when the event fires before a run exists. Stored as 'platform' sentinel."""
    user_id: str | None = None
    source: EventSource = EventSource.RUN
    event_type: str
    """Free string the producer defines, e.g. 'workflow.step.started'."""
    category: str = Field(default="lifecycle")
    """Reuses existing run_events categories: 'message' | 'trace' | 'lifecycle'."""
    content: str = ""
    metadata: dict = Field(default_factory=dict)
    """Object references (workflow_id, trigger_id, …) go here — never new columns."""
    seq: int | None = None
    """Assigned by the store on write; None before persistence."""
    created_at: datetime | str | None = None
    """Assigned by the store on write; None before persistence."""

    def to_store_kwargs(self) -> dict:
        """Return keyword args ready to pass directly to RunEventStore.put()."""
        return {
            "thread_id": self.thread_id,
            "run_id": self.run_id or _PLATFORM_RUN_SENTINEL,
            "event_type": self.event_type,
            "category": self.category,
            "content": self.content,
            "metadata": self.metadata,
            "source": self.source.value,
        }

    @classmethod
    def from_row(cls, row: RunEventRow) -> PlatformEvent:
        """Reconstruct a PlatformEvent from a persisted RunEventRow."""
        return cls(
            thread_id=row.thread_id,
            run_id=None if row.run_id == _PLATFORM_RUN_SENTINEL else row.run_id,
            user_id=row.user_id,
            source=EventSource(row.source or EventSource.RUN),
            event_type=row.event_type,
            category=row.category,
            content=row.content or "",
            metadata=row.event_metadata or {},
            seq=row.seq,
            created_at=row.created_at,
        )

    @classmethod
    def from_dict(cls, d: dict) -> PlatformEvent:
        """Reconstruct a PlatformEvent from a store.put() result dict."""
        raw_run_id = d.get("run_id")
        return cls(
            thread_id=d["thread_id"],
            run_id=None if raw_run_id == _PLATFORM_RUN_SENTINEL else raw_run_id,
            user_id=d.get("user_id"),
            source=EventSource(d.get("source") or EventSource.RUN),
            event_type=d["event_type"],
            category=d.get("category", "lifecycle"),
            content=d.get("content", ""),
            metadata=d.get("metadata") or {},
            seq=d.get("seq"),
            created_at=d.get("created_at"),
        )
