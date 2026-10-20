"""The run history in the gateway: opened at startup, purged on a schedule."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.run_history.store import RunHistory

logger = logging.getLogger(__name__)

#: How often the retention purge runs while the gateway is up.
PURGE_INTERVAL_SECONDS = 3600


def open_history(base_dir: Path) -> RunHistory:
    """The gateway's run history, under its data dir, purged once now."""
    history = RunHistory(base_dir / "run-history")
    try:
        n = history.purge()
        if n:
            logger.info("run history: purged %d run(s) past retention", n)
    except Exception:
        logger.exception("run history: the startup purge failed")
    return history


async def purge_forever(history: RunHistory, interval: float = PURGE_INTERVAL_SECONDS) -> None:
    """The retention job: purge, sleep, repeat, until cancelled."""
    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.to_thread(history.purge)
        except Exception:
            logger.exception("run history: a scheduled purge failed")
