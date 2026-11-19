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
from app.gateway.apps.service import AppNotFound, served

logger = logging.getLogger(__name__)

LEASE_NAME = "apps-refresher"
#: Seconds between ticks; the lease outlives two missed ticks.
TICK_S = 15.0
LEASE_TTL_S = 45.0
OPENED_WITHIN_S = 24 * 3600
#: The longest wait between passes while passes keep failing.
MAX_BACKOFF_S = 300.0

#: This process's name on the lease.
HOLDER = secrets.token_hex(8)


async def tick(app_state, repo, *, holder: str = HOLDER) -> int:
    """One pass. Returns how many sources it refreshed (0 without the lease).

    One app or one source failing never ends the pass: it is logged once (by
    type or by its fixed, user-facing reason: never upstream text), only that
    source keeps its last answer (shown stale), and the others are refreshed.
    """
    if not await repo.acquire_lease(name=LEASE_NAME, holder=holder, ttl_s=LEASE_TTL_S):
        return 0
    refreshed = 0
    now = time.time()
    for owner_id, app_id in await repo.opened_since(now - OPENED_WITHIN_S):
        try:
            app = await served(repo, owner_id, app_id)
            if not await repo.active_grant(owner_id=owner_id, app_id=app_id, manifest_hash=app.manifest_hash):
                continue
        except AppNotFound:
            continue
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - one app must not stop the others
            logger.warning("apps refresher: app %s could not be read (%s)", app_id, type(exc).__name__)
            continue
        for name in app.sources:
            try:
                if await _refresh_source(app_state, repo, app, name, now):
                    refreshed += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - one source must not stop the others
                logger.warning("apps refresher: app %s source %s failed (%s)", app_id, name, type(exc).__name__)
    return refreshed


async def _refresh_source(app_state, repo, app, name: str, now: float) -> bool:
    """Refresh one source if it is due. True when upstream was called."""
    spec = app.sources[name]
    row = await repo.cache_row(owner_id=app.owner_id, app_id=app.app_id, source=name, manifest_hash=app.manifest_hash)
    answered = row.get("answered_at") if row else None
    if answered is not None and now - answered < spec["refresh_s"]:
        return False
    if bridge.refusal(app_state, catalog.get_entry(spec["use"]), spec["params"], datetime.now(UTC)) is not None:
        return False
    if not await repo.claim_upstream(owner_id=app.owner_id, app_id=app.app_id, source=name, manifest_hash=app.manifest_hash, min_interval_s=bridge.UPSTREAM_MIN_INTERVAL_S):
        return False
    state, reason = await bridge.fetch_and_record(app_state, repo, app, name)
    if state == "failed":
        # The reason is the fixed wording the tile shows, never upstream text.
        logger.warning("apps refresher: app %s source %s failed: %s", app.app_id, name, reason or "no reason")
    return True


def _backoff_s(failures: int) -> float:
    """Seconds before the next pass: TICK_S, doubled per consecutive failure, capped."""
    return min(TICK_S * (2 ** min(failures, 8)), MAX_BACKOFF_S)


async def run_forever(app_state) -> None:
    """Started in the gateway lifespan (start()); cancelled at shutdown.

    Whatever a pass raises, the loop goes on: the failure is logged by type
    and the next pass waits longer (exponential backoff, capped), so a store
    that keeps failing is not hammered and the loop is never silently dead.
    """
    failures = 0
    while True:
        await asyncio.sleep(_backoff_s(failures))
        try:
            repo = getattr(app_state, "app_repo", None)
            if repo is None:
                continue
            await tick(app_state, repo)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - one bad pass must not end the loop
            failures += 1
            # The type only: an error's text or traceback can carry a row's data.
            logger.warning("apps refresher pass failed (%s); next pass in %d s", type(exc).__name__, int(_backoff_s(failures)))
            continue
        if failures:
            logger.info("apps refresher recovered after %d failed pass(es)", failures)
        failures = 0


def _on_done(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    logger.error("apps refresher stopped unexpectedly (%s): app data will not refresh until the gateway restarts", type(exc).__name__ if exc else "returned")


def start(app_state) -> asyncio.Task:
    """Start the loop (every gateway start, every worker). An end other than
    the shutdown's cancel is logged, never silent."""
    task = asyncio.create_task(run_forever(app_state), name=LEASE_NAME)
    task.add_done_callback(_on_done)
    return task


async def stop(task: asyncio.Task | None, *, timeout: float) -> None:
    """Cancel the refresher loop and every background bridge refresh, and wait
    for them to finish (bounded): none of them may still be inside a database
    session when the engine closes. Results and errors are ignored."""
    tasks = [t for t in (task, *bridge.background_tasks()) if t is not None and not t.done()]
    for t in tasks:
        t.cancel()
    if tasks:
        await asyncio.wait(tasks, timeout=timeout)
