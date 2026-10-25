"""An async HTTP client whose connections never cross event loops.

WHY. `langchain_openai` gives every ChatOpenAI without its own client ONE
process-wide `httpx.AsyncClient` (an `lru_cache`, keyed by base URL and
timeout). Its pooled connections belong to the event loop that opened them.
The gateway runs models on more than one loop: the lead on the server's loop,
a subagent on the persistent isolated loop (subagents.executor), a confirmed
call on a fresh loop in a confirmation-pool thread. A subagent's first model
call then reused a connection the lead had opened on the server's loop. At
best that failed ("... is bound to a different event loop") and was retried,
sending the request twice and dropping the first answer; at worst the read or
write waited on an event that the OTHER loop sets, with no wake-up for this
one and no timeout (ChatOpenAI's default is none), so the subagent made no
model call at all and timed out after `subagents.timeout_seconds` (eval E-1:
a confirmed `task` that hung for 900 s).

This client keeps one connection pool PER EVENT LOOP, so every loop only ever
uses connections it opened. A pool is dropped with its loop (weakly keyed).
"""

from __future__ import annotations

import asyncio
import threading
import urllib.request
from collections.abc import Callable, Sequence
from typing import Any

import httpx

#: langchain_openai's own limits for its default client (and openai's).
DEFAULT_LIMITS = httpx.Limits(max_connections=1000, max_keepalive_connections=100, keepalive_expiry=5.0)


class LoopLocalAsyncTransport(httpx.AsyncBaseTransport):
    """Delegates each request to a transport owned by the running loop.

    NOTHING OUTLIVES ITS LOOP. A pool's keep-alive connections hold their
    loop, so a weak key never let go: every `asyncio.run` that made a request
    (an invited agent's run, a confirmed async tool) left a pool and its
    sockets behind (review of PR #153). A pool whose loop has closed is
    dropped the next time any loop asks, its sockets closed; and a short-lived
    loop closes its own pool before it ends (`release_current_loop`).
    """

    def __init__(self, factory: Callable[[], httpx.AsyncBaseTransport] | None = None) -> None:
        self._factory = factory or httpx.AsyncHTTPTransport
        self._lock = threading.Lock()
        self._by_loop: dict[asyncio.AbstractEventLoop, httpx.AsyncBaseTransport] = {}

    def _drop_closed(self) -> None:
        with self._lock:
            gone = [loop for loop in self._by_loop if loop.is_closed()]
            dropped = [self._by_loop.pop(loop) for loop in gone]
        for transport in dropped:
            _close_sockets(transport)

    def for_current_loop(self) -> httpx.AsyncBaseTransport:
        loop = asyncio.get_running_loop()
        self._drop_closed()
        with self._lock:
            transport = self._by_loop.get(loop)
            if transport is None:
                transport = self._factory()
                self._by_loop[loop] = transport
            return transport

    def pools(self) -> int:
        """How many live loops hold a pool now (for tests and diagnostics)."""
        self._drop_closed()
        with self._lock:
            return len(self._by_loop)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self.for_current_loop().handle_async_request(request)

    async def aclose(self) -> None:
        """Close the running loop's pool (only it can be closed from here)."""
        loop = asyncio.get_running_loop()
        with self._lock:
            transport = self._by_loop.pop(loop, None)
        if transport is not None:
            await transport.aclose()


def _close_sockets(transport: Any) -> None:
    """Close the sockets of a pool whose loop is gone: it cannot be awaited
    any more, so its connections' sockets are closed directly."""
    pool = getattr(transport, "_pool", None)
    for connection in list(getattr(pool, "connections", None) or []):
        stream = getattr(getattr(connection, "_connection", None), "_network_stream", None)
        sock = None
        try:
            sock = stream.get_extra_info("socket") if stream is not None else None
        except Exception:  # noqa: BLE001 - best effort on a dead loop
            sock = None
        # asyncio wraps the socket (TransportSocket); the real one is inside.
        raw = getattr(sock, "_sock", sock)
        if raw is not None and callable(getattr(raw, "close", None)):
            try:
                raw.close()
            except Exception:  # noqa: BLE001 - best effort on a dead loop
                pass


_clients: dict[tuple, httpx.AsyncClient] = {}
_clients_lock = threading.Lock()


def _proxy_from_environment() -> bool:
    """Whether httpx would route through a proxy from the environment.

    httpx builds its own (shared) transports for environment proxies, which
    this client cannot make loop-local without re-implementing NO_PROXY; so
    with one configured the library's default client is left in place.
    """
    proxies = urllib.request.getproxies()
    return any(proxies.get(scheme) for scheme in ("http", "https", "all"))


def resolve_socket_options(configured: Sequence[tuple[int, int, int]] | None) -> tuple[tuple[int, int, int], ...]:
    """The TCP options langchain_openai gives its own default client: the
    model's `http_socket_options` when set (an empty list turns them off),
    else the library's defaults (keep-alive probes, and on Linux
    TCP_USER_TIMEOUT), so a silent peer is noticed rather than waited on
    forever."""
    if configured is not None:
        return tuple(tuple(option) for option in configured)  # type: ignore[misc]
    try:
        from langchain_openai.chat_models._client_utils import _default_socket_options
    except ImportError:  # pragma: no cover - another langchain_openai layout
        return ()
    return tuple(_default_socket_options())


def loop_local_async_client(socket_options: Sequence[tuple[int, int, int]] | None = None) -> Any:
    """The process's loop-local async client for these socket options, or
    None when it must not be used (an environment proxy)."""
    if _proxy_from_environment():
        return None
    options = resolve_socket_options(socket_options)
    with _clients_lock:
        client = _clients.get(options)
        if client is None:

            def transport() -> httpx.AsyncBaseTransport:
                return httpx.AsyncHTTPTransport(socket_options=list(options), limits=DEFAULT_LIMITS)

            client = httpx.AsyncClient(transport=LoopLocalAsyncTransport(transport), trust_env=False, follow_redirects=True, limits=DEFAULT_LIMITS)
            _clients[options] = client
        return client


async def release_current_loop() -> None:
    """Close the running loop's pools: called at the end of a short-lived loop
    (an `asyncio.run`), so its connections end with it."""
    with _clients_lock:
        clients = list(_clients.values())
    for client in clients:
        transport = getattr(client, "_transport", None)
        if isinstance(transport, LoopLocalAsyncTransport):
            await transport.aclose()


async def run_and_release(coro: Any) -> Any:
    """Await `coro`, then release this loop's pools whatever happened."""
    try:
        return await coro
    finally:
        await release_current_loop()


def wants_loop_local_client(model_class: Any, settings: dict, kwargs: dict) -> bool:
    """A model class that takes an `http_async_client` (ChatOpenAI and its
    OpenAI-compatible subclasses), configured with no client or proxy of its
    own, gets the loop-local one."""
    fields = getattr(model_class, "model_fields", None)
    if not isinstance(fields, dict) or "http_async_client" not in fields:
        return False
    own = ("http_async_client", "http_client", "openai_proxy")
    return not any(settings.get(key) or kwargs.get(key) for key in own)
