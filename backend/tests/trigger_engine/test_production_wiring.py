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
import pytest_asyncio

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


@pytest.fixture(autouse=True)
def _no_ambient_extensions(tmp_path, monkeypatch):
    """Article XIV: nothing here may read the developer's untracked
    extensions_config.json. Every test starts with none configured; a test
    that needs the watcher registers one."""
    from omniharness.config.extensions_config import reset_extensions_config

    empty = tmp_path / "no_extensions.json"
    empty.write_text(json.dumps({"mcpServers": {}, "skills": {}}))
    monkeypatch.setenv("OMNI_HARNESS_EXTENSIONS_CONFIG_PATH", str(empty))
    reset_extensions_config()
    yield
    reset_extensions_config()


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
def telegram(tmp_path, monkeypatch):
    """A running channel service with Telegram up, installed where production
    looks for it (the service singleton). Its conversation store is the real
    ChannelStore, so chat -> thread mapping is production code."""
    import app.channels.service as service_module
    from app.channels.store import ChannelStore

    channel = _NetworklessTelegram()
    channel.store = ChannelStore(path=tmp_path / "channels.json")
    monkeypatch.setattr(service_module, "_channel_service", SimpleNamespace(get_channel=lambda name: channel if name == "telegram" else None, store=channel.store))
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
        self.status_code = 200
        self.run_seconds = self.RUN_SECONDS

    def fail_runs(self, error: str) -> None:
        """Answer runs/wait the way the gateway does for a failed run."""
        self.status_code = 500
        self.reply = {"detail": {"run_id": "run-x", "status": "error", "error": error}}
        self.run_seconds = 0.0

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
            await asyncio.sleep(self.run_seconds)
            return JSONResponse(self.reply, status_code=self.status_code)

        from starlette.middleware import Middleware

        from app.gateway.csrf_middleware import CSRFMiddleware

        # The gateway's REAL CSRF middleware. Without it this fake accepted the
        # engine's calls that the real gateway rejects with 403 — found only in
        # the live end-to-end check, because the test world lacked the check.
        return Starlette(
            routes=[
                Route("/api/threads", create_thread, methods=["POST"]),
                Route("/api/threads/{tid}/runs/wait", runs_wait, methods=["POST"]),
            ],
            middleware=[Middleware(CSRFMiddleware)],
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


def _config(tmp_path: Path, rules: list[dict], **top) -> SimpleNamespace:
    rules_file = tmp_path / "rules.json"
    rules_file.write_text(json.dumps({"quiet_hours": {"start": "22:00", "end": "07:30", "timezone": "UTC", "enabled": False}, "rules": rules, **top}))
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


def _build(tmp_path: Path, rules: list[dict], *, run_store=None, **top):
    """`build_production_loop` with what the gateway lifespan passes it."""
    from omniharness.runtime.runs.store.memory import MemoryRunStore

    return build_production_loop(_config(tmp_path, rules, **top), run_store=run_store if run_store is not None else MemoryRunStore())


WATCHER_RULE = {"id": "blocked-session", "type": "watcher", "match": {"event": "waiting-on-user"}, "prompt": "{project} is waiting: {last_message}", "destination": "auto"}


# -- the production shape ------------------------------------------------------


@pytest.mark.asyncio
async def test_the_production_engine_can_be_constructed(tmp_path) -> None:
    """Before anything about what the engine does: that it exists. Since #32 the
    gateway's start raised TypeError on every attempt, recorded only as
    `handle.error`. No test called `build_loop` past its rules check."""
    loop = _build(tmp_path, [WATCHER_RULE])

    assert loop.runner is not None


@pytest.mark.asyncio
async def test_the_watcher_feed_reports_what_a_live_watcher_sees(tmp_path, live_watcher) -> None:
    loop = _build(tmp_path, [WATCHER_RULE])

    # Called where production calls it: on the engine's worker thread.
    payload = await loop.runner.offload(loop.runner.sources[TriggerType.WATCHER].fetch_sessions)

    assert payload["observable"] is True, f"a live watcher is serving, and production's feed reported: {payload}"
    states = {s["session_id"]: s["state"] for s in payload["sessions"]}
    assert states.get(SESSION_ID) == "waiting-on-user", states


@pytest.mark.asyncio
async def test_a_remote_delivery_reaches_the_configured_channel(tmp_path, telegram) -> None:
    loop = _build(tmp_path, [WATCHER_RULE])
    remote = loop.runner.registry.resolve(Destination.REMOTE, present=False)

    # Delivery runs on the engine's worker thread in production, never on the
    # event loop; calling it from a thread here is that shape.
    await asyncio.to_thread(remote.deliver, "darcy-repo is waiting on you.")

    assert [(m.chat_id, m.text) for m in telegram.sent] == [(CHAT_ID, "darcy-repo is waiting on you.")]


@pytest.mark.asyncio
async def test_a_calendar_rule_is_rejected_naming_the_missing_feed(tmp_path) -> None:
    rule = {"id": "standup", "type": "calendar", "match": {"minutes_before": 10}, "prompt": "{summary} starts soon", "destination": "auto"}

    with pytest.raises(RuntimeError, match="calendar feed"):
        _build(tmp_path, [rule])


@pytest.mark.asyncio
async def test_a_completion_rule_is_rejected_naming_the_missing_feed(tmp_path) -> None:
    rule = {"id": "done", "type": "completion", "match": {}, "prompt": "{task_id} finished: {summary}", "destination": "auto"}

    with pytest.raises(RuntimeError, match="completion feed"):
        _build(tmp_path, [rule])


@pytest.mark.asyncio
async def test_rule_work_does_not_block_the_event_loop(tmp_path, gateway) -> None:
    """FR-031. The engine shares the gateway's event loop, and a rule's work is
    HTTP calls to that same gateway — a blocking one stalls every request this
    worker serves for as long as the agent run takes, and with one worker it
    stalls the very request it is waiting on."""
    loop = _build(tmp_path, [_cron_rule_due_once()])
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


# -- FR-016: not talking over an exchange --------------------------------------


@pytest_asyncio.fixture
async def sql_run_store(tmp_path):
    """The run store production uses: RunRepository on SQL. MemoryRunStore
    let the busy check pass here while the real one refused every query —
    'list_by_thread called with user_id=AUTO but no user context is set' —
    found only in the live end-to-end check (Article XI)."""
    from omniharness.persistence.engine import close_engine, get_session_factory, init_engine
    from omniharness.persistence.run import RunRepository

    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'runs.db'}", sqlite_dir=str(tmp_path))
    yield RunRepository(get_session_factory())
    await close_engine()


async def _running(store, run_id: str, thread_id: str) -> None:
    # As production records them: owned by a user, not by no one.
    await store.put(run_id, thread_id=thread_id, user_id="the-user", status="running")


@pytest.mark.asyncio
async def test_an_exchange_in_the_destination_conversation_holds_the_message(tmp_path, telegram, sql_run_store) -> None:
    """The exchange a proactive message would interrupt is the one in the chat
    it lands in — the user's Telegram conversation — not only the rule's own
    thread, where the user never types."""
    store = sql_run_store
    telegram.store.set_thread_id("telegram", CHAT_ID, "conv-1")
    loop = _build(tmp_path, [WATCHER_RULE], run_store=store)

    # Positive control: with nothing running, the check says free.
    assert await loop.runner.offload(loop.runner._is_mid_exchange, "rule-thread") is False

    await _running(store, "r1", "conv-1")
    assert await loop.runner.offload(loop.runner._is_mid_exchange, "rule-thread") is True


@pytest.mark.asyncio
async def test_a_run_on_the_rule_thread_holds_the_message(tmp_path, sql_run_store) -> None:
    """FR-016 as written: the target thread."""
    store = sql_run_store
    loop = _build(tmp_path, [WATCHER_RULE], run_store=store)
    await _running(store, "r1", "rule-thread")

    assert await loop.runner.offload(loop.runner._is_mid_exchange, "rule-thread") is True


@pytest.mark.asyncio
async def test_unknown_busyness_holds_rather_than_interrupts(tmp_path) -> None:
    """When the check cannot be made, hold: the interrupt queue's bound
    (FR-016a) releases it, so holding costs minutes; sending talks over the
    user. The comment in RuleRunner said this; the code returned 'free'."""

    class _Down:
        async def list_by_thread(self, thread_id, **_):
            raise ConnectionError("run store unreachable")

    loop = _build(tmp_path, [WATCHER_RULE], run_store=_Down())

    assert await loop.runner.offload(loop.runner._is_mid_exchange, "rule-thread") is True
    # ...and the audit must not claim an exchange was SEEN.
    assert "could not tell" in loop.runner._hold_reason and "ConnectionError" in loop.runner._hold_reason


# -- a failed run is a failure, not a message ----------------------------------


def _audit(loop) -> list[dict]:
    return loop.runner.audit.entries()


@pytest.mark.asyncio
async def test_a_failed_run_resolves_failed_with_its_reason_and_is_not_delivered(tmp_path, gateway) -> None:
    """It used to arrive as '(the assistant returned nothing)', and the event
    was fingerprinted so it never fired again."""
    gateway.fail_runs("FileNotFoundError: Agent directory not found")
    loop = _build(tmp_path, [_cron_rule_due_once()])

    await loop.cycle()

    assert len(gateway.runs) == 1, "positive control: the run was attempted"
    [entry] = _audit(loop)
    assert entry["outcome"] == "failed"
    assert "Agent directory not found" in entry["reason"]
    assert "attempt 1 of 3" in entry["reason"]
    assert loop.runner.registry.quiet.delivered == []


@pytest.mark.asyncio
async def test_a_failed_run_is_retried_three_times_then_given_up(tmp_path, gateway) -> None:
    """The stated retry rule: up to three attempts per event, one per cycle,
    then the event is settled as FAILED and never attempted again."""
    gateway.fail_runs("RuntimeError: model unavailable")
    loop = _build(tmp_path, [_cron_rule_due_once()])

    for _ in range(5):
        await loop.cycle()

    assert len(gateway.runs) == 3, f"expected exactly three attempts, saw {len(gateway.runs)}"
    reasons = [e["reason"] for e in _audit(loop)]
    assert reasons[-1].startswith("gave up after 3 attempts"), reasons
    assert loop.runner.registry.quiet.delivered == []


@pytest.mark.asyncio
async def test_a_run_with_no_reply_is_not_delivered_as_an_empty_message(tmp_path, gateway) -> None:
    gateway.reply = {"messages": [{"type": "human", "content": "Brief me"}]}
    loop = _build(tmp_path, [_cron_rule_due_once()])

    await loop.cycle()

    [entry] = _audit(loop)
    assert entry["outcome"] == "failed"
    assert "no reply" in entry["reason"]
    assert loop.runner.registry.quiet.delivered == []


# -- FR-018: a missed schedule fires once, late, and says so -------------------


@pytest.mark.asyncio
async def test_a_frequent_schedule_does_not_replay_a_day_of_missed_runs(tmp_path, gateway) -> None:
    """A gateway down overnight under a */5 rule used to come back to 288 runs,
    each one a message to the user's phone."""
    gateway.run_seconds = 0.0
    every_five = {"id": "pulse", "type": "cron", "match": {"schedule": "*/5 * * * *"}, "prompt": "Status as of {scheduled_at}.", "destination": "quiet"}
    loop = _build(tmp_path, [every_five], defaults={"coalesce_window_seconds": 0})

    await loop.cycle()
    await loop.cycle()  # and the skipped instants do not surface later

    assert len(gateway.runs) == 1, f"{len(gateway.runs)} missed runs were replayed"
    [message] = loop.runner.registry.quiet.delivered
    assert "skipped rather than replayed" in message, message


# -- FR-013b: re-check at release ----------------------------------------------


def _watcher_firing(state: str = "waiting-on-user", summary: str = "Should I pin the version or rewrite the fixture?"):
    from app.trigger_engine.models import Firing, TriggerEvent

    event = TriggerEvent(type=TriggerType.WATCHER, event_id=SESSION_ID, at=datetime.now(UTC), fields={"session_id": SESSION_ID, "state": state, "last_message": summary, "project": "darcy-repo"})
    return Firing(rule_id="blocked-session", event=event, prompt="p")


@pytest.mark.asyncio
async def test_a_deferred_alert_whose_session_is_still_waiting_is_delivered(tmp_path, live_watcher) -> None:
    """Positive control for the re-check: it can say yes."""
    loop = _build(tmp_path, [WATCHER_RULE])

    assert await loop.runner.offload(loop.runner.releaser.still_true, _watcher_firing()) is True


@pytest.mark.asyncio
async def test_a_deferred_alert_whose_session_moved_on_is_not_delivered(tmp_path, live_watcher) -> None:
    """The session that blocked overnight and was answered before 07:30 must
    not be reported at 07:30 (FR-013b). It was: still_true was `lambda: True`.
    The positive control above shows the same check can say yes."""
    loop = _build(tmp_path, [WATCHER_RULE])
    answered = _watcher_firing(summary="an earlier question the user has since answered")

    assert await loop.runner.offload(loop.runner.releaser.still_true, answered) is False


@pytest.mark.asyncio
async def test_a_calendar_rule_added_to_a_running_engine_is_rejected_too(tmp_path, gateway) -> None:
    """The loop hot-reloads the rule file every cycle. Rejecting only at startup
    would let the same rule slip in later and be skipped silently."""
    loop = _build(tmp_path, [WATCHER_RULE])
    rules_file = Path(loop.loader.path)
    standup = {"id": "standup", "type": "calendar", "match": {"minutes_before": 10}, "prompt": "{summary} soon", "destination": "auto"}
    rules_file.write_text(json.dumps({"rules": [WATCHER_RULE, standup]}))
    import os

    os.utime(rules_file, (time.time() + 5, time.time() + 5))  # a different mtime, so the reload happens

    cfg = loop.loader.load()

    assert [r.id for r in cfg.rules] == ["blocked-session"], "the previous valid rules stay in force"
    assert "calendar feed" in (loop.loader.last_error or ""), loop.loader.last_error


@pytest.mark.asyncio
async def test_a_disabled_calendar_rule_is_allowed_to_wait_for_its_feed(tmp_path) -> None:
    draft = {"id": "standup", "type": "calendar", "enabled": False, "match": {"minutes_before": 10}, "prompt": "{summary} soon", "destination": "auto"}

    loop = _build(tmp_path, [WATCHER_RULE, draft])

    assert {r.id for r in loop.loader.config.rules} == {"blocked-session", "standup"}


# -- the watcher's absences are told apart -------------------------------------


def _extensions(tmp_path, monkeypatch, servers: dict) -> None:
    from omniharness.config.extensions_config import reset_extensions_config

    ext = tmp_path / "extensions_config.json"
    ext.write_text(json.dumps({"mcpServers": servers, "skills": {}}))
    monkeypatch.setenv("OMNI_HARNESS_EXTENSIONS_CONFIG_PATH", str(ext))
    reset_extensions_config()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("servers", "said"),
    [
        ({}, "never been configured"),
        ({"session-watcher": {"enabled": False, "type": "sse", "url": "http://127.0.0.1:9/sse"}}, "disabled"),
        ({"session-watcher": {"enabled": True, "type": "sse", "url": "http://127.0.0.1:9/sse"}}, "127.0.0.1:9"),
    ],
    ids=["never-configured", "disabled", "unreachable"],
)
async def test_an_absent_watcher_says_which_kind_of_absent(tmp_path, monkeypatch, servers, said) -> None:
    """Not configured, disabled and unreachable are fixed differently, so the
    rule's recorded reason names which. None of them is an empty session list."""
    from app.trigger_engine.sources.base import SourceUnavailable

    _extensions(tmp_path, monkeypatch, servers)
    loop = _build(tmp_path, [WATCHER_RULE])
    source = loop.runner.sources[TriggerType.WATCHER]

    started = time.monotonic()
    with pytest.raises(SourceUnavailable, match=said) as raised:
        await loop.runner.offload(source.poll, loop.loader.config.rules[0], datetime.now(UTC))
    assert time.monotonic() - started < 12, "an unreachable watcher held the engine longer than its timeout"
    assert "ExceptionGroup" not in str(raised.value), "the reason names the task group, not what went wrong"


# -- the whole pipe: watcher -> agent -> Telegram ------------------------------

SECRET = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6"
AUTO_RULE = {**WATCHER_RULE, "destination": "auto"}


@pytest.mark.asyncio
async def test_a_blocked_session_reaches_telegram_redacted(tmp_path, live_watcher, gateway, telegram) -> None:
    """End to end in the production shape: the real watcher sees a waiting
    session, the engine asks the agent (over real HTTP), and the reply arrives
    on the configured chat through the channel boundary, redacted."""
    gateway.run_seconds = 0.0
    gateway.reply = {"messages": [{"type": "ai", "content": f"They asked whether to pin the version. The deploy token is {SECRET}."}]}
    loop = _build(tmp_path, [AUTO_RULE], defaults={"coalesce_window_seconds": 0})

    await loop.cycle()

    [sent] = telegram.sent
    assert sent.chat_id == CHAT_ID
    assert "darcy-repo" in sent.text and "waiting on you" in sent.text, sent.text
    assert SECRET not in sent.text and "[redacted]" in sent.text, sent.text
    # Through the coalescing window: queued, then delivered as one message.
    assert [e["outcome"] for e in _audit(loop)] == ["queued", "delivered"]


@pytest.mark.asyncio
async def test_a_blocked_session_waits_while_the_user_is_mid_exchange_on_telegram(tmp_path, live_watcher, gateway, telegram, sql_run_store) -> None:
    gateway.run_seconds = 0.0
    store = sql_run_store
    telegram.store.set_thread_id("telegram", CHAT_ID, "conv-1")
    await _running(store, "r1", "conv-1")
    loop = _build(tmp_path, [AUTO_RULE], run_store=store, defaults={"coalesce_window_seconds": 0})

    await loop.cycle()

    assert telegram.sent == [], "delivered over an exchange in progress"
    assert [e["outcome"] for e in _audit(loop)] == ["queued"]

    await store.update_status("r1", "success")
    await loop.cycle()
    assert len(telegram.sent) == 1, "held message was not released when the exchange ended"


@pytest.mark.asyncio
async def test_no_recipient_configured_is_a_failure_that_says_what_to_set(tmp_path, live_watcher, gateway, telegram) -> None:
    gateway.run_seconds = 0.0
    cfg = _config(tmp_path, [AUTO_RULE], defaults={"coalesce_window_seconds": 0})
    cfg.trigger_engine.remote = None
    from omniharness.runtime.runs.store.memory import MemoryRunStore

    loop = build_production_loop(cfg, run_store=MemoryRunStore())

    await loop.cycle()

    assert telegram.sent == []
    entry = _audit(loop)[-1]
    assert entry["outcome"] == "failed" and "trigger_engine.remote" in entry["reason"], entry


@pytest.mark.asyncio
async def test_a_channel_that_is_not_running_is_a_recorded_failure(tmp_path, live_watcher, gateway, telegram) -> None:
    """It used to vanish: deliver() raised out of release() after the event was
    fingerprinted, before anything was audited."""
    gateway.run_seconds = 0.0
    telegram._running = False
    loop = _build(tmp_path, [AUTO_RULE], defaults={"coalesce_window_seconds": 0})

    await loop.cycle()

    entry = _audit(loop)[-1]
    assert entry["outcome"] == "failed" and "not running" in entry["reason"], entry


@pytest.mark.asyncio
async def test_the_remote_destination_delivers_through_the_channel_boundary(tmp_path, telegram) -> None:
    """Independent of the Releaser's own redaction upstream: text handed to the
    remote destination leaves only through Channel.deliver, which redacts."""
    loop = _build(tmp_path, [WATCHER_RULE])
    remote = loop.runner.registry.resolve(Destination.REMOTE, present=False)

    await asyncio.to_thread(remote.deliver, f"token {SECRET}")

    [sent] = telegram.sent
    assert SECRET not in sent.text and "[redacted]" in sent.text


@pytest.mark.asyncio
async def test_the_rule_timeout_covers_a_rules_legitimate_work(tmp_path) -> None:
    """Live E2E: 'rule blocked-session exceeded 0:00:30 and was cancelled' on an
    ordinary agent run. The engine's 30 s default never fired while rule work
    blocked the loop; off the loop it fires on every run, and three mute the
    rule. A rule's work is: create its thread, run the agent, deliver."""
    from app.gateway.trigger_destinations import DELIVERY_TIMEOUT_SECONDS
    from app.gateway.trigger_engine_wiring import GATEWAY_CALL_TIMEOUT_SECONDS

    loop = _build(tmp_path, [WATCHER_RULE])

    needed = 2 * GATEWAY_CALL_TIMEOUT_SECONDS + DELIVERY_TIMEOUT_SECONDS
    assert loop.engine.rule_timeout.total_seconds() >= needed, f"{loop.engine.rule_timeout} cannot cover a rule's work ({needed}s)"


@pytest.mark.asyncio
async def test_a_brief_held_behind_a_conversation_is_delivered_when_it_ends(tmp_path, gateway, telegram, sql_run_store) -> None:
    """FR-016d end to end, in the production shape. It used to be held, then
    released at the bound as 'queue-expired', and expired as un-recheckable."""
    gateway.run_seconds = 0.0
    store = sql_run_store
    telegram.store.set_thread_id("telegram", CHAT_ID, "conv-1")
    await _running(store, "r1", "conv-1")
    brief = {**_cron_rule_due_once(), "destination": "auto"}
    loop = _build(tmp_path, [brief], run_store=store, defaults={"coalesce_window_seconds": 0})

    await loop.cycle()
    assert telegram.sent == [] and [e["outcome"] for e in _audit(loop)] == ["queued"]

    await store.update_status("r1", "success")
    await loop.cycle()

    assert len(telegram.sent) == 1, "the brief held behind a conversation was not delivered"
    assert [e["outcome"] for e in _audit(loop)] == ["queued", "delivered"]


@pytest.mark.asyncio
async def test_the_queue_bounds_come_from_the_rule_file(tmp_path) -> None:
    """InterruptQueue() was built with its own 5 minutes, so
    queued_turn_max_wait_seconds was parsed and never reached the queue."""
    loop = _build(tmp_path, [WATCHER_RULE], defaults={"queued_turn_max_wait_seconds": 90, "held_schedule_max_wait_seconds": 3600})

    assert loop.runner.interrupts.max_wait.total_seconds() == 90
    assert loop.runner.interrupts.schedule_max_wait.total_seconds() == 3600


@pytest.mark.asyncio
async def test_a_brief_released_late_after_a_conversation_carries_the_late_note(tmp_path, gateway, telegram, sql_run_store) -> None:
    """Composed on time, so composed WITHOUT a note; the conversation ran long.
    The note is written for the moment of delivery, naming why it is late."""
    gateway.run_seconds = 0.0
    telegram.store.set_thread_id("telegram", CHAT_ID, "conv-1")
    await _running(sql_run_store, "r1", "conv-1")
    brief = {**_cron_rule_due_once(), "destination": "auto"}
    loop = _build(tmp_path, [brief], run_store=sql_run_store, defaults={"coalesce_window_seconds": 0})
    await loop.cycle()
    await sql_run_store.update_status("r1", "success")
    [rule] = loop.loader.config.rules

    await loop.runner.offload(loop.runner.release_queued, rule, datetime.now(UTC) + timedelta(minutes=40))

    [sent] = telegram.sent
    assert sent.text.startswith("Running late") and "mid-conversation" in sent.text, sent.text


@pytest.mark.asyncio
async def test_the_production_loop_wakes_for_a_zoned_brief(tmp_path) -> None:
    """The loop's own wakeup computation, from the rule file, honours the zone."""
    brief = {"id": "morning-briefing", "type": "cron", "match": {"schedule": "45 8 * * 1-5", "timezone": "America/New_York"}, "prompt": "Brief me as of {scheduled_at}.", "destination": "auto"}
    loop = _build(tmp_path, [brief])

    friday_after_brief = datetime(2026, 10, 30, 13, 0, tzinfo=UTC)
    monday_brief_est = datetime(2026, 11, 2, 13, 45, tzinfo=UTC)
    assert loop.scheduler.next_wakeup([("morning-briefing", "45 8 * * 1-5", "America/New_York")], friday_after_brief) == monday_brief_est
    # Within the 60 s idle pulse of the brief, the brief is the next wakeup.
    assert loop.next_wakeup(datetime(2026, 11, 2, 13, 44, 30, tzinfo=UTC)) == monday_brief_est


# -- Feature 004 US2: the triggers surface, over state the REAL engine wrote --


def _surface(cfg):
    from _router_auth_helpers import make_authed_test_app
    from fastapi.testclient import TestClient

    from app.gateway.routers import triggers

    app = make_authed_test_app()
    app.include_router(triggers.router)
    app.state.config = cfg
    with TestClient(app) as client:
        return client.get("/api/triggers/rules").json(), client.get("/api/triggers/firings").json()


@pytest.mark.asyncio
async def test_firings_coalesced_into_one_message_name_each_other(tmp_path, gateway, telegram) -> None:
    """SC-010 / T053: two rules firing in one cycle are delivered as one message,
    and each firing in the log names the other."""
    gateway.run_seconds = 0.0
    a, b = {**_cron_rule_due_once(), "id": "brief-a", "destination": "auto"}, {**_cron_rule_due_once(), "id": "brief-b", "destination": "auto"}
    cfg = _config(tmp_path, [a, b], defaults={"coalesce_window_seconds": 0})
    from omniharness.runtime.runs.store.memory import MemoryRunStore

    loop = build_production_loop(cfg, run_store=MemoryRunStore())
    await loop.cycle()
    assert len(telegram.sent) == 1, "positive control: the two firings were delivered as ONE message"

    _, firings = _surface(cfg)

    delivered = {f["rule_id"]: f for f in firings["firings"] if f["outcome"] == "delivered"}
    assert delivered["brief-a"]["batch"] == "batched" and delivered["brief-a"]["batch_id"] == delivered["brief-b"]["batch_id"]
    assert [m["rule_id"] for m in delivered["brief-a"]["delivered_with"]] == ["brief-b"]
    assert [m["rule_id"] for m in delivered["brief-b"]["delivered_with"]] == ["brief-a"]


@pytest.mark.asyncio
async def test_a_quiet_hours_suppression_a_delivery_and_a_never_evaluated_rule_differ(tmp_path, gateway, telegram) -> None:
    """SC-008 / SC-009, over the real engine's own records."""
    from datetime import UTC as _UTC

    gateway.run_seconds = 0.0
    now = datetime.now(_UTC)
    start, end = (now - timedelta(hours=1)).strftime("%H:%M"), (now + timedelta(hours=1)).strftime("%H:%M")
    hushed = {**_cron_rule_due_once(), "id": "hushed", "destination": "auto"}
    dormant = {**_cron_rule_due_once(), "id": "dormant", "enabled": False}
    cfg = _config(tmp_path, [hushed, dormant], defaults={"coalesce_window_seconds": 0})
    cfg_rules = Path(cfg.trigger_engine.rules_path)
    doc = json.loads(cfg_rules.read_text())
    doc["quiet_hours"] = {"start": start, "end": end, "timezone": "UTC", "enabled": True}
    cfg_rules.write_text(json.dumps(doc))
    from omniharness.runtime.runs.store.memory import MemoryRunStore

    loop = build_production_loop(cfg, run_store=MemoryRunStore())
    await loop.cycle()

    rules, firings = _surface(cfg)

    r = {x["id"]: x for x in rules["rules"]}
    assert r["hushed"]["activity"] == "fired" and r["hushed"]["last_outcome"] == "suppressed"
    assert r["dormant"]["activity"] == "never-evaluated" and r["dormant"]["last_evaluated"] == "never"
    [f] = firings["firings"]
    assert f["outcome"] == "suppressed" and f["reason"].startswith("quiet hours"), f  # verbatim, not a status word (FR-019)
