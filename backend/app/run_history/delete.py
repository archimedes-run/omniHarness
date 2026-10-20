"""Deleting the run history, and with it the automations' conversation threads.

The lead's choice for Feature 006: deleting means deleting. A run's content
also lives in the LangGraph thread the automation ran in (its checkpoints hold
every message, tool call and tool result), so deleting only the run history
would leave the same content one click away. This deletes, for every
automation thread (the rule-to-thread map's threads and every thread a stored
automation run names, both written by the server, never chosen by a request):

  * the thread's checkpoints (every message, tool call and result),
  * its thread record (so it leaves the thread list),
  * its files on disk (uploads, outputs, workspace),
  * its run records and run event traces,

then forgets each rule's thread, so the next firing starts a fresh one, and
deletes every stored run. Kept: the automations themselves, their delivery log
(times and outcomes, no content), and any message still waiting for delivery
(held for quiet hours).

SAFETY. It refuses (ThreadsBusy) while any of those threads has a run in
progress, rather than deleting under it, and while a firing holds the rule
map's cross-process firing lock (a firing in ANY worker). The map itself is a
file the engine re-reads before each firing, so a forgotten thread is never
reused by a worker holding an old copy. While the trigger engine runs, the
whole deletion runs on the engine's own worker, so no firing can start, or
write to a thread, between the check and the delete. A thread that cannot be
deleted is reported by id, never reported as deleted.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.run_history.recorder import AUTOMATION

logger = logging.getLogger(__name__)

#: How long one thread's deletion may take before it is reported as failed.
STEP_TIMEOUT = 60.0
#: How long to wait for a firing in progress (any worker) before refusing.
LOCK_WAIT = 5.0


class ThreadsBusy(RuntimeError):
    """A run is in progress in an automation thread; nothing was deleted."""

    def __init__(self, thread_ids: list[str]) -> None:
        super().__init__(f"{len(thread_ids)} automation thread(s) have a run in progress")
        self.thread_ids = thread_ids


@dataclass
class DeleteResult:
    runs: int
    threads_deleted: list[str] = field(default_factory=list)
    threads_failed: dict[str, str] = field(default_factory=dict)


def _rule_map(app):
    """The engine's live rule-to-thread map, or the one on disk when the engine
    is not running in this worker."""
    handle = getattr(app.state, "trigger_engine", None)
    loop = getattr(handle, "loop", None)
    if loop is not None and getattr(handle, "running", False):
        return loop.threads, loop
    from app.trigger_engine.threads import RuleThreadMap
    from omniharness.config.app_config import get_app_config

    def _never(rule_id: str) -> str:
        raise RuntimeError("not creating threads while deleting")

    state = Path(get_app_config().trigger_engine.state_dir)
    return RuleThreadMap(path=state / "threads.json", create_thread=_never), None


async def _busy(app, thread_ids: set[str]) -> list[str]:
    from omniharness.runtime.runs.schemas import RunStatus

    manager = getattr(app.state, "run_manager", None)
    if manager is None:
        return []
    busy = []
    for tid in sorted(thread_ids):
        if any(r.status in (RunStatus.pending, RunStatus.running) for r in await manager.list_by_thread(tid)):
            busy.append(tid)
    return busy


async def delete_thread_everywhere(app, thread_id: str) -> None:
    """Every trace of one thread, strictly: any step failing raises.

    The same steps as DELETE /api/threads/{id} (routers/threads.py), which
    are best-effort there; here a failure is reported, because the person was
    told the content is gone. Plus the run records and event traces, which that
    endpoint leaves.
    """
    from omniharness.config.paths import get_paths

    state = app.state
    store = getattr(state, "thread_store", None)
    record = await store.get(thread_id, user_id=None) if store is not None else None
    owner = (record or {}).get("user_id")

    preview = getattr(state, "preview_session_manager", None)
    if preview is not None:
        await preview.stop_thread_sessions(thread_id=thread_id)

    paths = get_paths()
    for user_id in {owner, "default", None}:
        paths.delete_thread_dir(thread_id, user_id=user_id)

    checkpointer = getattr(state, "checkpointer", None)
    if checkpointer is not None and hasattr(checkpointer, "adelete_thread"):
        await checkpointer.adelete_thread(thread_id)

    events = getattr(state, "run_event_store", None)
    if events is not None:
        await events.delete_by_thread(thread_id)

    runs = getattr(state, "run_store", None)
    if runs is not None:
        for run in await runs.list_by_thread(thread_id, user_id=None, limit=10_000):
            await runs.delete(run["run_id"])

    if store is not None:
        await store.delete(thread_id, user_id=None)


async def delete_history_and_threads(app) -> DeleteResult:
    """Delete every automation thread, then the whole run history. Raises
    ThreadsBusy, having deleted nothing, when one of the threads is running."""
    history = app.state.run_history
    rule_map, engine = _rule_map(app)
    main = asyncio.get_running_loop()

    def run(coro) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, main).result(timeout=STEP_TIMEOUT)

    def critical() -> DeleteResult:
        # The engine holds this lock for each firing, in whichever worker runs
        # it. Not had within LOCK_WAIT: a firing is in progress; refuse.
        with rule_map.firing_lock(timeout=LOCK_WAIT) as held:
            if not held:
                raise ThreadsBusy(["(a firing in another worker)"])
            return _delete_locked()

    def _delete_locked() -> DeleteResult:
        by_rule = {rule: rule_map.thread_of(rule) for rule in rule_map.known_rules()}
        thread_ids = {t for t in by_rule.values() if t} | history.thread_ids(kind=AUTOMATION)
        busy = run(_busy(app, thread_ids))
        if busy:
            raise ThreadsBusy(busy)
        result = DeleteResult(runs=0)
        for tid in sorted(thread_ids):
            try:
                run(delete_thread_everywhere(app, tid))
                result.threads_deleted.append(tid)
            except Exception as exc:  # noqa: BLE001 — reported per thread, by id
                logger.exception("run history: deleting automation thread %s failed", tid)
                result.threads_failed[tid] = type(exc).__name__
        for rule, tid in by_rule.items():
            if tid in result.threads_deleted:
                rule_map.forget(rule)
        result.runs = history.delete_all()
        return result

    if engine is not None:
        # On the engine's worker: no firing runs while this does.
        return await engine.runner.offload(critical)
    return await asyncio.to_thread(critical)
