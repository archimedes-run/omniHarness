"""The gateway's shutdown ends within a bound, whatever is still in flight (issue #192).

Seen in CI: a trigger-engine test's teardown (the app's shutdown) ran past the
300 s hard limit, and every later test on that worker failed on state the
half-shut app still held. The cause: a database connection whose worker
thread had died. aiosqlite runs each connection on a thread that hands every
result back to the event loop that asked; when that loop is closed (a
request served on a short-lived loop of its own, as a TestClient used
without `with` serves it, or any other thread's own loop), handing the result
back raises in the worker thread and the thread dies. Every later call on
that connection waits forever, the checkpointer's close at shutdown among
them, and the gateway's shutdown (a reload in the live app) never finished.

Each shutdown step that can wait on something outside its control is now
bounded: past the bound it is logged and the next step runs.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

#: Each bounded step gets this long in these tests (the gateway's default is 5 s).
STEP_BOUND_S = 0.5
#: The whole shutdown, with every step stuck at once, ends well inside this.
SHUTDOWN_BOUND_S = 10.0


@pytest.fixture
def short_bounds(monkeypatch):
    import sys

    import app.gateway.deps as deps

    gateway_app = sys.modules["app.gateway.app"]  # the module (the package exports a FastAPI named app)
    monkeypatch.setattr(gateway_app, "_SHUTDOWN_HOOK_TIMEOUT_SECONDS", STEP_BOUND_S)
    monkeypatch.setattr(deps, "RUNTIME_SHUTDOWN_TIMEOUT_SECONDS", STEP_BOUND_S)


def _shut_down(client) -> float:
    """Close the app (its lifespan's shutdown) on a thread; how long it took, or inf."""
    done = threading.Event()
    started = time.monotonic()

    def close():
        try:
            client.__exit__(None, None, None)
        finally:
            done.set()

    threading.Thread(target=close, daemon=True).start()
    return time.monotonic() - started if done.wait(SHUTDOWN_BOUND_S) else float("inf")


def _kill_worker_thread(conn) -> None:
    """What a request served on a short-lived loop does to a shared aiosqlite
    connection: its loop closes before the connection's thread hands the
    result back, and the thread dies handing it to a closed loop."""

    def other_loop():
        async def go():
            asyncio.ensure_future(conn._execute(time.sleep, 0.2))
            await asyncio.sleep(0.01)

        asyncio.run(go())  # cancels the pending call and closes the loop

    worker = threading.Thread(target=other_loop)
    worker.start()
    worker.join()
    conn._thread.join(timeout=5)
    assert not conn._thread.is_alive(), "the connection's thread survived; this test proves nothing"


def test_shutdown_ends_with_a_dead_checkpointer_connection(make_gateway, short_bounds):
    app, client = make_gateway()
    conn = app.state.checkpointer.conn
    _kill_worker_thread(conn)
    took = _shut_down(client)
    assert took < SHUTDOWN_BOUND_S, "the shutdown hung on a database connection whose thread had died"


def test_shutdown_ends_with_a_dead_database_engine_connection(make_gateway, short_bounds):
    from sqlalchemy import text

    from omniharness.persistence.engine import get_engine

    _app, client = make_gateway()
    engine = get_engine()

    async def checkout():
        """A pooled connection, back in the pool (the engine's dispose closes it)."""
        async with engine.connect() as conn:
            await conn.execute(text("select 1"))
            raw = await conn.get_raw_connection()
            return raw.driver_connection

    driver = client.portal.call(checkout)
    _kill_worker_thread(driver)
    took = _shut_down(client)
    assert took < SHUTDOWN_BOUND_S, "the shutdown hung on the database engine's dead connection"


def test_shutdown_ends_with_a_sweep_that_will_not_stop(make_gateway, short_bounds, monkeypatch):
    """The expiry and question sweeps are cancelled and awaited: one whose
    cleanup after the cancel never ends on its own (a close on a dead
    connection, as above) does not hold the shutdown."""
    import app.gateway.questions as questions
    import app.gateway.resume as resume

    monkeypatch.setattr(resume, "resume_expired_forever", _will_not_stop)
    monkeypatch.setattr(questions, "sweep_forever", _will_not_stop)
    _app, client = make_gateway()
    took = _shut_down(client)
    assert took < SHUTDOWN_BOUND_S, "the shutdown hung on a sweep that would not stop"


def test_shutdown_ends_with_a_run_still_streaming(make_gateway, short_bounds, monkeypatch):
    """A run mid-stream when the gateway stops (a reload during a reply)."""
    streaming = threading.Event()

    class Agent:
        async def astream(self, *_args, **_kwargs):
            streaming.set()
            await asyncio.Event().wait()
            yield {}

    monkeypatch.setattr("app.gateway.services.resolve_agent_factory", lambda assistant_id: lambda config, **_: Agent())
    _app, client = make_gateway()
    tid = client.post("/api/threads", json={}).json()["thread_id"]
    resp = client.post(f"/api/threads/{tid}/runs", json={"assistant_id": "lead_agent", "input": {"messages": [{"role": "human", "content": "hi"}]}})
    assert resp.status_code == 200, resp.text
    assert streaming.wait(10), "the run never started streaming; this test proves nothing"
    took = _shut_down(client)
    assert took < SHUTDOWN_BOUND_S, "the shutdown hung on a run still streaming"


async def _will_not_stop(*_args, **_kwargs):
    """A step whose cleanup after the cancel waits on what never answers."""
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        await asyncio.Event().wait()
        raise


def test_shutdown_ends_with_a_trigger_engine_that_will_not_stop(make_gateway, short_bounds, monkeypatch):
    """A firing in flight when the engine is told to stop. asyncio.wait_for
    bounded this step before, but it waits for the cancelled step to finish,
    so a step that does not finish when cancelled held the shutdown anyway."""
    import sys
    from types import SimpleNamespace

    gateway_app = sys.modules["app.gateway.app"]

    async def started(_app):
        return SimpleNamespace(lock=None)

    monkeypatch.setattr(gateway_app, "_start_trigger_engine", started)
    monkeypatch.setattr("app.trigger_engine.lifespan.stop", _will_not_stop)
    _app, client = make_gateway()
    took = _shut_down(client)
    assert took < SHUTDOWN_BOUND_S, "the shutdown hung on the trigger engine's stop"
