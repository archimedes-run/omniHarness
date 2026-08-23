"""Gateway registration (T082).

Gate 4 found that the loop was fully built and nothing started it — the
feature-level instance of the exact defect the gate exists for. Without this
module the engine is a library nobody calls.

Startup MUST NOT be able to prevent the gateway from starting. The engine is an
addition to the assistant, not a precondition for it: a trigger engine that
fails to start should cost proactive messages, not the whole product.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class EngineHandle:
    task: asyncio.Task | None = None
    loop: object | None = None
    error: str | None = None
    #: Leadership lock held while this worker runs the engine. Released on
    #: shutdown so a restarting worker can take over immediately rather than
    #: waiting for the OS to reap the old process.
    lock: object | None = None

    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    def describe(self) -> dict:
        return {"running": self.running, "error": self.error, "holds_lock": self.lock is not None}


async def start(build_loop, *, enabled: bool = True) -> EngineHandle:
    """Start the trigger loop as a background task.

    `build_loop` is a zero-arg callable returning a TriggerLoop. Injected rather
    than imported so this module has no opinion about how the loop is wired.
    """
    handle = EngineHandle()
    if not enabled:
        logger.info("trigger engine disabled by configuration")
        return handle
    try:
        loop = build_loop()
    except Exception as exc:  # noqa: BLE001 — see the module docstring
        handle.error = f"{type(exc).__name__}: {exc}"
        logger.exception("trigger engine failed to build; the gateway continues without it")
        return handle
    handle.loop = loop
    handle.task = asyncio.create_task(loop.run_forever(), name="trigger-engine")
    logger.info("trigger engine started")
    return handle


async def stop(handle: EngineHandle, *, timeout: float = 5.0) -> None:
    if handle.loop is not None:
        handle.loop.stop()
    if handle.task is not None:
        try:
            await asyncio.wait_for(handle.task, timeout=timeout)
        except (TimeoutError, asyncio.CancelledError):
            handle.task.cancel()
        except Exception:  # noqa: BLE001
            logger.exception("trigger engine raised during shutdown")
    logger.info("trigger engine stopped")
