"""A reply cut off by a gateway restart leaves a trace (live chat 2026-11-14).

The bug: a run killed by a restart (uvicorn --reload after a source change,
SIGTERM, a crash) stayed "running" in the run store forever. Its process was
gone, so nothing ever ended it: `RunManager` only knows its own process's
runs, the worker's `finally` never ran, and no sweep looked at runs. The chat
showed the steps and no reply, and no notice.

Now:

* WORKER LEASE. Every gateway worker holds an exclusive `flock` on its own
  lock file for its whole life (released by the OS when the process ends,
  however it ends), and stamps its id on every run it records
  (RunManager.worker_id -> run metadata `worker_id`). A run whose worker's
  lock can be taken is a dead worker's; a run whose lock is held belongs to a
  live worker and is never touched (multi-worker safe). Same host, same data
  dir: the assumption the confirmation and resume locks already make.
* SWEEP at startup and every RECOVERY_INTERVAL_SECONDS in every worker: each
  dead worker's "pending"/"running" run is, under a per-run lock, given the
  notice (below) and then marked `interrupted` with error "restart" by one
  conditional update (the exclusive marker: exactly one sweeper wins).
  Rows written before this change carry no worker id: they are a dead
  worker's when they were last updated before this process started.
* GRACEFUL STOP (shutdown, within the data closes' reserve): this worker's
  in-flight runs are cancelled with reason "restart" (the run worker then
  flushes its journal and records `interrupted` / "restart" itself) and get
  the notice, so it exists before the next start.
* THE NOTICE: one assistant-role message written by the server, never by a
  model: "This reply was interrupted by a restart. Ask again.", with the
  server's own "Ran without asking:" line (FR-063) for Tier 2 actions that
  ran in the cut-off part of the turn and were not yet disclosed, and the
  person's message for the chat's "Try again" button (a NEW turn, sent only
  when the owner clicks it: nothing is retried automatically). It is put at
  the end of that turn in the thread's state and in the run's journal (the
  chat's display history), under one id, so it is shown exactly once, and a
  second sweep or restart adds nothing. A channel chat gets one line.
* CARDS of an interrupted run are kept: a Tier 3 action never runs without
  the owner's click, and answering a card resumes the turn at most once
  under the existing resume rules; the expiry sweep never resumes it (the
  thread's latest run was interrupted: app.gateway.resume._why_not).
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import json
import logging
import os
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REASON = "restart"
NOTICE_TEXT = "This reply was interrupted by a restart. Ask again."
CHANNEL_LINE = NOTICE_TEXT
#: On the notice message (display data; the chat renders it as a system notice).
NOTICE_MARKER = "omniharness_run_notice"
#: Journal event recording that the run's notice was written (idempotence).
NOTICE_EVENT = "run.interrupted_notice"
RECOVERY_INTERVAL_SECONDS = 60.0


def notice_id(run_id: str) -> str:
    return f"run-interrupted-{run_id}"


# -- the worker lease ----------------------------------------------------------


class WorkerLease:
    """This process's liveness, as an flock the OS releases when it dies."""

    def __init__(self, base_dir: Path) -> None:
        self.dir = Path(base_dir) / "runtime" / "run_workers"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.worker_id = uuid.uuid4().hex
        self.started = datetime.now(UTC)
        self._handle = open(self._path(self.worker_id), "a+")  # noqa: SIM115 - held for the process's life
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _path(self, worker_id: str) -> Path:
        return self.dir / f"{worker_id}.lock"

    def alive(self, worker_id: str) -> bool:
        """Whether the worker that stamped this id still runs."""
        if worker_id == self.worker_id:
            return True
        path = self._path(worker_id)
        if not path.exists():
            return False
        try:
            with open(path, "a+") as handle:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return True
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                return False
        except OSError:
            return True  # can't tell: never treat a run as orphaned on doubt

    def prune(self, older_than_seconds: float = 86400.0) -> None:
        """Remove dead workers' lock files older than a day."""
        cutoff = time.time() - older_than_seconds
        for path in self.dir.glob("*.lock"):
            if path.stem == self.worker_id:
                continue
            try:
                if path.stat().st_mtime < cutoff and not self.alive(path.stem):
                    path.unlink(missing_ok=True)
            except OSError:
                continue

    def release(self) -> None:
        with contextlib.suppress(Exception):
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            self._handle.close()
        with contextlib.suppress(OSError):
            self._path(self.worker_id).unlink()


@contextlib.asynccontextmanager
async def _run_lock(base_dir: Path, run_id: str):
    """One sweeper per run at a time, across workers (an flock) and within
    this one (taken without blocking the event loop: a blocking flock here
    would stall every other coroutine of the worker, a second sweep's too)."""
    path = Path(base_dir) / "runtime" / "run_recovery"
    path.mkdir(parents=True, exist_ok=True)
    with open(path / f"{run_id}.lock", "a+") as handle:
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                await asyncio.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


# -- which runs are orphaned --------------------------------------------------


def _when(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else None
    except ValueError:
        return None
    if parsed is not None and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def is_orphaned(row: dict, *, lease: WorkerLease, run_manager: Any) -> bool:
    """A "pending"/"running" run no live worker owns."""
    if row.get("status") not in ("pending", "running"):
        return False
    if run_manager.owns(str(row.get("run_id"))):
        return False  # this process's own run, live
    from omniharness.runtime.runs.manager import WORKER_ID_KEY

    worker = str((row.get("metadata") or {}).get(WORKER_ID_KEY) or "")
    if worker:
        return not lease.alive(worker)
    # Recorded before workers stamped their id: a previous process's, if it
    # was last written before this one started.
    updated = _when(row.get("updated_at") or row.get("created_at"))
    return updated is not None and updated < lease.started


# -- the notice ---------------------------------------------------------------


def _human_text(message: Any) -> str:
    content = message.get("content") if isinstance(message, dict) else getattr(message, "content", "")
    if isinstance(content, list):
        return " ".join(str(b.get("text", "")) for b in content if isinstance(b, dict)).strip()
    return str(content or "").strip()


async def _turn_start(event_store: Any, row: dict) -> tuple[str | None, str | None]:
    """(the person's message id, its text) for the interrupted run."""
    message_id = text = None
    if event_store is not None:
        try:
            events = await event_store.list_events(row["thread_id"], row["run_id"], event_types=["llm.human.input"], limit=5)
        except Exception:  # noqa: BLE001
            events = []
        for event in events or []:
            content = event.get("content")
            if isinstance(content, dict):
                message_id = content.get("id")
                text = _human_text(content)
                break
    if text is None:
        # The run's own input (the run row keeps it): a run that died before
        # its first model call has no journal yet.
        messages = (((row.get("kwargs") or {}).get("input") or {}).get("messages")) or []
        for message in reversed(messages if isinstance(messages, list) else []):
            kind = message.get("type") or message.get("role") if isinstance(message, dict) else getattr(message, "type", None)
            if kind in ("human", "user"):
                text = _human_text(message)
                message_id = message_id or (message.get("id") if isinstance(message, dict) else getattr(message, "id", None))
                break
    return message_id, (text or None)


def _undisclosed_records(turn: list[Any]) -> tuple[list[Any], list[str]]:
    """The Tier 2 actions that ran in the cut-off part of the turn and were
    not disclosed on an earlier final reply of it (FR-063: exactly once, on
    the final reply of the turn or run that caused it). Built from the
    server's step stamps on the tool results, never from model text."""
    from langchain_core.messages import AIMessage, ToolMessage

    from app.policy.disclose import ExecutionRecord
    from omniharness.agents.turns import DELEGATED_DISCLOSURE_MARKER, DISCLOSURE_MARKER, POLICY_STEP_MARKER

    start = 0
    for index, message in enumerate(turn):
        if isinstance(message, AIMessage) and isinstance((message.additional_kwargs or {}).get(DISCLOSURE_MARKER), dict):
            start = index + 1
    names: dict[str, str] = {}
    for message in turn:
        for call in getattr(message, "tool_calls", None) or []:
            names[str(call.get("id"))] = str(call.get("name") or "")
    records: list[Any] = []
    sources: list[str] = []
    for message in turn[start:]:
        if not isinstance(message, ToolMessage):
            continue
        kwargs = message.additional_kwargs or {}
        text = str(message.content or "").lstrip()
        stamp = kwargs.get(POLICY_STEP_MARKER)
        if isinstance(stamp, dict) and stamp.get("tier") == 2 and stamp.get("outcome") == "ran" and message.status != "error" and not text.startswith(("Error", "Not run:", "Waiting for you:")):
            name = message.name or names.get(str(message.tool_call_id), "") or "a tool"
            records.append(ExecutionRecord(tool_name=name, arguments={}, result=None, targets=tuple(str(t) for t in stamp.get("targets") or [])))
        delegated = kwargs.get(DELEGATED_DISCLOSURE_MARKER)
        if isinstance(delegated, dict):
            agent = str(delegated.get("agent") or "a specialist")
            for item in delegated.get("items") or []:
                if isinstance(item, dict) and item.get("tool"):
                    records.append(ExecutionRecord(tool_name=str(item["tool"]), arguments={}, result=None, targets=tuple(str(t) for t in item.get("targets") or []), grant=bool(item.get("grant")), agent=agent))
            sources.append(str(message.tool_call_id))
    return records, sources


def build_notice(run_id: str, turn: list[Any], retry_text: str | None) -> Any:
    from langchain_core.messages import AIMessage

    from app.policy.disclose import notice_line
    from omniharness.agents.turns import DISCLOSURE_MARKER

    records, sources = _undisclosed_records(turn)
    content = NOTICE_TEXT
    kwargs: dict[str, Any] = {NOTICE_MARKER: {"kind": "interrupted", "reason": REASON, "run_id": run_id, "retry_text": retry_text}}
    if records:
        line = notice_line(records)
        content = f"{NOTICE_TEXT}\n\n{line}"
        kwargs[DISCLOSURE_MARKER] = {
            "text": content[len(NOTICE_TEXT) :],
            "items": [{"tool": r.tool_name, "text": r.sentence() + (f" (via {r.agent})" if r.agent else ""), "agent": r.agent, "grant": r.grant} for r in records],
            "sources": sources,
        }
    return AIMessage(id=notice_id(run_id), content=content, additional_kwargs=kwargs, response_metadata={"model_name": "server"})


def _turn_bounds(messages: list[Any], human_id: str | None) -> tuple[int, int]:
    """[start, end) of the interrupted run's turn in the thread's messages."""
    from omniharness.agents.working_loop import is_turn_start

    start = None
    if human_id:
        start = next((i for i, m in enumerate(messages) if getattr(m, "id", None) == human_id), None)
    if start is None:
        starts = [i for i, m in enumerate(messages) if is_turn_start(m)]
        start = starts[-1] if starts else 0
    end = next((j for j in range(start + 1, len(messages)) if is_turn_start(messages[j])), len(messages))
    return start, end


async def write_notice(app_state: Any, row: dict) -> bool:
    """Put the notice at the end of the run's turn, in the thread's state and
    in the run's journal, once. True when it is there (now or already)."""
    from omniharness.utils.time import now_iso

    thread_id, run_id = str(row["thread_id"]), str(row["run_id"])
    checkpointer = getattr(app_state, "checkpointer", None)
    event_store = getattr(app_state, "run_event_store", None)
    human_id, retry_text = await _turn_start(event_store, row)
    notice = None
    if checkpointer is not None:
        config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
        current = await checkpointer.aget_tuple(config)
        if current is not None:
            checkpoint = dict(getattr(current, "checkpoint", {}) or {})
            values = dict(checkpoint.get("channel_values") or {})
            messages = list(values.get("messages") or [])
            existing = next((m for m in messages if getattr(m, "id", None) == notice_id(run_id)), None)
            if existing is not None:
                notice = existing
            else:
                start, end = _turn_bounds(messages, human_id)
                notice = build_notice(run_id, messages[start:end], retry_text)
                values["messages"] = [*messages[:end], notice, *messages[end:]]
                checkpoint["channel_values"] = values
                metadata = dict(getattr(current, "metadata", {}) or {})
                metadata.update({"updated_at": now_iso(), "source": "update", "step": metadata.get("step", 0) + 1})
                await checkpointer.aput(config, checkpoint, metadata, {})
    if notice is None:
        notice = build_notice(run_id, [], retry_text)
    if event_store is not None:
        done = await event_store.list_events(thread_id, run_id, event_types=[NOTICE_EVENT], limit=1)
        if not done:
            await event_store.put(thread_id=thread_id, run_id=run_id, event_type="llm.ai.response", category="message", content=notice.model_dump(), metadata={"caller": "server:run_recovery"})
            await event_store.put(thread_id=thread_id, run_id=run_id, event_type=NOTICE_EVENT, category="trace", content={"reason": REASON}, metadata={"status": "interrupted", "reason": REASON})
    return True


# -- channels: one line ---------------------------------------------------------


def _outbox(base_dir: Path) -> Path:
    path = Path(base_dir) / "runtime" / "run_recovery"
    path.mkdir(parents=True, exist_ok=True)
    return path / "channel_outbox.json"


@contextlib.contextmanager
def _locked_outbox(base_dir: Path):
    path = _outbox(base_dir)
    with open(str(path) + ".lock", "a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            items = json.loads(path.read_text()) if path.exists() else []
        except ValueError:
            items = []
        box = {"items": items}
        try:
            yield box
        finally:
            tmp = str(path) + ".tmp"
            Path(tmp).write_text(json.dumps(box["items"]))
            os.replace(tmp, path)
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def queue_channel_line(base_dir: Path, thread_id: str, run_id: str) -> None:
    """The thread's IM chats get one line, sent by the worker that runs the
    channel service (this one, or another at its next sweep)."""
    with _locked_outbox(base_dir) as box:
        if not any(i.get("run_id") == run_id for i in box["items"]):
            box["items"].append({"thread_id": thread_id, "run_id": run_id})


async def drain_channel_lines(base_dir: Path) -> int:
    from app.channels.service import get_channel_service

    service = get_channel_service()
    if service is None:
        return 0
    from app.channels.message_bus import OutboundMessage

    sent = 0
    with _locked_outbox(base_dir) as box:
        pending, box["items"] = box["items"], []
        entries = service.store.list_entries() if getattr(service, "store", None) is not None else []
        for item in pending:
            for entry in entries:
                if entry.get("thread_id") != item.get("thread_id"):
                    continue
                try:
                    await service.bus.publish_outbound(OutboundMessage(channel_name=entry["channel_name"], chat_id=entry["chat_id"], thread_id=item["thread_id"], text=CHANNEL_LINE, thread_ts=entry.get("topic_id")))
                    sent += 1
                except Exception:  # noqa: BLE001 - one chat's failure never blocks the others
                    logger.warning("run recovery: could not send the restart line to %s", entry.get("channel_name"), exc_info=True)
    return sent


# -- the sweep and the graceful stop ---------------------------------------------


async def _read_run(store: Any, run_id: str) -> dict | None:
    """The run's row whoever owns it (a sweep has no request user)."""
    try:
        return await store.get(run_id, user_id=None)
    except TypeError:  # the in-memory store takes no user
        return await store.get(run_id)


async def recover_orphaned_runs(app_state: Any, *, lease: WorkerLease, base_dir: Path) -> list[str]:
    """Every dead worker's in-flight run: notice, then `interrupted`."""
    run_manager = app_state.run_manager
    store = getattr(app_state, "run_store", None)
    if store is None:
        return []
    done: list[str] = []
    for row in await store.list_active():
        if not is_orphaned(row, lease=lease, run_manager=run_manager):
            continue
        run_id, thread_id = str(row["run_id"]), str(row["thread_id"])
        if await run_manager.thread_busy(thread_id):
            continue  # a new run of this thread runs here: next pass
        async with _run_lock(base_dir, run_id):
            fresh = await _read_run(store, run_id)
            if not fresh or fresh.get("status") not in ("pending", "running"):
                continue
            try:
                await write_notice(app_state, {**row, **fresh})
            except Exception:  # noqa: BLE001 - left active: the next pass tries again
                logger.warning("run recovery: could not write the notice for run %s", run_id, exc_info=True)
                continue
            if await store.mark_interrupted_if_active(run_id, error=REASON):
                done.append(run_id)
                queue_channel_line(base_dir, thread_id, run_id)
                thread_store = getattr(app_state, "thread_store", None)
                if thread_store is not None:
                    with contextlib.suppress(Exception):
                        await thread_store.update_status(thread_id, "interrupted", user_id=None)
                logger.info("run recovery: run %s on thread %s was interrupted by a restart; notice written", run_id, thread_id)
    return done


async def interrupt_live_runs(app_state: Any, *, base_dir: Path, wait_seconds: float = 3.0) -> list[str]:
    """Graceful stop: this worker's in-flight runs end as interrupted by a
    restart, with their journal flushed (the run worker's own end) and the
    notice written now, before the process exits."""
    run_manager = app_state.run_manager
    records = run_manager.live_records()
    for record in records:
        record.interrupt_reason = REASON
        record.abort_action = "interrupt"
        record.abort_event.set()
        if record.task is not None and not record.task.done():
            record.task.cancel()
    tasks = [r.task for r in records if r.task is not None and not r.task.done()]
    if tasks:
        await asyncio.wait(tasks, timeout=wait_seconds)
    done: list[str] = []
    store = getattr(app_state, "run_store", None)
    for record in records:
        row = {"run_id": record.run_id, "thread_id": record.thread_id, "kwargs": record.kwargs, "status": record.status.value}
        try:
            await write_notice(app_state, row)
        except Exception:  # noqa: BLE001 - the next start's sweep writes it
            logger.warning("run recovery: could not write the notice for run %s at shutdown", record.run_id, exc_info=True)
            continue
        if store is not None:
            # A task that did not finish in time: recorded here instead.
            await store.mark_interrupted_if_active(record.run_id, error=REASON)
        queue_channel_line(base_dir, record.thread_id, record.run_id)
        done.append(record.run_id)
    return done


async def recover_forever(app_state: Any, *, lease: WorkerLease, base_dir: Path, interval: float = RECOVERY_INTERVAL_SECONDS) -> None:
    """At startup and then every `interval` seconds, in every worker."""
    while True:
        try:
            await recover_orphaned_runs(app_state, lease=lease, base_dir=base_dir)
            await drain_channel_lines(base_dir)
            lease.prune()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a failed pass is retried at the next
            logger.warning("run recovery: sweep failed", exc_info=True)
        await asyncio.sleep(interval)
