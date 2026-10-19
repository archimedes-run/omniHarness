"""Article XI: the engine in the production shape.

THE STRUCTURAL DIFFERENCE THIS FILE DEFENDS AGAINST: every other engine test
builds its loop by hand, choosing its own arguments. Production calls
`build_production_loop(config)`, and the October audit found four stub
arguments in that call — a watcher feed hard-coded to "unobservable",
QuietDestination in the remote slot, and no calendar or completion source —
all shipped with a green suite (specs/AUDIT-2026-10.md §1.1).

So nothing here constructs engine objects. It calls the same function the
gateway lifespan calls, and replaces only what sits OUTSIDE the process:

  * the session watcher is the REAL Feature 001 server, run on a free port
    against a session file written by the test, and found through the same
    extensions-config lookup production uses;
  * the IM channel is a stand-in for Telegram's network client, subclassing
    the real `Channel` base so the channel boundary itself is exercised.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.channels.base import Channel
from app.channels.message_bus import MessageBus, OutboundMessage
from app.gateway.trigger_engine_wiring import build_production_loop
from app.trigger_engine.models import Destination, TriggerType

SESSION_ID = "sess-blocked"
CHAT_ID = "4242"


# -- outside-the-process stand-ins ---------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _serve(app, port: int):
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("test server did not start")
        time.sleep(0.02)
    return server, thread


def _write_blocked_session(root: Path) -> None:
    """A session whose turn ENDED on a question two minutes ago: the shape the
    real watcher resolves to waiting-on-user (state.py, `_classify_state`)."""
    now = datetime.now(UTC)
    base = {"sessionId": SESSION_ID, "session_id": SESSION_ID, "cwd": "/Users/dev/projects/darcy-repo", "gitBranch": "main", "isSidechain": False, "version": "2.0.0"}
    records = [
        {**base, "type": "user", "uuid": "u1", "timestamp": (now - timedelta(minutes=3)).isoformat(), "message": {"role": "user", "content": [{"type": "text", "text": "fix the flaky test"}]}},
        {
            **base,
            "type": "assistant",
            "uuid": "u2",
            "timestamp": (now - timedelta(minutes=2)).isoformat(),
            "message": {"role": "assistant", "stop_reason": "end_turn", "content": [{"type": "text", "text": "Should I pin the version or rewrite the fixture?"}]},
        },
    ]
    project = root / "-Users-dev-projects-darcy-repo"
    project.mkdir(parents=True)
    (project / f"{SESSION_ID}.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n")


@pytest.fixture
def live_watcher(tmp_path, monkeypatch):
    """The real watcher server, registered the way production finds it."""
    from session_watcher.server import WatcherService, build_app

    from omniharness.config.extensions_config import reset_extensions_config

    root = tmp_path / "projects"
    _write_blocked_session(root)
    service = WatcherService(root=root)
    service.refresh()
    # Positive control (Article XII): the watcher itself must see the session as
    # waiting before a feed reporting otherwise means anything about the feed.
    seen = {s["session_id"]: s["state"] for s in service.list_sessions()["sessions"]}
    assert seen.get(SESSION_ID) == "waiting-on-user", f"fixture is wrong, not the feed: the watcher sees {seen}"

    port = _free_port()
    server, thread = _serve(build_app(service), port)

    ext = tmp_path / "extensions_config.json"
    ext.write_text(json.dumps({"mcpServers": {"session-watcher": {"enabled": True, "type": "sse", "url": f"http://127.0.0.1:{port}/sse"}}, "skills": {}}))
    monkeypatch.setenv("OMNI_HARNESS_EXTENSIONS_CONFIG_PATH", str(ext))
    reset_extensions_config()
    yield f"http://127.0.0.1:{port}/sse"
    server.should_exit = True
    thread.join(timeout=5)
    reset_extensions_config()


class _NetworklessTelegram(Channel):
    """Telegram with the network client removed. Everything above `send` — the
    base class, including the channel boundary — is the real code."""

    def __init__(self) -> None:
        super().__init__(name="telegram", bus=MessageBus(), config={})
        self._running = True
        self.sent: list[OutboundMessage] = []

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def send(self, msg: OutboundMessage) -> None:
        self.sent.append(msg)


@pytest.fixture
def telegram(monkeypatch):
    """A running channel service with Telegram up, installed where production
    looks for it (the service singleton)."""
    import app.channels.service as service_module

    channel = _NetworklessTelegram()
    monkeypatch.setattr(service_module, "_channel_service", SimpleNamespace(get_channel=lambda name: channel if name == "telegram" else None))
    return channel


class _FakeGateway:
    """The gateway's HTTP surface, served for real on a free port, so the
    engine's own HTTP client is the code under test. `runs/wait` is slow on
    purpose: a blocking call on the event loop shows up as loop lag."""

    RUN_SECONDS = 0.6

    def __init__(self) -> None:
        self.threads: list[dict] = []
        self.runs: list[tuple[str, dict]] = []
        self.reply: dict = {"messages": [{"type": "ai", "content": "darcy-repo needs a decision on the fixture."}]}

    def app(self):
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import JSONResponse
        from starlette.routing import Route

        async def create_thread(request: Request):
            self.threads.append(await request.json())
            return JSONResponse({"thread_id": f"t-{len(self.threads)}"})

        async def runs_wait(request: Request):
            self.runs.append((request.path_params["tid"], await request.json()))
            await asyncio.sleep(self.RUN_SECONDS)
            return JSONResponse(self.reply)

        return Starlette(
            routes=[
                Route("/api/threads", create_thread, methods=["POST"]),
                Route("/api/threads/{tid}/runs/wait", runs_wait, methods=["POST"]),
            ]
        )


@pytest.fixture
def gateway(monkeypatch):
    fake = _FakeGateway()
    port = _free_port()
    server, thread = _serve(fake.app(), port)
    # The engine finds the gateway the way the gateway finds its own port.
    monkeypatch.setenv("GATEWAY_PORT", str(port))
    yield fake
    server.should_exit = True
    thread.join(timeout=5)


def _cron_rule_due_once() -> dict:
    """A daily schedule whose one instant in the catch-up window is the minute
    that just passed — due exactly once, whatever the catch-up policy."""
    at = datetime.now(UTC) - timedelta(minutes=1)
    return {"id": "morning-briefing", "type": "cron", "match": {"schedule": f"{at.minute} {at.hour} * * *"}, "prompt": "Brief me, as of {scheduled_at}.", "destination": "quiet"}


def _config(tmp_path: Path, rules: list[dict]) -> SimpleNamespace:
    rules_file = tmp_path / "rules.json"
    rules_file.write_text(json.dumps({"quiet_hours": {"start": "22:00", "end": "07:30", "timezone": "UTC", "enabled": False}, "rules": rules}))
    return SimpleNamespace(
        trigger_engine=SimpleNamespace(
            enabled=True,
            rules_path=str(rules_file),
            state_dir=str(tmp_path / "state"),
            actor="default",
            tick_seconds=30.0,
            remote=SimpleNamespace(channel="telegram", chat_id=CHAT_ID),
        ),
        database=SimpleNamespace(backend="memory", postgres_url=""),
    )


WATCHER_RULE = {"id": "blocked-session", "type": "watcher", "match": {"event": "waiting-on-user"}, "prompt": "{project} is waiting: {last_message}", "destination": "auto"}


# -- the production shape ------------------------------------------------------


def test_the_production_engine_can_be_constructed(tmp_path) -> None:
    """Before anything about what the engine does: that it exists. Since #32 the
    gateway's start raised TypeError on every attempt, recorded only as
    `handle.error`. No test called `build_loop` past its rules check."""
    loop = build_production_loop(_config(tmp_path, [WATCHER_RULE]))

    assert loop.runner is not None


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="AUDIT T-1: production's watcher feed is a stub that always reports observable=False")
def test_the_watcher_feed_reports_what_a_live_watcher_sees(tmp_path, live_watcher) -> None:
    loop = build_production_loop(_config(tmp_path, [WATCHER_RULE]))

    payload = loop.runner.sources[TriggerType.WATCHER].fetch_sessions()

    assert payload["observable"] is True, f"a live watcher is serving, and production's feed reported: {payload}"
    states = {s["session_id"]: s["state"] for s in payload["sessions"]}
    assert states.get(SESSION_ID) == "waiting-on-user", states


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="AUDIT T-2: QuietDestination fills the remote slot; nothing reaches a channel")
@pytest.mark.asyncio
async def test_a_remote_delivery_reaches_the_configured_channel(tmp_path, telegram) -> None:
    loop = build_production_loop(_config(tmp_path, [WATCHER_RULE]))
    remote = loop.runner.registry.resolve(Destination.REMOTE, present=False)

    # Delivery runs on the engine's worker thread in production, never on the
    # event loop; calling it from a thread here is that shape.
    await asyncio.to_thread(remote.deliver, "darcy-repo is waiting on you.")

    assert [(m.chat_id, m.text) for m in telegram.sent] == [(CHAT_ID, "darcy-repo is waiting on you.")]


@pytest.mark.xfail(strict=True, raises=pytest.fail.Exception, reason="AUDIT T-4: a calendar rule loads, and is then skipped every cycle with a debug log")
def test_a_calendar_rule_is_rejected_naming_the_missing_feed(tmp_path) -> None:
    rule = {"id": "standup", "type": "calendar", "match": {"minutes_before": 10}, "prompt": "{summary} starts soon", "destination": "auto"}

    with pytest.raises(RuntimeError, match="calendar feed"):
        build_production_loop(_config(tmp_path, [rule]))


@pytest.mark.xfail(strict=True, raises=pytest.fail.Exception, reason="AUDIT T-4: a completion rule loads, and is then skipped every cycle with a debug log")
def test_a_completion_rule_is_rejected_naming_the_missing_feed(tmp_path) -> None:
    rule = {"id": "done", "type": "completion", "match": {}, "prompt": "{task_id} finished: {summary}", "destination": "auto"}

    with pytest.raises(RuntimeError, match="completion feed"):
        build_production_loop(_config(tmp_path, [rule]))


@pytest.mark.asyncio
async def test_rule_work_does_not_block_the_event_loop(tmp_path, gateway) -> None:
    """FR-031. The engine shares the gateway's event loop, and a rule's work is
    HTTP calls to that same gateway — a blocking one stalls every request this
    worker serves for as long as the agent run takes, and with one worker it
    stalls the very request it is waiting on."""
    loop = build_production_loop(_config(tmp_path, [_cron_rule_due_once()]))
    lags: list[float] = []

    async def heartbeat() -> None:
        tick = 0.01
        last = time.monotonic()
        while True:
            await asyncio.sleep(tick)
            now = time.monotonic()
            lags.append(now - last - tick)
            last = now

    beat = asyncio.create_task(heartbeat())
    await asyncio.sleep(0.05)  # the heartbeat is ticking before the cycle starts
    try:
        await loop.cycle()
        await asyncio.sleep(0.05)  # ...and ticks once after, so a stall is measured
    finally:
        beat.cancel()

    # Positive control: the slow call happened, so there was something to block on.
    assert len(gateway.runs) == 1, f"the rule did not reach the gateway (runs={gateway.runs})"
    assert max(lags) < 0.2, f"the event loop stalled for {max(lags):.2f}s while a rule ran"
