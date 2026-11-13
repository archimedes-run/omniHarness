"""The shared cache and the refresher across workers (Spec 011 FR-014, FR-015).

Two repositories on two engines over ONE database file stand for two workers:
only one holds the refresher's lease, and only one of two concurrent requests
calls upstream.
"""

from __future__ import annotations

import asyncio
import time
from functools import partial

from _apps_helpers import gmail_answer, manifest

INBOX = {"use": "gmail.unread_subjects", "fields": ["count", "subject"]}


async def _two_repos(path):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    import omniharness.persistence.models  # noqa: F401 - register every table
    from omniharness.persistence.apps import AppRepository
    from omniharness.persistence.base import Base

    engines = [create_async_engine(f"sqlite+aiosqlite:///{path}") for _ in range(2)]
    async with engines[0].begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engines, [AppRepository(async_sessionmaker(e, expire_on_commit=False)) for e in engines]


def test_one_lease_holder_across_workers(tmp_path) -> None:
    async def run():
        engines, (a, b) = await _two_repos(tmp_path / "shared.db")
        try:
            assert await a.acquire_lease(name="apps-refresher", holder="worker-a", ttl_s=30)
            assert not await b.acquire_lease(name="apps-refresher", holder="worker-b", ttl_s=30)
            assert await a.acquire_lease(name="apps-refresher", holder="worker-a", ttl_s=30), "the holder renews"
            assert await a.acquire_lease(name="other", holder="worker-a", ttl_s=-1)
            assert await b.acquire_lease(name="other", holder="worker-b", ttl_s=30), "an expired lease is taken over"
        finally:
            for e in engines:
                await e.dispose()

    asyncio.run(run())


def test_one_upstream_claim_across_workers(tmp_path) -> None:
    async def run():
        engines, (a, b) = await _two_repos(tmp_path / "shared.db")
        key = {"owner_id": "o", "app_id": "today", "source": "inbox", "manifest_hash": "h" * 64, "min_interval_s": 60}
        try:
            results = await asyncio.gather(*(r.claim_upstream(**key) for r in (a, b, a, b)))
            assert sorted(results) == [False, False, False, True]
        finally:
            for e in engines:
                await e.dispose()

    asyncio.run(run())


def test_rate_counter_is_shared_across_workers(tmp_path) -> None:
    async def run():
        engines, (a, b) = await _two_repos(tmp_path / "shared.db")
        try:
            counts = [await (a if i % 2 else b).hit(owner_id="o", app_id="today") for i in range(6)]
            assert counts == [1, 2, 3, 4, 5, 6]
        finally:
            for e in engines:
                await e.dispose()

    asyncio.run(run())


def test_concurrent_first_reads_call_upstream_once(gateway, composio, apps) -> None:
    from app.gateway.apps import bridge
    from app.gateway.apps.service import load_app

    composio.connect("GMAIL")
    composio.fake.answers["GMAIL_FETCH_EMAILS"] = gmail_answer()
    reg = apps.register(manifest(inbox=INBOX))
    apps.approve(reg.app_id)
    app = load_app(gateway.user_id, reg.app_id)

    async def both():
        return await asyncio.gather(*(bridge.serve(gateway.app.state, apps.repo, app, "inbox") for _ in range(4)))

    results = gateway.client.portal.call(both)
    assert [r["state"] for r in results] == ["fresh"] * 4
    assert composio.fake.slugs() == ["GMAIL_FETCH_EMAILS"]


def test_refresher_refreshes_opened_granted_apps_and_stops_on_revoke(gateway, composio, apps) -> None:
    from app.gateway.apps import refresher

    composio.connect("GMAIL")
    composio.fake.answers["GMAIL_FETCH_EMAILS"] = gmail_answer()
    reg = apps.register(manifest(inbox=INBOX))
    unopened = apps.register(manifest(inbox=INBOX))
    apps.approve(reg.app_id)
    apps.approve(unopened.app_id)
    tick = partial(refresher.tick, gateway.app.state, apps.repo, holder="worker-a")

    assert gateway.client.portal.call(tick) == 0, "nothing opened yet"
    apps.call(apps.repo.mark_opened, owner_id=gateway.user_id, app_id=reg.app_id)
    assert gateway.client.portal.call(tick) == 1
    rows = apps.call(apps.repo.cache_rows, owner_id=gateway.user_id, app_id=reg.app_id)
    assert rows[0]["state"] == "fresh" and rows[0]["data"]
    assert apps.call(apps.repo.cache_rows, owner_id=gateway.user_id, app_id=unopened.app_id) == []
    assert gateway.client.portal.call(tick) == 0, "fresh within refresh_s"
    assert gateway.client.portal.call(partial(refresher.tick, gateway.app.state, apps.repo, holder="worker-b")) == 0, "another worker has no lease"

    gateway.client.post(f"/api/apps/{reg.app_id}/revoke")
    calls = len(composio.fake.calls)
    gateway.client.portal.call(_expire_answers)
    assert gateway.client.portal.call(tick) == 0
    assert len(composio.fake.calls) == calls and apps.call(apps.repo.cache_rows, owner_id=gateway.user_id, app_id=reg.app_id) == []


def test_refresher_skips_apps_not_opened_in_24_hours(gateway, composio, apps) -> None:
    from app.gateway.apps import refresher

    composio.connect("GMAIL")
    reg = apps.register(manifest(inbox=INBOX))
    apps.approve(reg.app_id)
    apps.call(apps.repo.mark_opened, owner_id=gateway.user_id, app_id=reg.app_id)
    gateway.client.portal.call(partial(_set_opened, reg.app_id, time.time() - 25 * 3600))
    assert gateway.client.portal.call(partial(refresher.tick, gateway.app.state, apps.repo, holder="w")) == 0
    assert composio.fake.calls == []


def test_a_revoke_during_a_fetch_stores_nothing(gateway, composio, apps) -> None:
    """The in-flight answer finds its row gone: the cache is not resurrected."""
    from app.gateway.apps import bridge
    from app.gateway.apps.service import load_app

    composio.connect("GMAIL")
    reg = apps.register(manifest(inbox=INBOX))
    apps.approve(reg.app_id)
    app = load_app(gateway.user_id, reg.app_id)

    composio.fake.answers["GMAIL_FETCH_EMAILS"] = gmail_answer()
    key = {"owner_id": gateway.user_id, "app_id": reg.app_id, "source": "inbox", "manifest_hash": app.manifest_hash}
    assert apps.call(apps.repo.claim_upstream, **key, min_interval_s=60)
    apps.call(apps.repo.delete_cache, owner_id=gateway.user_id, app_id=reg.app_id)
    gateway.client.portal.call(partial(bridge.fetch_and_record, gateway.app.state, apps.repo, app, "inbox"))
    assert apps.call(apps.repo.cache_rows, owner_id=gateway.user_id, app_id=reg.app_id) == []


async def _expire_answers():
    from sqlalchemy import update

    from omniharness.persistence.apps import AppSourceCacheRow
    from omniharness.persistence.engine import get_session_factory

    async with get_session_factory()() as s:
        await s.execute(update(AppSourceCacheRow).values(answered_at=0, attempted_at=0))
        await s.commit()


async def _set_opened(app_id, at):
    from sqlalchemy import update

    from omniharness.persistence.apps import AppOpenRow
    from omniharness.persistence.engine import get_session_factory

    async with get_session_factory()() as s:
        await s.execute(update(AppOpenRow).where(AppOpenRow.app_id == app_id).values(opened_at=at))
        await s.commit()
