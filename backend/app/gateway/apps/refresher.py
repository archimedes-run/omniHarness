"""The in-gateway refresher (Spec 011 FR-014).

Keeps the sources of apps opened in the last 24 h warm: each source is
refreshed every `refresh_s` (default 300 s, 60 to 3600). Every worker runs the
loop; only the holder of the lease in the shared store does any work, so one
worker refreshes at a time. Each refresh also claims the source's upstream slot
(one call per source per 60 s), shared with the bridge, so a request and the
refresher never both call upstream.

Not the trigger engine: that starts agent runs, and app data must never reach
one. A revoked app has no active grant: its sources are skipped (and its cache
rows are gone), so its refreshes stop on the next tick.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from datetime import UTC, datetime

from app.gateway.apps import bridge, catalog
from app.gateway.apps.service import AppNotFound, load_app

logger = logging.getLogger(__name__)

LEASE_NAME = "apps-refresher"
#: Seconds between ticks; the lease outlives two missed ticks.
TICK_S = 15.0
LEASE_TTL_S = 45.0
OPENED_WITHIN_S = 24 * 3600

#: This process's name on the lease.
HOLDER = secrets.token_hex(8)


async def tick(app_state, repo, *, holder: str = HOLDER) -> int:
    """One pass. Returns how many sources it refreshed (0 without the lease)."""
    if not await repo.acquire_lease(name=LEASE_NAME, holder=holder, ttl_s=LEASE_TTL_S):
        return 0
    refreshed = 0
    now = time.time()
    for owner_id, app_id in await repo.opened_since(now - OPENED_WITHIN_S):
        try:
            app = load_app(owner_id, app_id)
        except AppNotFound:
            continue
        if not await repo.active_grant(owner_id=owner_id, app_id=app_id, manifest_hash=app.manifest_hash):
            continue
        for name, spec in app.sources.items():
            row = await repo.cache_row(owner_id=owner_id, app_id=app_id, source=name, manifest_hash=app.manifest_hash)
            answered = row.get("answered_at") if row else None
            if answered is not None and now - answered < spec["refresh_s"]:
                continue
            if bridge.refusal(app_state, catalog.get_entry(spec["use"]), spec["params"], datetime.now(UTC)) is not None:
                continue
            if not await repo.claim_upstream(owner_id=owner_id, app_id=app_id, source=name, manifest_hash=app.manifest_hash, min_interval_s=bridge.UPSTREAM_MIN_INTERVAL_S):
                continue
            await bridge.fetch_and_record(app_state, repo, app, name)
            refreshed += 1
    return refreshed


async def run_forever(app_state) -> None:
    """Started in the gateway lifespan; cancelled at shutdown."""
    while True:
        await asyncio.sleep(TICK_S)
        repo = getattr(app_state, "app_repo", None)
        if repo is None:
            continue
        try:
            await tick(app_state, repo)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - one bad pass must not end the loop
            logger.warning("apps refresher pass failed", exc_info=True)


async def stop(task: asyncio.Task | None, *, timeout: float) -> None:
    """Cancel the refresher loop and every background bridge refresh, and wait
    for them to finish (bounded): none of them may still be inside a database
    session when the engine closes. Results and errors are ignored."""
    tasks = [t for t in (task, *bridge.background_tasks()) if t is not None and not t.done()]
    for t in tasks:
        t.cancel()
    if tasks:
        await asyncio.wait(tasks, timeout=timeout)
