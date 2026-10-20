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

THE LEDGER. Which threads are the automations' is read from the run
history's own ledger (store.automation_threads), written when the engine
creates a thread and whenever an automation run names one. A ledger row stays
until its thread is really gone, so a failed delete is retried (next delete,
and `sweep_threads` at startup and after every retention purge). The sweep
also deletes threads no stored run names any more, once their rule is gone, and
ROTATES a live rule's thread once its oldest content is past the retention (the
rule's next firing starts a new thread; the old one is deleted), so retention
covers content wherever it is stored, not only the run history.

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
import json
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
    #: Kept, with only content inside the retention: a person wrote in them.
    threads_trimmed: list[str] = field(default_factory=list)


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

    # Re-check: a run (a person's, on any worker) that wrote to the thread
    # during the delete leaves a checkpoint behind. Then it is NOT gone: raise,
    # so it is reported and retried, never reported as deleted.
    if checkpointer is not None and await checkpointer.aget_tuple({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}) is not None:
        raise ThreadsBusy([thread_id])


async def _locked(app, work, *, refuse: bool = True):
    """Run `work(rule_map, run)` holding the cross-process firing lock: on the
    engine's own worker when it runs here, else on a thread. `run(coro)` runs a
    coroutine on the gateway's loop from there. With `refuse`, a firing in
    progress (any worker) raises ThreadsBusy; without, returns None."""
    rule_map, engine = _rule_map(app)
    main = asyncio.get_running_loop()

    def run(coro) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, main).result(timeout=STEP_TIMEOUT)

    def critical():
        with rule_map.firing_lock(timeout=LOCK_WAIT) as held:
            if not held:
                if refuse:
                    raise ThreadsBusy(["(a firing in another worker)"])
                return None
            return work(rule_map, run)

    if engine is not None:
        # On the engine's worker: no firing runs while this does.
        return await engine.runner.offload(critical)
    return await asyncio.to_thread(critical)


def _is_person(message: Any) -> bool:
    """Could this message be a person's own? A human message that is not the
    engine's injected prompt (signed turn id) and carries no harness `name`
    (summary, todo_reminder...). Conservative: when unsure, keep it."""
    from app.gateway.internal_auth import TURN_ID_PREFIX

    get = message.get if isinstance(message, dict) else (lambda k, d=None: getattr(message, k, d))
    kind = get("type") or get("role")
    mid = get("id") or ""
    return kind in ("human", "user") and not get("name") and not str(mid).startswith(TURN_ID_PREFIX)


def _message_key(message: Any) -> str:
    get = message.get if isinstance(message, dict) else (lambda k, d=None: getattr(message, k, d))
    return str(get("id") or "") or json.dumps([get("type"), get("content")], default=str, sort_keys=True)


class TrimIncomplete(RuntimeError):
    """A big trim stopped after MAX_TRIM_WRITES rewrites; the next sweep goes on
    (the trim is idempotent and resumable: each rewrite stands on its own)."""


#: Checkpoint rewrites per trim call, so one call stays well inside STEP_TIMEOUT.
MAX_TRIM_WRITES = 200


def _get(message: Any, key: str):
    return message.get(key) if isinstance(message, dict) else getattr(message, key, None)


async def trim_thread(app, thread_id: str, cutoff) -> bool:
    """Retention for a thread a PERSON also wrote in: remove only content older
    than `cutoff`, keep the conversation. Returns True when the thread is kept;
    False when no person's message is inside the window, so the caller deletes
    the whole thread.

    A message's age is the time of the first checkpoint that holds it. The
    trim REWRITES each existing checkpoint IN PLACE (same id, same time, same
    parent), with the messages older than the cutoff removed. Nothing is
    deleted and no new checkpoint is made, so:
      * a checkpoint another worker commits meanwhile (a person's newest
        message) is never touched or lost; it is trimmed by the next sweep;
      * every message keeps its age, so the next trim still sees old content
        as old (no extension of the retention);
      * nothing is rewritten when nothing is older than the cutoff.
    Before rewriting, the latest checkpoint is re-read; if it changed since the
    thread was read, the trim stops (returns True: kept) and the next sweep
    retries. Callers hold the cross-process firing lock (sweep_threads).
    Limit, stated: pending writes stored beside checkpoints by some saver
    backends are not rewritten."""
    from datetime import UTC, datetime

    cp = getattr(app.state, "checkpointer", None)
    if cp is None:
        return False
    cfg = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    tuples = [t async for t in cp.alist(cfg)]
    if not tuples:
        return False
    first: dict[str, datetime] = {}
    for t in tuples:
        ts = datetime.fromisoformat(str(t.checkpoint.get("ts")))
        ts = ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts
        for m in (t.checkpoint.get("channel_values") or {}).get("messages") or []:
            k = _message_key(m)
            first[k] = min(first.get(k, ts), ts)
    old = {k for k, ts in first.items() if ts < cutoff}
    # A tool result never outlives its tool call: a result whose call is being
    # removed is removed with it (a thread starting with an orphan tool result
    # is refused by the model providers).
    removed_calls = set()
    for t in tuples:
        for m in (t.checkpoint.get("channel_values") or {}).get("messages") or []:
            if _message_key(m) in old:
                for call in _get(m, "tool_calls") or []:
                    call_id = call.get("id") if isinstance(call, dict) else getattr(call, "id", None)
                    if call_id:
                        removed_calls.add(call_id)
    for t in tuples:
        for m in (t.checkpoint.get("channel_values") or {}).get("messages") or []:
            if _get(m, "tool_call_id") in removed_calls:
                old.add(_message_key(m))
    latest = tuples[0]
    messages = (latest.checkpoint.get("channel_values") or {}).get("messages") or []
    if not any(_is_person(m) for m in messages if _message_key(m) not in old):
        return False
    if not old:
        return True  # nothing past the retention: no rewrite at all
    again = await cp.aget_tuple(cfg)
    if again is None or again.checkpoint.get("id") != latest.checkpoint.get("id"):
        return True  # written meanwhile: leave it, the next sweep retries
    writes = 0
    for t in tuples:
        values = dict(t.checkpoint.get("channel_values") or {})
        kept = [m for m in values.get("messages") or [] if _message_key(m) not in old]
        if len(kept) == len(values.get("messages") or []):
            continue
        if writes >= MAX_TRIM_WRITES:
            raise TrimIncomplete(f"{thread_id}: stopped after {writes} rewrites; continued by the next sweep")
        writes += 1
        values["messages"] = kept
        checkpoint = {**t.checkpoint, "channel_values": values}
        parent = t.parent_config or {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
        await cp.aput(parent, checkpoint, dict(t.metadata or {}), {})
    runs = getattr(app.state, "run_store", None)
    events = getattr(app.state, "run_event_store", None)
    if runs is not None:
        for r in await runs.list_by_thread(thread_id, user_id=None, limit=10_000):
            created = str(r.get("created_at") or "")
            if created and datetime.fromisoformat(created).replace(tzinfo=datetime.fromisoformat(created).tzinfo or UTC) < cutoff:
                if events is not None:
                    await events.delete_by_run(thread_id, r["run_id"])
                await runs.delete(r["run_id"])
    return True


def _delete_ledgered(app, history, rule_map, run, thread_ids, result: DeleteResult, *, trim_before=None) -> None:
    """Delete each ledger thread; the ledger row goes only when the thread is
    really gone, so a failure is retried by the next call or the startup sweep.
    With `trim_before` (retention, not "Delete run history"), a thread a person
    wrote in within the window is trimmed instead (see trim_thread)."""
    mapped = {rule: rule_map.thread_of(rule) for rule in rule_map.known_rules()}
    for tid in sorted(thread_ids):
        if trim_before is not None:
            try:
                kept = run(trim_thread(app, tid, trim_before))
            except Exception as exc:  # noqa: BLE001 — a failed TRIM stays a trim
                logger.exception("run history: trimming automation thread %s failed; retried as a trim", tid)
                history.trim_failed(tid, type(exc).__name__)
                result.threads_failed[tid] = type(exc).__name__
                continue
            if kept:
                # Kept in the ledger: still the engine's thread, so "Delete run
                # history" deletes it (the dialog says: including what you
                # wrote in it). Trimming again finds nothing older to remove.
                history.trim_done(tid)
                result.threads_trimmed.append(tid)
                for rule, mapped_tid in mapped.items():
                    if mapped_tid == tid:
                        rule_map.forget(rule)
                continue
        try:
            run(delete_thread_everywhere(app, tid))
        except Exception as exc:  # noqa: BLE001 — reported per thread, by id
            logger.exception("run history: deleting automation thread %s failed", tid)
            history.thread_failed(tid, type(exc).__name__, reason="retention" if trim_before is not None else "explicit")
            result.threads_failed[tid] = type(exc).__name__
            continue
        history.thread_gone(tid)
        result.threads_deleted.append(tid)
        for rule, mapped_tid in mapped.items():
            if mapped_tid == tid:
                rule_map.forget(rule)


async def delete_history_and_threads(app) -> DeleteResult:
    """Delete every automation thread, then the whole run history. Raises
    ThreadsBusy, having deleted nothing, when one of the threads is running.

    Which threads: the LEDGER (store.automation_threads), which records each
    thread the engine created and each thread an automation run named. A
    rule-map entry naming a thread the ledger does not know (a tampered or
    foreign map) is NOT deleted: it is reported in threads_failed and the rule
    forgets it, so the engine never writes into it again."""
    history = app.state.run_history

    def work(rule_map, run) -> DeleteResult:
        for tid in history.thread_ids(kind=AUTOMATION):  # runs from before the ledger
            history.note_thread(tid, None)
        ledger = set(history.ledger_threads())
        busy = run(_busy(app, ledger))
        if busy:
            raise ThreadsBusy(busy)
        result = DeleteResult(runs=0)
        for rule in rule_map.known_rules():
            tid = rule_map.thread_of(rule)
            if tid and tid not in ledger:
                result.threads_failed[tid] = "not a thread the engine created; not deleted"
                rule_map.forget(rule)
        # Durable intent first: an interrupted delete is finished by the sweep.
        history.mark_threads_pending(ledger)
        _delete_ledgered(app, history, rule_map, run, ledger, result)
        result.runs = history.delete_all()
        return result

    return await _locked(app, work)


async def purge_locked(app) -> int | None:
    """The retention purge under the cross-process firing lock, so it never
    runs while a firing (and its record) is in flight on any worker. Skipped,
    not waited for, while one is (returns None; the next purge retries). The
    store's own key grace period (store.KEY_GRACE_SECONDS) also protects a
    record that holds no lock."""
    history = getattr(app.state, "run_history", None)
    if history is None:
        return None
    return await _locked(app, lambda rule_map, run: history.purge(), refuse=False)


async def sweep_threads(app) -> DeleteResult | None:
    """Delete the ledger threads that should no longer exist: a delete that
    failed or was interrupted (retried here), and threads no run names any more
    (retention purged their runs) whose rule is gone. Run at startup, after
    every retention purge, and never while a firing runs (skipped, not
    waited for: the next purge retries). Returns None when skipped."""
    history = getattr(app.state, "run_history", None)
    if history is None:
        return None

    def work(rule_map, run) -> DeleteResult:
        # RETENTION COVERS LIVE RULES' THREADS TOO. A live rule's thread whose
        # oldest content is past the retention is ROTATED: the rule forgets it
        # (its next firing starts a fresh thread) and the old thread is deleted
        # with the others below. What the automation loses: its memory of
        # firings before the rotation (at most once per retention window).
        stale = history.threads_past_retention()
        for rule in rule_map.known_rules():
            if rule_map.thread_of(rule) in stale:
                rule_map.forget(rule)
        mapped = {t for t in (rule_map.thread_of(r) for r in rule_map.known_rules()) if t}
        todo = sorted(set(history.threads_to_sweep(mapped)) | (stale - mapped))
        result = DeleteResult(runs=0)
        busy = set(run(_busy(app, set(todo))))
        # Only an EXPLICIT delete that failed is finished whole. Everything
        # else (a retention delete or trim that failed, an expired thread) goes
        # through the trim path, which re-checks for a person's messages and
        # deletes the whole thread only when there are none.
        pending = history.explicit_deletes()
        ready = [t for t in todo if t not in busy]
        cutoff = history.retention_cutoff()
        _delete_ledgered(app, history, rule_map, run, [t for t in ready if t in pending], result)
        _delete_ledgered(app, history, rule_map, run, [t for t in ready if t not in pending], result, trim_before=cutoff)
        if result.threads_deleted or result.threads_failed:
            logger.info("run history: swept %d automation thread(s), %d failed", len(result.threads_deleted), len(result.threads_failed))
        return result

    try:
        return await _locked(app, work, refuse=False)
    except Exception:
        logger.exception("run history: the thread sweep failed; it is retried after the next purge")
        return None
