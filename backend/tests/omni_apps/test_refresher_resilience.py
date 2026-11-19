"""The apps refresher keeps going (Spec 011 FR-013, FR-014).

* One source (or one app) that raises is logged once per pass, by type, and
  the other sources are still refreshed; the next pass runs as usual.
* A pass that raises does not end the loop: it is logged, the next pass waits
  longer (backoff), and the loop recovers. An unexpected end is logged.
* The loop starts with every gateway start and is stopped at shutdown.
* An app that is not approved is never refreshed.
* Opening an app whose cached data is already past the "may be out of date"
  line reads it now instead of answering with that data.
"""

from __future__ import annotations

import asyncio
import logging
import time
from functools import partial
from types import SimpleNamespace

from _apps_helpers import MARKER, gmail_answer, manifest
from test_cache_refresher_multiworker import _expire_answers

INBOX = {"use": "gmail.unread_subjects", "fields": ["count", "subject"]}


def _tick(gateway, apps):
    from app.gateway.apps import refresher

    return gateway.client.portal.call(partial(refresher.tick, gateway.app.state, apps.repo, holder="worker-a"))


def _states(apps, gateway, app_id) -> dict[str, str | None]:
    return {r["source"]: r["state"] for r in apps.call(apps.repo.cache_rows, owner_id=gateway.user_id, app_id=app_id)}


def test_a_source_that_raises_does_not_stop_the_others_or_the_next_pass(gateway, composio, apps, monkeypatch, caplog) -> None:
    from app.gateway.apps import bridge

    composio.connect("GMAIL")
    composio.fake.answers["GMAIL_FETCH_EMAILS"] = gmail_answer()
    reg = apps.register(manifest(broken=INBOX, inbox=INBOX))
    apps.approve(reg.app_id)
    apps.call(apps.repo.mark_opened, owner_id=gateway.user_id, app_id=reg.app_id)

    real = bridge.fetch_and_record
    attempts: list[str] = []

    async def fetch_and_record(app_state, repo, app, name):
        attempts.append(name)
        if name == "broken":
            raise RuntimeError(f"upstream text {MARKER}")
        return await real(app_state, repo, app, name)

    monkeypatch.setattr(bridge, "fetch_and_record", fetch_and_record)
    with caplog.at_level(logging.WARNING, logger="app.gateway.apps.refresher"):
        assert _tick(gateway, apps) == 1
    assert attempts == ["broken", "inbox"], "the source after the failing one is still refreshed"
    assert _states(apps, gateway, reg.app_id)["inbox"] == "fresh"
    failures = [r.getMessage() for r in caplog.records if "broken" in r.getMessage()]
    assert failures == [f"apps refresher: app {reg.app_id} source broken failed (RuntimeError)"], failures
    assert MARKER not in caplog.text, "an error's text never reaches a log"

    # The next pass runs and tries both again.
    gateway.client.portal.call(_expire_answers)
    assert _tick(gateway, apps) == 1
    assert attempts == ["broken", "inbox", "broken", "inbox"]


def test_an_app_that_raises_does_not_stop_the_other_apps(gateway, composio, apps, monkeypatch) -> None:
    from app.gateway.apps import refresher

    composio.connect("GMAIL")
    composio.fake.answers["GMAIL_FETCH_EMAILS"] = gmail_answer()
    bad = apps.register(manifest(inbox=INBOX))
    good = apps.register(manifest(inbox=INBOX))
    for reg in (bad, good):
        apps.approve(reg.app_id)
        apps.call(apps.repo.mark_opened, owner_id=gateway.user_id, app_id=reg.app_id)

    real = refresher.served

    async def served(repo, owner_id, app_id):
        if app_id == bad.app_id:
            raise OSError("the snapshot could not be read")
        return await real(repo, owner_id, app_id)

    monkeypatch.setattr(refresher, "served", served)
    assert _tick(gateway, apps) == 1
    assert _states(apps, gateway, good.app_id) == {"inbox": "fresh"}


def test_an_unapproved_app_is_never_refreshed(gateway, composio, apps) -> None:
    composio.connect("GMAIL")
    composio.fake.answers["GMAIL_FETCH_EMAILS"] = gmail_answer()
    reg = apps.register(manifest(inbox=INBOX))
    apps.call(apps.repo.mark_opened, owner_id=gateway.user_id, app_id=reg.app_id)
    assert _tick(gateway, apps) == 0
    assert composio.fake.calls == []
    assert apps.call(apps.repo.cache_rows, owner_id=gateway.user_id, app_id=reg.app_id) == []


def test_a_failing_pass_is_retried_with_backoff_and_the_loop_recovers(monkeypatch, caplog) -> None:
    from app.gateway.apps import refresher

    monkeypatch.setattr(refresher, "TICK_S", 0.01)
    monkeypatch.setattr(refresher, "MAX_BACKOFF_S", 0.05)
    assert [refresher._backoff_s(n) for n in range(4)] == [0.01, 0.02, 0.04, 0.05]

    calls: list[float] = []

    async def tick(app_state, repo):
        calls.append(time.monotonic())
        if len(calls) <= 2:
            raise ConnectionError(f"database text {MARKER}")
        return 0

    monkeypatch.setattr(refresher, "tick", tick)

    async def run():
        task = asyncio.create_task(refresher.run_forever(SimpleNamespace(app_repo=object())))
        for _ in range(200):
            if len(calls) >= 4:
                break
            await asyncio.sleep(0.01)
        assert not task.done(), "a failing pass does not end the loop"
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    with caplog.at_level(logging.INFO, logger="app.gateway.apps.refresher"):
        asyncio.run(run())
    assert len(calls) >= 4, "the loop kept running after two failed passes"
    messages = [r.getMessage() for r in caplog.records]
    assert sum("pass failed (ConnectionError)" in m for m in messages) == 2, messages
    assert any("recovered after 2 failed" in m for m in messages), messages
    assert MARKER not in caplog.text


def test_an_unexpected_end_of_the_loop_is_logged(monkeypatch, caplog) -> None:
    from app.gateway.apps import refresher

    async def ends(app_state):
        raise SystemError("boom")

    monkeypatch.setattr(refresher, "run_forever", ends)

    async def run():
        task = refresher.start(SimpleNamespace())
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)

    with caplog.at_level(logging.ERROR, logger="app.gateway.apps.refresher"):
        asyncio.run(run())
    assert any("stopped unexpectedly (SystemError)" in r.getMessage() for r in caplog.records), caplog.text


def test_the_loop_starts_with_the_gateway_and_stops_at_shutdown(gateway, monkeypatch) -> None:
    import sys

    from app.gateway.apps import refresher

    gateway_app = sys.modules["app.gateway.app"]

    async def loops():
        return [t for t in asyncio.all_tasks() if t.get_name() == refresher.LEASE_NAME]

    running = gateway.client.portal.call(loops)
    assert len(running) == 1 and not running[0].done(), "the lifespan started the refresher"

    # Stopped by the bounded shutdown itself (before the trigger engine and
    # the database), not by the event loop going away afterwards.
    seen: list[bool] = []
    real_stop = gateway_app._stop_trigger_engine

    async def stop_trigger_engine(app):
        seen.append(running[0].done())
        await real_stop(app)

    monkeypatch.setattr(gateway_app, "_stop_trigger_engine", stop_trigger_engine)
    gateway.client.__exit__(None, None, None)
    assert seen == [True], "the shutdown stopped the refresher"


def test_opening_an_app_with_data_past_the_stale_line_reads_it_now(gateway, composio, apps) -> None:
    from sqlalchemy import update

    from omniharness.persistence.apps import AppSourceCacheRow
    from omniharness.persistence.engine import get_session_factory

    composio.connect("GMAIL")
    composio.fake.answers["GMAIL_FETCH_EMAILS"] = gmail_answer()
    reg = apps.register(manifest(inbox=INBOX))
    apps.approve(reg.app_id)
    first = gateway.client.get(f"/api/apps/{reg.app_id}/data").json()["results"]["inbox"]
    assert first["state"] == "fresh" and not first["stale"]

    two_days_ago = time.time() - 2 * 86400

    async def age():
        async with get_session_factory()() as s:
            await s.execute(update(AppSourceCacheRow).values(answered_at=two_days_ago, fetched_at=two_days_ago, attempted_at=two_days_ago))
            await s.commit()

    gateway.client.portal.call(age)
    calls = len(composio.fake.calls)
    again = gateway.client.get(f"/api/apps/{reg.app_id}/data").json()["results"]["inbox"]
    assert len(composio.fake.calls) == calls + 1, "read upstream on open"
    assert again["state"] == "fresh" and not again["stale"], again
