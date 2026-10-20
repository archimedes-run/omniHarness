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


async def load_known_secrets(app) -> None:
    """Register every secret value the gateway can load, for the run history's
    exact-match redaction. Logs counts per source, never values. Never raises."""
    from omniharness.utils.known_secrets import load_process_secrets

    try:
        counts = await asyncio.to_thread(load_process_secrets)
        # The internal auth token is a credential too (it lets a caller act as
        # the system): never in a stored run.
        from app.gateway import internal_auth
        from omniharness.utils.known_secrets import register_secret

        register_secret(internal_auth._INTERNAL_AUTH_TOKEN, "internal-auth")
        # And the trigger engine's credential derived from it.
        register_secret(internal_auth._trigger_engine_token(), "internal-auth")
        counts["internal-auth"] = 2
        vault = getattr(app.state, "mcp_secrets_vault", None)
        if vault is not None:
            counts["mcp-vault"] = await vault.register_known_secrets()
        logger.info("run history: exact-match redaction knows %s", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    except Exception:
        logger.exception("run history: loading known secret values failed; only pattern redaction applies")


async def purge_forever(history: RunHistory, interval: float = PURGE_INTERVAL_SECONDS, *, app=None) -> None:
    """The retention job: purge, then sweep the threads retention orphaned (and
    retry failed thread deletes), sleep, repeat, until cancelled."""
    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.to_thread(history.purge)
            if app is not None:
                from app.run_history.delete import sweep_threads

                await sweep_threads(app)
        except Exception:
            logger.exception("run history: a scheduled purge failed")
