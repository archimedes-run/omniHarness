"""The session watcher restarting under a running gateway (dogfooding D4-a).

After the session-watcher container restarted, Home kept saying "Can't reach
the session watcher" / "Watcher did not answer". The gateway asks the watcher
on a connection and MCP session of its own for every call (nothing is cached
between calls), so the next poll after the watcher is back must read it; and
a poll that lands while the watcher is still binding its port must not be
lost: one bounded retry on a fresh connection.

Through `create_app()` (Home's `/api/home/today` and `/api/sessions`, the real
`WatcherClient`, MCP over SSE) against the REAL watcher server
(`session_watcher.server.build_app`, its token and host guard) on a local
port, with only its session source stood in for. Stopping it closes the port;
restarting it is a new server on the same port.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
import uvicorn

TOKEN = "watcher-test-token"


class _Service:
    """The watcher's service with a stand-in session source."""

    def __init__(self, delay: float = 0.0) -> None:
        self.calls = 0
        self.delay = delay
        self.registry = SimpleNamespace(sessions={}, observability=lambda now: SimpleNamespace(value="live"))

    def refresh(self, now=None) -> None:
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)

    def list_sessions(self, now=None) -> dict:
        at = datetime.now(UTC).isoformat()
        return {
            "observable": True,
            "observability": "live",
            "as_of": at,
            "staleness_seconds": 0,
            "agents": [],
            "sessions": [{"session_id": "s1", "project": "repo-a", "state": "idle", "idle_reason": "completed", "last_activity_at": at, "quiet_seconds": 1}],
        }

    def agents(self) -> list:
        return []


class _Watcher:
    def __init__(self, port: int) -> None:
        self.port = port
        self.server: uvicorn.Server | None = None
        self.thread: threading.Thread | None = None
        self.service = _Service()

    def start(self, service: _Service | None = None) -> None:
        from session_watcher.server import build_app

        self.service = service or _Service()
        self.server = uvicorn.Server(uvicorn.Config(build_app(self.service, token=TOKEN), host="127.0.0.1", port=self.port, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        deadline = time.time() + 10
        while not self.server.started:
            assert time.time() < deadline, "the watcher did not start"
            time.sleep(0.02)

    def stop(self) -> None:
        if self.server is not None:
            self.server.should_exit = True
            self.server.force_exit = True
            self.thread.join(10)
            self.server = None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def watcher(gateway, monkeypatch, tmp_path):
    """The real watcher on a local port, configured as the gateway's
    `session-watcher` server with its token file."""
    from omniharness.config.extensions_config import reset_extensions_config

    port = _free_port()
    token_file = tmp_path / "watcher.token"
    token_file.write_text(TOKEN + "\n")
    monkeypatch.setenv("OMNI_HARNESS_WATCHER_TOKEN_FILE", str(token_file))
    (gateway.tmp / "extensions.json").write_text(json.dumps({"mcpServers": {"session-watcher": {"enabled": True, "type": "sse", "url": f"http://127.0.0.1:{port}/sse"}}, "skills": {}}))
    reset_extensions_config()
    w = _Watcher(port)
    w.start()
    yield w
    w.stop()
    reset_extensions_config()


def _home(gateway) -> str:
    return gateway.client.get("/api/home/today", params={"since": "2000-01-01T00:00:00+00:00"}).json()["sources"]["sessions"]


def _sessions(gateway) -> dict:
    return gateway.client.get("/api/sessions").json()


def test_after_the_watcher_restarts_the_next_poll_reads_it(gateway, watcher) -> None:
    assert _home(gateway) == "ok"
    assert _sessions(gateway)["reachable"] is True

    watcher.stop()
    assert _home(gateway) == "unavailable"
    down = _sessions(gateway)
    assert down["reachable"] is False and down["sessions"] is None, "a stopped watcher must read as can't-tell, never as no sessions"

    watcher.start()
    assert _home(gateway) == "ok", "Home still could not reach the watcher after it came back"
    back = _sessions(gateway)
    assert back["reachable"] is True and [s["project"] for s in back["sessions"]] == ["repo-a"]


def test_a_poll_during_the_restart_recovers_on_one_fresh_connection(gateway, watcher) -> None:
    """The watcher binds its port a moment after the poll was refused."""
    watcher.stop()
    restarter = threading.Timer(0.1, watcher.start)
    restarter.start()
    try:
        started = time.monotonic()
        view = _sessions(gateway)
        elapsed = time.monotonic() - started
    finally:
        restarter.join()
    assert view["reachable"] is True, f"the poll in the restart window was lost: {view.get('unreachable_detail')}"
    assert elapsed < 2.5, "the retry went past the page's bound"


def test_a_busy_watcher_is_asked_once_not_twice(gateway, watcher) -> None:
    """A timeout is the watcher there and busy: a second attempt would only
    add to its load, so it is not retried."""
    from app.gateway.routers import sessions as sessions_router

    watcher.stop()
    slow = _Service(delay=sessions_router.SESSIONS_TIMEOUT_S + 1.0)
    watcher.start(slow)
    view = _sessions(gateway)
    assert view["reachable"] is False
    time.sleep(1.5)  # let the watcher finish the one refresh it was asked for
    assert slow.calls == 1, f"the busy watcher was asked {slow.calls} times"


def test_the_retry_is_bounded(gateway, watcher, monkeypatch) -> None:
    """A watcher that stays down is reported after two attempts, quickly."""
    from app.gateway import watcher_client

    watcher.stop()
    attempts = []
    real = watcher_client.WatcherClient._attempt

    async def counting(self, *args, **kwargs):
        attempts.append(1)
        return await real(self, *args, **kwargs)

    monkeypatch.setattr(watcher_client.WatcherClient, "_attempt", counting)
    started = time.monotonic()
    assert _sessions(gateway)["reachable"] is False
    assert time.monotonic() - started < 2.5
    assert len(attempts) == watcher_client.MAX_ATTEMPTS == 2
