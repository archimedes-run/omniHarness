"""The loop-local model HTTP client (omniharness/models/loop_local_http.py).

- Nothing outlives its loop: an `asyncio.run` that made a request leaves no
  pool and no open socket behind (review of PR #153: a weakly keyed pool was
  never dropped, its keep-alive connections holding the loop).
- It carries the settings langchain_openai gives its own default client: TCP
  keep-alive socket options (or the model's `http_socket_options`), the
  1000/100 connection limits, and redirects followed.

Real requests against a local server; no model provider is called.
"""

from __future__ import annotations

import asyncio
import gc
import http.server
import importlib
import os
import socketserver
import sys
import threading

import httpx
import pytest

from omniharness.models import loop_local_http
from omniharness.models.loop_local_http import DEFAULT_LIMITS, LoopLocalAsyncTransport, loop_local_async_client, resolve_socket_options, run_and_release


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - http.server's name
        if self.path == "/moved":
            self.send_response(302)
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *_args) -> None:
        pass


@pytest.fixture
def server():
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture(autouse=True)
def no_proxy(monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)


def _fds() -> int:
    return len(os.listdir("/dev/fd"))


def _transport(client: httpx.AsyncClient) -> LoopLocalAsyncTransport:
    transport = client._transport
    assert isinstance(transport, LoopLocalAsyncTransport)
    return transport


def _live(transport: LoopLocalAsyncTransport) -> set:
    """The loops holding a pool now (other tests' loops may still be live)."""
    transport.pools()
    return set(transport._by_loop)


def test_many_short_lived_loops_leave_no_pool_and_no_socket(server) -> None:
    client = loop_local_async_client()
    others = _live(_transport(client))
    gc.collect()
    before = _fds()
    used: list = []

    async def call() -> int:
        used.append(asyncio.get_running_loop())
        return (await client.get(f"{server}/")).status_code

    for _ in range(40):
        assert asyncio.run(call()) == 200
    gc.collect()
    assert _live(_transport(client)) - others == set(), "a closed loop's pool was kept"
    assert not set(used) & set(_transport(client)._by_loop)
    assert _fds() - before <= 1, f"sockets left open: {_fds() - before}"


def test_a_released_loop_closes_its_own_pool_before_it_ends(server) -> None:
    client = loop_local_async_client()
    transport = _transport(client)
    _ = transport.pools()  # drop anything a previous test left

    used: list = []

    async def call() -> int:
        used.append(asyncio.get_running_loop())
        return (await client.get(f"{server}/")).status_code

    assert asyncio.run(run_and_release(call())) == 200
    # Not swept on the next call: released by the loop itself.
    assert used and used[0] not in transport._by_loop


def test_a_confirmed_async_call_releases_its_loop(server) -> None:
    from app.policy.surface_run import _await

    transport = _transport(loop_local_async_client())
    _ = transport.pools()

    used: list = []

    async def call() -> int:
        used.append(asyncio.get_running_loop())
        return (await loop_local_async_client().get(f"{server}/")).status_code

    assert _await(call()) == 200
    assert used and used[0] not in transport._by_loop


def test_an_invited_agents_run_releases_its_loop(server, monkeypatch) -> None:
    """SubagentExecutor.execute with no running loop (an @-called agent):
    the asyncio.run it makes ends with its pool closed."""
    monkeypatch.delitem(sys.modules, "omniharness.subagents.executor")
    executor_module = importlib.import_module("omniharness.subagents.executor")
    transport = _transport(loop_local_async_client())
    _ = transport.pools()
    seen: dict[str, int] = {}

    async def fake_aexecute(self, task, result_holder=None):
        seen["loop"] = asyncio.get_running_loop()
        seen["status"] = (await loop_local_async_client().get(f"{server}/")).status_code
        return "done"

    monkeypatch.setattr(executor_module.SubagentExecutor, "_aexecute", fake_aexecute)
    executor = object.__new__(executor_module.SubagentExecutor)
    assert executor.execute("task") == "done"
    assert seen["status"] == 200
    assert seen["loop"] not in transport._by_loop


def test_the_transport_carries_langchain_openais_socket_options_and_limits() -> None:
    from langchain_openai.chat_models._client_utils import _default_socket_options

    client = loop_local_async_client()
    assert client.follow_redirects is True

    async def pool():
        return _transport(client).for_current_loop()._pool

    inner = asyncio.run(pool())
    assert inner._socket_options == list(_default_socket_options())
    assert inner._socket_options, "no keep-alive options: a silent peer would hang forever"
    assert (inner._max_connections, inner._max_keepalive_connections, inner._keepalive_expiry) == (1000, 100, 5.0)
    assert DEFAULT_LIMITS.max_connections == 1000


def test_a_models_own_socket_options_are_used() -> None:
    import socket

    custom = [(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)]
    assert resolve_socket_options(custom) == ((socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),)
    assert resolve_socket_options([]) == ()
    client = loop_local_async_client(custom)
    assert client is not loop_local_async_client()

    async def pool():
        return _transport(client).for_current_loop()._pool

    assert asyncio.run(pool())._socket_options == custom


def test_redirects_are_followed(server) -> None:
    async def call() -> int:
        return (await loop_local_async_client().get(f"{server}/moved")).status_code

    assert asyncio.run(run_and_release(call())) == 200


def test_chatopenai_from_the_factory_gets_the_client_for_its_socket_options() -> None:
    import socket

    from langchain_openai import ChatOpenAI

    from omniharness.models.factory import create_chat_model

    model = create_chat_model(name=None)
    assert isinstance(model, ChatOpenAI)
    assert model.http_async_client is loop_local_async_client()
    custom = [(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)]
    tuned = create_chat_model(name=None, http_socket_options=custom)
    assert tuned.http_async_client is loop_local_async_client(custom)
    assert loop_local_http._clients  # one client per option set
