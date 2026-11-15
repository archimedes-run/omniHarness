"""Tool assembly off the event loop (omniharness.utils.off_loop), as if inline.

Assembly sets context variables its caller reads afterwards (the deferred-tool
registry `tool_search` uses): run in a worker thread, those must still be set
in the caller's context, or moving it off the loop would change a run.
"""

from __future__ import annotations

import asyncio
import contextvars
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from omniharness.utils.off_loop import call_off_loop

_VAR: contextvars.ContextVar[str | None] = contextvars.ContextVar("off_loop_test", default=None)


@pytest.mark.anyio
async def test_runs_in_another_thread_and_keeps_what_it_set():
    loop_thread = threading.get_ident()
    seen = {}

    def assemble(value: str) -> str:
        seen["thread"] = threading.get_ident()
        seen["inherited"] = _VAR.get()
        _VAR.set(value)
        return "tools"

    _VAR.set("caller")
    assert await call_off_loop(assemble, "assembled") == "tools"
    assert seen["thread"] != loop_thread
    assert seen["inherited"] == "caller"  # it sees the caller's context
    assert _VAR.get() == "assembled"  # and the caller sees what it set


@pytest.mark.anyio
async def test_what_it_set_before_raising_stays_set():
    def assemble() -> None:
        _VAR.set("before-raise")
        raise LookupError("cap")

    with pytest.raises(LookupError):
        await call_off_loop(assemble)
    assert _VAR.get() == "before-raise"


@pytest.mark.anyio
async def test_a_cancelled_caller_stops_waiting_at_once_and_keeps_nothing():
    """A stop or restart must not wait for a build that is not answering
    (a toolkit up to its time limit): the caller is cancelled at once and the
    thread's result, context changes included, is dropped."""
    import time

    release = threading.Event()

    def assemble() -> None:
        release.wait(5)
        _VAR.set("late")

    _VAR.set("caller")
    task = asyncio.ensure_future(call_off_loop(assemble))
    await asyncio.sleep(0.05)
    started = time.monotonic()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert time.monotonic() - started < 0.5
    release.set()
    await asyncio.sleep(0.05)
    assert _VAR.get() == "caller"


@pytest.mark.anyio
async def test_assembly_runs_in_its_own_pool_not_the_default_one():
    """The default pool also serves journal writes, card statements, password
    hashing and DNS: assembly never takes its threads."""
    names = {}

    def assemble() -> None:
        names["thread"] = threading.current_thread().name

    await call_off_loop(assemble)
    assert names["thread"].startswith("tool-assembly"), names


@pytest.mark.anyio
async def test_deferred_tool_registry_reaches_the_caller():
    from omniharness.tools.builtins.tool_search import DeferredToolRegistry, get_deferred_registry, reset_deferred_registry, set_deferred_registry

    reset_deferred_registry()
    registry = DeferredToolRegistry()
    await call_off_loop(set_deferred_registry, registry)
    assert get_deferred_registry() is registry


@pytest.mark.anyio
async def test_a_run_builds_its_agent_off_the_event_loop():
    """The run worker is a task on the gateway's loop: building the agent
    (which assembles its tools) there held every request the gateway serves."""
    from omniharness.runtime.runs.manager import RunManager
    from omniharness.runtime.runs.worker import RunContext, run_agent

    run_manager = RunManager()
    record = await run_manager.create("thread-1")
    bridge = SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())
    loop_thread = threading.get_ident()
    seen = {}

    class DummyAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            seen["var_in_run"] = _VAR.get()
            yield {"messages": []}

    def factory(*, config):
        seen["factory_thread"] = threading.get_ident()
        _VAR.set("set-by-factory")
        return DummyAgent()

    await run_agent(bridge, run_manager, record, ctx=RunContext(checkpointer=None), agent_factory=factory, graph_input={}, config={})
    await asyncio.sleep(0)

    assert seen["factory_thread"] != loop_thread
    assert seen["var_in_run"] == "set-by-factory"
