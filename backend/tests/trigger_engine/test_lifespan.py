"""T083 — the engine starts with the gateway and cannot prevent it starting."""

from __future__ import annotations

import asyncio

import pytest

from app.trigger_engine.lifespan import EngineHandle, start, stop

pytestmark = pytest.mark.asyncio


class _Loop:
    def __init__(self, boom: bool = False):
        self.started = self.stopped = False
        self.boom = boom
        self._ev = asyncio.Event()

    async def run_forever(self):
        self.started = True
        if self.boom:
            raise RuntimeError("loop exploded")
        await self._ev.wait()

    def stop(self):
        self.stopped = True
        self._ev.set()


async def test_the_loop_starts_with_the_app() -> None:
    loop = _Loop()
    handle = await start(lambda: loop)
    await asyncio.sleep(0)
    assert handle.running and loop.started
    await stop(handle)
    assert loop.stopped


async def test_it_stops_with_the_app() -> None:
    loop = _Loop()
    handle = await start(lambda: loop)
    await asyncio.sleep(0)
    await stop(handle)
    assert not handle.running


async def test_a_build_failure_does_not_prevent_the_gateway_starting() -> None:
    """The engine is an addition to the assistant, not a precondition for it."""

    def boom():
        raise RuntimeError("bad config path")

    handle = await start(boom)
    assert not handle.running
    assert "bad config path" in handle.error
    await stop(handle)  # must not raise


async def test_a_loop_that_raises_does_not_escape_startup() -> None:
    loop = _Loop(boom=True)
    handle = await start(lambda: loop)
    await asyncio.sleep(0.01)
    assert loop.started
    await stop(handle)  # must not raise


async def test_disabled_is_a_supported_state() -> None:
    handle = await start(lambda: _Loop(), enabled=False)
    assert not handle.running and handle.error is None
    assert handle.describe() == {"running": False, "error": None, "holds_lock": False}


async def test_stopping_a_never_started_handle_is_safe() -> None:
    await stop(EngineHandle())
