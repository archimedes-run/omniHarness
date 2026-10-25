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
import weakref
from collections.abc import Callable
from typing import Any

import httpx


class LoopLocalAsyncTransport(httpx.AsyncBaseTransport):
    """Delegates each request to a transport owned by the running loop."""

    def __init__(self, factory: Callable[[], httpx.AsyncBaseTransport] | None = None) -> None:
        self._factory = factory or httpx.AsyncHTTPTransport
        self._lock = threading.Lock()
        self._by_loop: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, httpx.AsyncBaseTransport] = weakref.WeakKeyDictionary()

    def for_current_loop(self) -> httpx.AsyncBaseTransport:
        loop = asyncio.get_running_loop()
        with self._lock:
            transport = self._by_loop.get(loop)
            if transport is None:
                transport = self._factory()
                self._by_loop[loop] = transport
            return transport

    def pools(self) -> int:
        """How many loops hold a pool now (for tests and diagnostics)."""
        with self._lock:
            return len(self._by_loop)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self.for_current_loop().handle_async_request(request)

    async def aclose(self) -> None:
        # Only this loop's pool can be closed from this loop; the others close
        # on their own loops, or are dropped with them.
        loop = asyncio.get_running_loop()
        with self._lock:
            transport = self._by_loop.pop(loop, None)
        if transport is not None:
            await transport.aclose()


_client: httpx.AsyncClient | None = None
_client_lock = threading.Lock()


def _proxy_from_environment() -> bool:
    """Whether httpx would route through a proxy from the environment.

    httpx builds its own (shared) transports for environment proxies, which
    this client cannot make loop-local without re-implementing NO_PROXY; so
    with one configured the library's default client is left in place.
    """
    proxies = urllib.request.getproxies()
    return any(proxies.get(scheme) for scheme in ("http", "https", "all"))


def loop_local_async_client() -> Any:
    """The process's loop-local async client, or None when it must not be used."""
    global _client
    if _proxy_from_environment():
        return None
    with _client_lock:
        if _client is None:
            _client = httpx.AsyncClient(transport=LoopLocalAsyncTransport(), trust_env=False)
        return _client


def wants_loop_local_client(model_class: Any, settings: dict, kwargs: dict) -> bool:
    """A model class that takes an `http_async_client` (ChatOpenAI and its
    OpenAI-compatible subclasses), configured with no client or proxy of its
    own, gets the loop-local one."""
    fields = getattr(model_class, "model_fields", None)
    if not isinstance(fields, dict) or "http_async_client" not in fields:
        return False
    own = ("http_async_client", "http_client", "openai_proxy")
    return not any(settings.get(key) or kwargs.get(key) for key in own)
