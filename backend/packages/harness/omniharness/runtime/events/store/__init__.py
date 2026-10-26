import logging

from omniharness.runtime.events.store.base import RunEventStore
from omniharness.runtime.events.store.memory import MemoryRunEventStore

logger = logging.getLogger(__name__)


def make_run_event_store(config=None) -> RunEventStore:
    """Create a RunEventStore based on run_events.backend configuration."""
    backend = getattr(config, "backend", None) or "auto"
    if backend == "memory":
        from omniharness.persistence.engine import get_session_factory

        if get_session_factory() is not None:
            logger.warning("run_events.backend is 'memory' although the gateway has a database: run journals (the chat's display history of summarized conversations) are lost on every restart. Set run_events.backend to 'auto' or 'db'.")
        return MemoryRunEventStore()
    if backend in ("db", "auto"):
        from omniharness.persistence.engine import get_session_factory

        sf = get_session_factory()
        if sf is None:
            # No SQL database (database.backend=memory): nothing to persist to.
            return MemoryRunEventStore()
        from omniharness.runtime.events.store.db import DbRunEventStore

        return DbRunEventStore(sf, max_trace_content=getattr(config, "max_trace_content", 10240))
    if config.backend == "jsonl":
        from omniharness.runtime.events.store.jsonl import JsonlRunEventStore

        return JsonlRunEventStore()
    raise ValueError(f"Unknown run_events backend: {backend!r}")


__all__ = ["MemoryRunEventStore", "RunEventStore", "make_run_event_store"]
