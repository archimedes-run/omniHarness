"""Two first requests after a restart must not deadlock the gateway.

Live, 2026-10-23: right after a restart the open tab sent GET /api/tools/catalog
(awaits initialize_mcp_tools on the event loop) and GET /api/threads/{id}/tools
(async route calling the SYNC get_available_tools -> get_cached_mcp_tools) at
once. The sync path blocked the event loop on a thread that waited for the
init lock, held by the coroutine parked on that same loop: no request was
answered again until the gateway was restarted.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from omniharness.mcp import cache


@pytest.fixture
def slow_mcp(monkeypatch):
    """MCP servers that take a moment to answer, and count their loads."""
    loads = []

    async def get_mcp_tools():
        loads.append(threading.get_ident())
        await asyncio.sleep(0.3)
        return ["tool-a", "tool-b"]

    import omniharness.mcp.tools as mcp_tools

    monkeypatch.setattr(mcp_tools, "get_mcp_tools", get_mcp_tools)
    monkeypatch.setattr(cache, "_get_config_mtime", lambda: None)
    cache.reset_mcp_tools_cache()
    yield loads
    cache.reset_mcp_tools_cache()


def _run_with_deadline(coro, seconds: float):
    """Run `coro` on its own loop in a daemon thread; fail (not hang) past the deadline."""
    out: dict = {}

    def target():
        try:
            out["value"] = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001 - reported below
            out["error"] = exc

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(seconds)
    assert not t.is_alive(), "the event loop deadlocked: a sync MCP lookup waited on an init parked on its own loop"
    if "error" in out:
        raise out["error"]
    return out["value"]


def test_a_sync_lookup_on_the_loop_during_an_async_init_does_not_deadlock(slow_mcp) -> None:
    async def two_first_requests():
        catalog = asyncio.create_task(cache.initialize_mcp_tools())  # GET /api/tools/catalog
        await asyncio.sleep(0.05)  # it now holds the init lock, parked in get_mcp_tools
        thread_tools = cache.get_cached_mcp_tools()  # GET /api/threads/{id}/tools, on the loop
        return await catalog, thread_tools

    started = time.monotonic()
    from_catalog, from_thread_tools = _run_with_deadline(two_first_requests(), 10)
    assert from_catalog == from_thread_tools == ["tool-a", "tool-b"]
    assert len(slow_mcp) == 1, "the servers were loaded twice"
    assert time.monotonic() - started < 5


def test_concurrent_async_and_threaded_lookups_load_the_servers_once(slow_mcp) -> None:
    async def many():
        on_loop = [asyncio.create_task(cache.initialize_mcp_tools()) for _ in range(3)]
        in_threads = [asyncio.to_thread(cache.get_cached_mcp_tools) for _ in range(3)]
        return await asyncio.gather(*on_loop, *in_threads)

    results = _run_with_deadline(many(), 10)
    assert all(r == ["tool-a", "tool-b"] for r in results)
    assert len(slow_mcp) == 1
