"""In-memory run registry with optional persistent RunStore backing."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from omniharness.utils.time import now_iso as _now_iso

from .schemas import DisconnectMode, RunStatus

if TYPE_CHECKING:
    from omniharness.runtime.runs.store.base import RunStore

logger = logging.getLogger(__name__)


@dataclass
class RunRecord:
    """Mutable record for a single run."""

    run_id: str
    thread_id: str
    assistant_id: str | None
    status: RunStatus
    on_disconnect: DisconnectMode
    multitask_strategy: str = "reject"
    metadata: dict = field(default_factory=dict)
    kwargs: dict = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    task: asyncio.Task | None = field(default=None, repr=False)
    abort_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    abort_action: str = "interrupt"
    error: str | None = None


#: An active run row in the store not updated for this long belongs to a
#: worker that died; it no longer holds its thread (write_when_idle).
OTHER_WORKER_RUN_STALE_AFTER = timedelta(hours=1)


class RunManager:
    """In-memory run registry with optional persistent RunStore backing.

    All mutations are protected by an asyncio lock. When a ``store`` is
    provided, serializable metadata is also persisted to the store so
    that run history survives process restarts.
    """

    def __init__(self, store: RunStore | None = None) -> None:
        self._runs: dict[str, RunRecord] = {}
        self._lock = asyncio.Lock()
        self._store = store
        #: Thread writes waiting for that thread's run to end (write_when_idle).
        self._deferred: dict[str, list[Callable[[], Awaitable[bool]]]] = {}
        #: Drains scheduled from finished run tasks (held until they finish).
        self._drains: set[asyncio.Task] = set()

    def _busy(self, thread_id: str, *, exclude: str | None = None) -> bool:
        """A run on this thread is in flight: pending, running, or its task not
        yet finished (a cancelled run is marked interrupted before its task
        unwinds, and may still write its checkpoint)."""
        for record in self._runs.values():
            if record.thread_id != thread_id or record.run_id == exclude:
                continue
            if record.status in (RunStatus.pending, RunStatus.running):
                return True
            if record.task is not None and not record.task.done():
                return True
        return False

    async def thread_busy(self, thread_id: str) -> bool:
        """Whether a run on this thread is in flight now."""
        async with self._lock:
            return self._busy(thread_id)

    async def _active_elsewhere(self, thread_id: str) -> bool:
        """A run on this thread that ANOTHER worker recorded as active.

        This manager only sees its own process's runs; the run store sees
        every worker's. A row still "pending"/"running" but not updated for
        OTHER_WORKER_RUN_STALE_AFTER is a crashed worker's, and not counted.
        A store that cannot be read is can't-tell: treated as busy (the post
        waits and is retried), never as idle.
        """
        if self._store is None:
            return False
        try:
            rows = await self._store.list_by_thread(thread_id, user_id=None)
        except Exception:
            logger.warning("Could not read runs of thread %s from the run store; treating it as busy", thread_id, exc_info=True)
            return True
        now = datetime.now(UTC)
        for row in rows or []:
            if row.get("run_id") in self._runs or row.get("status") not in ("pending", "running"):
                continue
            updated = row.get("updated_at") or row.get("created_at")
            try:
                when = datetime.fromisoformat(str(updated).replace("Z", "+00:00")) if updated else None
            except ValueError:
                when = None
            if when is not None and when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            if when is None or now - when < OTHER_WORKER_RUN_STALE_AFTER:
                return True
        return False

    async def write_when_idle(self, thread_id: str, write: Callable[[], Awaitable[bool]]) -> Literal["written", "queued", "elsewhere", "failed"]:
        """Write to a thread's checkpoint WITHOUT racing a run on it.

        A run holds the thread's state in memory and checkpoints it as it goes,
        so a write made while it runs is overwritten by its next checkpoint: a
        confirmed action's result posted from its card was lost that way
        (review of PR #58). Under the lock no run can start (create_or_reject
        takes it), so an idle thread is written now; a busy one is queued and
        written when its run ends (drain_deferred, from the run worker).

        `write` returns True only when the write persisted (re-read).
        """
        async with self._lock:
            if self._busy(thread_id):
                self._deferred.setdefault(thread_id, []).append(write)
                logger.info("Thread %s is running; a write is queued until the run ends", thread_id)
                return "queued"
            if await self._active_elsewhere(thread_id):
                # Another worker's run holds the thread: the caller waits and
                # tries again (this process is not told when that run ends).
                return "elsewhere"
            return "written" if await write() else "failed"

    async def drain_deferred(self, thread_id: str, *, finished_run_id: str) -> None:
        """Called by the run worker when a run ends: write what was queued for
        its thread, unless another run is already in flight (its end drains)."""
        await self._drain(thread_id, finished_run_id=finished_run_id)

    def attach_task(self, record: RunRecord, task: asyncio.Task) -> None:
        """Bind a run's task, and drain its thread's queue AFTER the task is done.

        The worker drains in its `finally`, while its own task is still running;
        a write queued after that drain (the task not yet done, so the thread
        still busy) was left in memory until the next run or a restart. The
        task's done-callback drains once nothing of the run is left.
        """
        record.task = task

        def drained(_task: asyncio.Task) -> None:
            loop = _task.get_loop()
            if not loop.is_closed():
                follow_up = loop.create_task(self._drain(record.thread_id, finished_run_id=record.run_id))
                self._drains.add(follow_up)
                follow_up.add_done_callback(self._drains.discard)

        task.add_done_callback(drained)

    async def _drain(self, thread_id: str, *, finished_run_id: str) -> None:
        async with self._lock:
            if thread_id not in self._deferred or self._busy(thread_id, exclude=finished_run_id):
                return
            writes = self._deferred.pop(thread_id)
            for write in writes:
                try:
                    if not await write():
                        logger.warning("A queued write to thread %s did not persist", thread_id)
                except Exception:
                    logger.warning("A queued write to thread %s failed", thread_id, exc_info=True)

    async def _persist_to_store(self, record: RunRecord) -> None:
        """Best-effort persist run record to backing store."""
        if self._store is None:
            return
        try:
            await self._store.put(
                record.run_id,
                thread_id=record.thread_id,
                assistant_id=record.assistant_id,
                status=record.status.value,
                multitask_strategy=record.multitask_strategy,
                metadata=record.metadata or {},
                kwargs=record.kwargs or {},
                created_at=record.created_at,
            )
        except Exception:
            logger.warning("Failed to persist run %s to store", record.run_id, exc_info=True)

    async def update_run_completion(self, run_id: str, **kwargs) -> None:
        """Persist token usage and completion data to the backing store."""
        if self._store is not None:
            try:
                await self._store.update_run_completion(run_id, **kwargs)
            except Exception:
                logger.warning("Failed to persist run completion for %s", run_id, exc_info=True)

    async def create(
        self,
        thread_id: str,
        assistant_id: str | None = None,
        *,
        on_disconnect: DisconnectMode = DisconnectMode.cancel,
        metadata: dict | None = None,
        kwargs: dict | None = None,
        multitask_strategy: str = "reject",
    ) -> RunRecord:
        """Create a new pending run and register it."""
        run_id = str(uuid.uuid4())
        now = _now_iso()
        record = RunRecord(
            run_id=run_id,
            thread_id=thread_id,
            assistant_id=assistant_id,
            status=RunStatus.pending,
            on_disconnect=on_disconnect,
            multitask_strategy=multitask_strategy,
            metadata=metadata or {},
            kwargs=kwargs or {},
            created_at=now,
            updated_at=now,
        )
        async with self._lock:
            self._runs[run_id] = record
        await self._persist_to_store(record)
        logger.info("Run created: run_id=%s thread_id=%s", run_id, thread_id)
        return record

    def get(self, run_id: str) -> RunRecord | None:
        """Return a run record by ID, or ``None``."""
        return self._runs.get(run_id)

    async def list_by_thread(self, thread_id: str) -> list[RunRecord]:
        """Return all runs for a given thread, newest first."""
        async with self._lock:
            # Dict insertion order matches creation order, so reversing it gives
            # us deterministic newest-first results even when timestamps tie.
            return [r for r in self._runs.values() if r.thread_id == thread_id]

    async def set_status(self, run_id: str, status: RunStatus, *, error: str | None = None) -> None:
        """Transition a run to a new status."""
        async with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                logger.warning("set_status called for unknown run %s", run_id)
                return
            record.status = status
            record.updated_at = _now_iso()
            if error is not None:
                record.error = error
        if self._store is not None:
            try:
                await self._store.update_status(run_id, status.value, error=error)
            except Exception:
                logger.warning("Failed to persist status update for run %s", run_id, exc_info=True)
        logger.info("Run %s -> %s", run_id, status.value)

    async def cancel(self, run_id: str, *, action: str = "interrupt") -> bool:
        """Request cancellation of a run.

        Args:
            run_id: The run ID to cancel.
            action: "interrupt" keeps checkpoint, "rollback" reverts to pre-run state.

        Sets the abort event with the action reason and cancels the asyncio task.
        Returns ``True`` if the run was in-flight and cancellation was initiated.
        """
        async with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                return False
            if record.status not in (RunStatus.pending, RunStatus.running):
                return False
            record.abort_action = action
            record.abort_event.set()
            if record.task is not None and not record.task.done():
                record.task.cancel()
            record.status = RunStatus.interrupted
            record.updated_at = _now_iso()
        logger.info("Run %s cancelled (action=%s)", run_id, action)
        return True

    async def create_or_reject(
        self,
        thread_id: str,
        assistant_id: str | None = None,
        *,
        on_disconnect: DisconnectMode = DisconnectMode.cancel,
        metadata: dict | None = None,
        kwargs: dict | None = None,
        multitask_strategy: str = "reject",
    ) -> RunRecord:
        """Atomically check for inflight runs and create a new one.

        For ``reject`` strategy, raises ``ConflictError`` if thread
        already has a pending/running run.  For ``interrupt``/``rollback``,
        cancels inflight runs before creating.

        This method holds the lock across both the check and the insert,
        eliminating the TOCTOU race in separate ``has_inflight`` + ``create``.
        """
        run_id = str(uuid.uuid4())
        now = _now_iso()

        _supported_strategies = ("reject", "interrupt", "rollback")

        async with self._lock:
            if multitask_strategy not in _supported_strategies:
                raise UnsupportedStrategyError(f"Multitask strategy '{multitask_strategy}' is not yet supported. Supported strategies: {', '.join(_supported_strategies)}")

            inflight = [r for r in self._runs.values() if r.thread_id == thread_id and r.status in (RunStatus.pending, RunStatus.running)]

            if multitask_strategy == "reject" and inflight:
                raise ConflictError(f"Thread {thread_id} already has an active run")

            if multitask_strategy in ("interrupt", "rollback") and inflight:
                for r in inflight:
                    r.abort_action = multitask_strategy
                    r.abort_event.set()
                    if r.task is not None and not r.task.done():
                        r.task.cancel()
                    r.status = RunStatus.interrupted
                    r.updated_at = now
                logger.info(
                    "Cancelled %d inflight run(s) on thread %s (strategy=%s)",
                    len(inflight),
                    thread_id,
                    multitask_strategy,
                )

            record = RunRecord(
                run_id=run_id,
                thread_id=thread_id,
                assistant_id=assistant_id,
                status=RunStatus.pending,
                on_disconnect=on_disconnect,
                multitask_strategy=multitask_strategy,
                metadata=metadata or {},
                kwargs=kwargs or {},
                created_at=now,
                updated_at=now,
            )
            self._runs[run_id] = record

        await self._persist_to_store(record)
        logger.info("Run created: run_id=%s thread_id=%s", run_id, thread_id)
        return record

    async def cleanup(self, run_id: str, *, delay: float = 300) -> None:
        """Remove a run record after an optional delay."""
        if delay > 0:
            await asyncio.sleep(delay)
        async with self._lock:
            self._runs.pop(run_id, None)
        logger.debug("Run record %s cleaned up", run_id)


class ConflictError(Exception):
    """Raised when multitask_strategy=reject and thread has inflight runs."""


class UnsupportedStrategyError(Exception):
    """Raised when a multitask_strategy value is not yet implemented."""
