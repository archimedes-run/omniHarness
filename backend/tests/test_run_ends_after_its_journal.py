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
