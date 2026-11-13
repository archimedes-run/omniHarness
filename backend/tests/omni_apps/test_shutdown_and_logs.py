"""Shutdown waits for app refreshes; bridge data never reaches a log (Spec 011 FR-011, FR-012, FR-014).

* The refresher loop and in-flight background refreshes are cancelled AND
  awaited before the database engine closes, within a bound: a refresh still
  inside a session when the engine goes away can hang a worker at shutdown.
* A failed cache write (a locked database) logs the error's type only, and
  the engine hides statement parameters, so the projected payload being
  written appears in no log record and in no exception text.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time

import httpx
from _apps_helpers import MARKER, gmail_answer, manifest

INBOX = {"use": "gmail.unread_subjects", "fields": ["count", "subject"]}
SHUTDOWN_BOUND_S = 10.0


def test_shutdown_awaits_in_flight_refreshes_before_the_engine_closes(gateway, composio, apps, monkeypatch) -> None:
    import sys

    gateway_app = sys.modules["app.gateway.app"]  # the module (the package exports a FastAPI named app)
    from app.gateway.apps import bridge
    from app.gateway.apps.service import load_app

    entered: list[bool] = []

    async def slow(request: httpx.Request) -> httpx.Response:
        entered.append(True)
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            # Cleanup after cancellation takes a moment (as closing a session
            # does): only a shutdown that WAITS sees it finish.
            await asyncio.sleep(0.5)
            raise
        return gmail_answer()

    composio.connect("GMAIL")
    gateway.app.state.composio_client._transport = httpx.MockTransport(slow)
    reg = apps.register(manifest(inbox=INBOX))
    apps.approve(reg.app_id)
    app = load_app(gateway.user_id, reg.app_id)

    async def start_refresh():
        bridge._background(gateway.app.state, apps.repo, app, "inbox")
        await asyncio.sleep(0.2)

    gateway.client.portal.call(start_refresh)
    assert entered and bridge.background_tasks(), "a refresh is in flight"

    seen_at_close: list[list[bool]] = []
    real_stop = gateway_app._stop_trigger_engine

    # The trigger engine stops after the apps refresher and before the
    # channel service and the database: what is still running there would
    # still be running when the engine closes.
    async def stop_trigger_engine(app):
        loops = [t for t in asyncio.all_tasks() if getattr(t.get_coro(), "__qualname__", "") == "run_forever"]
        seen_at_close.append([t.done() for t in bridge.background_tasks()] + [t.done() for t in loops])
        await real_stop(app)

    monkeypatch.setattr(gateway_app, "_stop_trigger_engine", stop_trigger_engine)
    t0 = time.monotonic()
    gateway.client.__exit__(None, None, None)
    took = time.monotonic() - t0
    assert took < SHUTDOWN_BOUND_S, f"shutdown took {took:.1f} s"
    assert seen_at_close and all(seen_at_close[0]), f"tasks still running when the engine closed: {seen_at_close}"


def test_a_locked_database_puts_no_bridge_data_in_any_log(gateway, composio, apps, caplog) -> None:
    caplog.set_level(logging.DEBUG, logger="app")
    caplog.set_level(logging.WARNING)
    composio.connect("GMAIL")
    composio.fake.answers["GMAIL_FETCH_EMAILS"] = gmail_answer(subject=f"Locked {MARKER}")
    reg = apps.register(manifest(inbox=INBOX))
    apps.approve(reg.app_id)
    db = next((gateway.tmp / "data").glob("*.db"))
    real = apps.repo.record_answer
    raised: list[str] = []

    async def record_while_locked(**kwargs):
        lock = sqlite3.connect(db, isolation_level=None, timeout=1)
        lock.execute("BEGIN EXCLUSIVE")
        try:
            try:
                return await real(**kwargs)
            except Exception as exc:
                raised.append(f"{type(exc).__name__}: {exc}")
                raise
        finally:
            lock.execute("ROLLBACK")
            lock.close()

    apps.repo.record_answer = record_while_locked
    try:
        resp = gateway.client.get(f"/api/apps/{reg.app_id}/data/inbox")
    finally:
        del apps.repo.record_answer
    assert raised and "locked" in raised[0], raised
    assert MARKER not in raised[0], "the engine hides statement parameters"
    assert MARKER not in caplog.text, "only the error's type is logged"
    assert any("could not be stored (OperationalError)" in r.getMessage() for r in caplog.records)
    assert MARKER not in resp.text


def test_a_failed_cache_write_is_logged_by_type_only(gateway, composio, apps, caplog) -> None:
    """The catch around the write, on its own: an error whose text carries the
    data (as a driver's message could) still logs only its type."""
    caplog.set_level(logging.DEBUG, logger="app")
    composio.connect("GMAIL")
    composio.fake.answers["GMAIL_FETCH_EMAILS"] = gmail_answer(subject=f"Typed {MARKER}")
    reg = apps.register(manifest(inbox=INBOX))
    apps.approve(reg.app_id)

    async def fails(**kwargs):
        raise RuntimeError(f"write failed for {kwargs.get('data_json')}")

    apps.repo.record_answer = fails
    try:
        resp = gateway.client.get(f"/api/apps/{reg.app_id}/data/inbox")
    finally:
        del apps.repo.record_answer
    assert MARKER not in caplog.text and MARKER not in resp.text
    assert any("could not be stored (RuntimeError)" in r.getMessage() for r in caplog.records)


def test_an_unexpected_bridge_error_is_a_fixed_500_logged_by_type(gateway, composio, apps, caplog, monkeypatch) -> None:
    from app.gateway.apps import bridge

    caplog.set_level(logging.DEBUG, logger="app")
    reg = apps.register(manifest(inbox=INBOX))
    apps.approve(reg.app_id)

    async def boom(*a, **k):
        raise RuntimeError(f"cache read failed: {MARKER}")

    monkeypatch.setattr(bridge, "serve", boom)
    resp = gateway.client.get(f"/api/apps/{reg.app_id}/data/inbox")
    assert resp.status_code == 500 and resp.json()["detail"]["code"] == "bridge_failed"
    assert MARKER not in caplog.text and MARKER not in resp.text
