"""The gateway's client for Feature 001's session watcher.

The watcher's only integration point is its MCP server over SSE (FR-018), at the
URL the `session-watcher` entry in extensions_config names — the same entry
that gives the agent its watcher tools. This reads that entry and calls the same
tools, so the trigger engine sees what the agent sees.

It replaces `_fetch_watcher_sessions`, which returned `{"observable": False}`
unconditionally: every watcher rule raised SourceUnavailable and none ever
fired (audit T-1). The Feature 004 sessions surface is meant to reuse it.

The four ways the watcher can be absent are kept apart, because an operator
fixes each differently: never configured, configured but disabled, configured
but unreachable — and reachable, in which case the watcher's own `observable`
flag says whether its data is live or stale.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

#: The extensions_config key, shared with the agent's tool registration.
SERVER_NAME = "session-watcher"


class WatcherUnavailable(RuntimeError):
    """The watcher could not be asked. Subclasses say why."""


class WatcherNotConfigured(WatcherUnavailable):
    pass


class WatcherDisabled(WatcherUnavailable):
    pass


class WatcherUnreachable(WatcherUnavailable):
    pass


class WatcherTimedOut(WatcherUnreachable):
    """It is there (the connection was made or pending) and did not answer in
    time: busy, not down. A refused connection is plain WatcherUnreachable."""


def _root_cause(exc: BaseException) -> BaseException:
    """The error worth reporting. The MCP client runs in a task group, so a
    refused connection arrives as 'ExceptionGroup: unhandled errors in a
    TaskGroup (1 sub-exception)' — true, and useless to an operator."""
    while isinstance(exc, BaseExceptionGroup) and len(exc.exceptions) == 1:
        exc = exc.exceptions[0]
    return exc


#: One call tries at most this many fresh connections (bounded retry).
MAX_ATTEMPTS = 2
#: The pause before the second attempt: a restarting watcher binds its port
#: a moment after it was refused.
RETRY_PAUSE_S = 0.25

#: Whether the last call reached the watcher, per URL: failures are logged when
#: the watcher stops answering and when it answers again, not on every poll.
#: The gateway logged none, so a watcher that stayed unreachable left no trace.
_reachable: dict[str, bool] = {}


def _note_failure(url: str, exc: Exception) -> None:
    if _reachable.get(url, True):
        logger.warning("Session watcher at %s could not be asked: %s", url, exc)
    _reachable[url] = False


def _note_success(url: str) -> None:
    if _reachable.get(url) is False:
        logger.info("Session watcher at %s answers again", url)
    _reachable[url] = True


@dataclass
class WatcherClient:
    #: Bounds one whole call — connect, initialise, call. The engine polls on
    #: a minute-scale pulse; a watcher slower than this is reported unreachable.
    timeout: float = 10.0

    def _url(self) -> str:
        from omniharness.config.extensions_config import get_extensions_config

        entry = get_extensions_config().mcp_servers.get(SERVER_NAME)
        if entry is None:
            raise WatcherNotConfigured(f"no {SERVER_NAME!r} server in extensions_config; the watcher has never been configured")
        if not entry.enabled:
            raise WatcherDisabled(f"the {SERVER_NAME!r} server is disabled in extensions_config")
        if entry.type != "sse" or not entry.url:
            raise WatcherNotConfigured(f"the {SERVER_NAME!r} server must be type 'sse' with a url (found type {entry.type!r}, url {entry.url!r})")
        return entry.url

    def _headers(self) -> dict[str, str]:
        """The configured headers of the watcher entry (the token is added on top)."""
        from omniharness.config.extensions_config import get_extensions_config

        entry = get_extensions_config().mcp_servers.get(SERVER_NAME)
        return dict(getattr(entry, "headers", None) or {})

    async def call(self, tool: str, arguments: dict | None = None) -> dict:
        """Call one watcher tool and return its structured payload.

        Every attempt opens its own connection and MCP session: nothing is
        cached between calls. A connection that was refused or dropped (the
        watcher restarting: its port is not bound while it re-reads the
        transcripts) is tried ONCE more on a fresh connection after a short
        pause, within the same overall `timeout`, so the poll that lands in
        the restart window recovers instead of reporting the watcher gone
        until the next poll. A timeout is not retried: the watcher is there
        and busy, and a second attempt would only add to its load.
        """
        url = self._url()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.timeout
        attempt = 0
        while True:
            attempt += 1
            try:
                result = await self._attempt(url, tool, arguments, deadline - loop.time())
            except WatcherTimedOut as exc:
                _note_failure(url, exc)
                raise
            except WatcherUnreachable as exc:
                remaining = deadline - loop.time()
                if attempt >= MAX_ATTEMPTS or remaining <= RETRY_PAUSE_S:
                    _note_failure(url, exc)
                    raise
                await asyncio.sleep(RETRY_PAUSE_S)
                continue
            _note_success(url)
            return result

    async def _attempt(self, url: str, tool: str, arguments: dict | None, budget: float) -> dict:
        """One call on a connection and MCP session of its own."""
        from mcp import ClientSession
        from mcp.client.sse import sse_client

        budget = max(budget, 0.01)

        async def _call():
            from omniharness.mcp.watcher_token import watcher_headers

            async with sse_client(url, headers=watcher_headers(SERVER_NAME, self._headers()), timeout=budget) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    return await session.call_tool(tool, arguments or {})

        try:
            result = await asyncio.wait_for(_call(), timeout=budget)
        except Exception as exc:  # noqa: BLE001 — every failure here means "could not ask"
            cause = _root_cause(exc)
            import httpx

            kind = WatcherTimedOut if isinstance(cause, (TimeoutError, httpx.TimeoutException)) else WatcherUnreachable
            raise kind(f"{url}: {type(cause).__name__}: {cause}") from exc
        if result.isError or not result.content:
            raise WatcherUnreachable(f"{url}: {tool} returned an error or no content")
        return json.loads(result.content[0].text)

    async def list_sessions(self) -> dict:
        """The watcher's roll-up: `observable`, `observability`, `sessions`."""
        return await self.call("list_coding_sessions")

    def list_sessions_blocking(self) -> dict:
        """`list_sessions` for the trigger engine's worker thread.

        Runs on a short-lived loop of its own, so the watcher call never touches
        the gateway's event loop (FR-031). Must not be called from a thread that
        is already running a loop.
        """
        return asyncio.run(self.list_sessions())
