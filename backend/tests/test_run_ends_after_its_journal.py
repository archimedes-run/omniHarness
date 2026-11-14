"""A run is reported ended only once its journal is written (issue #180).

The run's journal is the chat's display history: a client that sees a run end
(a poll of its status, a reload) reads the journal at once. The worker marked
the run ``success`` and only then, in its ``finally``, flushed the journal, so
a journal write still in flight (the final answer's) landed after the status
said the run was over. On a slow runner the policy suite saw a finished run
whose journal lacked its final answer.

Deterministic: the journal write of the final answer is held until the
agent's stream has ended, then takes a moment, as a SQLite write on a busy
runner does. The run manager records what the journal holds at the instant
the run's status turns terminal.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from omniharness.runtime.events.store.memory import MemoryRunEventStore
from omniharness.runtime.journal import RunJournal
from omniharness.runtime.runs.manager import RunManager
from omniharness.runtime.runs.schemas import RunStatus
from omniharness.runtime.runs.worker import RunContext, run_agent

FINAL = "Brunch picks: Talula's Garden, Middle Child, Suraya."


class _HeldStore(MemoryRunEventStore):
    """A journal store whose writes wait for the stream to end, then take a moment."""

    def __init__(self) -> None:
        super().__init__()
        self.stream_ended = asyncio.Event()

    async def put_batch(self, events):
        await self.stream_ended.wait()
        await asyncio.sleep(0.05)
        return await super().put_batch(events)


class _WatchingManager(RunManager):
    """Records the journal's messages at the moment a run's status turns terminal."""

    def __init__(self, store: MemoryRunEventStore) -> None:
        super().__init__()
        self._events = store
        self.seen_at_end: dict[RunStatus, list[dict]] = {}

    async def set_status(self, run_id, status, *, error=None):
        if status in (RunStatus.success, RunStatus.error, RunStatus.interrupted):
            record = self.get(run_id)
            rows = await self._events.list_messages_by_run(record.thread_id, run_id, limit=200)
            self.seen_at_end[status] = rows
        await super().set_status(run_id, status, error=error)


def _final_answer(config: dict) -> None:
    """The model's final reply, through the journal as LangChain hands it over."""
    [journal] = [cb for cb in config["callbacks"] if isinstance(cb, RunJournal)]
    journal.on_llm_end(LLMResult(generations=[[ChatGeneration(message=AIMessage(content=FINAL))]]), run_id=uuid.uuid4())


@pytest.mark.anyio
@pytest.mark.parametrize("outcome", [RunStatus.success, RunStatus.error])
async def test_a_run_ends_only_after_its_final_journal_write(outcome):
    store = _HeldStore()
    manager = _WatchingManager(store)
    record = await manager.create("thread-1")
    bridge = SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())

    class Agent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            _final_answer(config)
            yield {"messages": []}
            store.stream_ended.set()
            if outcome is RunStatus.error:
                raise RuntimeError("the model provider went away")

    await run_agent(
        bridge,
        manager,
        record,
        ctx=RunContext(checkpointer=None, event_store=store),
        agent_factory=lambda *, config: Agent(),
        graph_input={},
        config={},
    )

    assert manager.get(record.run_id).status is outcome
    # The precondition: the write is in the journal once the run is over.
    after = await store.list_messages_by_run("thread-1", record.run_id, limit=200)
    assert FINAL in str(after), "the final answer never reached the journal; this test proves nothing"
    # The point: it was there when the status said the run had ended.
    assert FINAL in str(manager.seen_at_end[outcome]), f"the run was reported {outcome.value} before its final answer was in its journal"


# -- a cancel or a hanging store during the end's write (review of #189) -----


class _GatedStore(MemoryRunEventStore):
    """A journal store whose writes wait until the test releases them."""

    def __init__(self) -> None:
        super().__init__()
        self.release = asyncio.Event()

    async def put_batch(self, events):
        await self.release.wait()
        return await super().put_batch(events)


async def _start(store, manager, *, fail: bool = False):
    """A run whose final answer's write is held; returns once the stream has
    ended and the worker is waiting on that write in its end."""
    record = await manager.create("thread-1")
    bridge = SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())
    ended = asyncio.Event()

    class Agent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            _final_answer(config)
            yield {"messages": []}
            ended.set()
            if fail:
                raise RuntimeError("the model provider went away")

    task = asyncio.create_task(
        run_agent(bridge, manager, record, ctx=RunContext(checkpointer=None, event_store=store), agent_factory=lambda *, config: Agent(), graph_input={}, config={}),
    )
    record.task = task
    await ended.wait()
    for _ in range(5):
        await asyncio.sleep(0)
    assert manager.get(record.run_id).status is RunStatus.running, "the run ended before its final write; this test proves nothing"
    return record, task


async def _stop_by_cancel(manager, record):
    assert await manager.cancel(record.run_id), "the cancel was refused; this test proves nothing"


async def _stop_by_new_message(manager, record):
    newer = await manager.create_or_reject("thread-1", multitask_strategy="interrupt")
    assert newer.run_id != record.run_id


@pytest.mark.anyio
@pytest.mark.parametrize("stop", [_stop_by_cancel, _stop_by_new_message], ids=["stop", "interrupting-message"])
async def test_a_stop_during_the_final_write_leaves_a_finished_run_finished(stop):
    store = _GatedStore()
    manager = _WatchingManager(store)
    record, task = await _start(store, manager)

    await stop(manager, record)
    await asyncio.sleep(0)
    store.release.set()
    await asyncio.wait_for(task, timeout=10)

    assert not task.cancelled()
    assert manager.get(record.run_id).status is RunStatus.success, "a finished run was recorded as stopped"
    assert FINAL in str(manager.seen_at_end[RunStatus.success]), "the run was reported success before its final answer was in its journal"
    rows = await store.list_messages_by_run("thread-1", record.run_id, limit=200)
    assert [r for r in rows if FINAL in str(r)], "the final answer was lost from the journal"


@pytest.mark.anyio
async def test_a_stop_during_the_error_paths_write_still_records_the_error():
    store = _GatedStore()
    manager = _WatchingManager(store)
    record, task = await _start(store, manager, fail=True)

    await _stop_by_cancel(manager, record)
    await asyncio.sleep(0)
    store.release.set()
    await asyncio.wait_for(task, timeout=10)

    assert manager.get(record.run_id).status is RunStatus.error, "a failed run was left recorded as stopped (or running)"
    assert FINAL in str(manager.seen_at_end[RunStatus.error])


@pytest.mark.anyio
async def test_a_journal_that_hangs_never_leaves_the_run_unended(monkeypatch):
    import omniharness.runtime.runs.worker as worker

    monkeypatch.setattr(worker, "JOURNAL_FLUSH_TIMEOUT_SECONDS", 0.2)
    store = _GatedStore()
    manager = _WatchingManager(store)
    record, task = await _start(store, manager)
    try:
        for _ in range(60):
            if manager.get(record.run_id).status is not RunStatus.running:
                break
            await asyncio.sleep(0.05)
        assert manager.get(record.run_id).status is RunStatus.success, "the run was left running behind a journal that never answered"
    finally:
        store.release.set()
        await asyncio.wait_for(task, timeout=5)


@pytest.mark.anyio
async def test_a_cancelled_journal_write_is_kept_for_the_next_flush():
    """A write cancelled mid-flight goes back to the buffer, never dropped."""
    store = _GatedStore()
    journal = RunJournal(run_id="run-1", thread_id="thread-1", event_store=store)
    journal.record_middleware("summarize", name="M", hook="before_model", action="summarize", changes={})  # buffered, not yet written

    flushing = asyncio.create_task(journal.flush())
    await asyncio.sleep(0)
    flushing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await flushing

    store.release.set()
    await journal.flush()
    events = await store.list_events("thread-1", "run-1")
    assert [e for e in events if e["event_type"] == "middleware:summarize"], "a cancelled write's events were dropped"
