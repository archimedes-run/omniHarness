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
        """Call one watcher tool and return its structured payload."""
        from mcp import ClientSession
        from mcp.client.sse import sse_client

        url = self._url()

        async def _call():
            from omniharness.mcp.watcher_token import watcher_headers

            async with sse_client(url, headers=watcher_headers(SERVER_NAME, self._headers()), timeout=self.timeout) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    return await session.call_tool(tool, arguments or {})

        try:
            result = await asyncio.wait_for(_call(), timeout=self.timeout)
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
