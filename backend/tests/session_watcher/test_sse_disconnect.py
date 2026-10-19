"""A client disconnecting from the watcher's SSE endpoint is not an error.

`handle_sse` returned None, which Starlette tried to call as a response: one
"Exception in ASGI application" traceback per tool call. Present in the
running stack's logs before the trigger engine started polling.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import threading
import time

import uvicorn
from mcp import ClientSession
from mcp.client.sse import sse_client
from session_watcher.server import WatcherService, build_app


def test_a_completed_tool_call_logs_no_server_error(tmp_path, caplog) -> None:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(build_app(WatcherService(root=tmp_path)), host="127.0.0.1", port=port, log_level="warning", log_config=None))
    # log_config=None: uvicorn's default config sets propagate=False on its own
    # loggers, which hides the very traceback this test looks for from caplog.
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.02)

    async def _call():
        async with sse_client(f"http://127.0.0.1:{port}/sse") as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                return await session.call_tool("list_coding_sessions", {})

    with caplog.at_level(logging.ERROR):
        result = asyncio.run(_call())
        time.sleep(0.3)  # the disconnect is handled after the client returns
    server.should_exit = True

    assert not result.isError  # positive control: the call itself worked
    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert not errors, errors
