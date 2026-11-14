"""The gateway's shutdown: one deadline, the data closes reserved, nothing left behind to hang the process (issue #192).

A worker's exit or a reload runs the lifespan's shutdown steps in order: the
stoppable services first (the trigger engine, the channel service, the sweeps,
...), then the data closes (the database engine, the store, the checkpointer,
the stream bridge). Any step can wait on something outside the gateway's
control: a database connection whose worker thread has died never answers.

* ONE DEADLINE (``OMNI_HARNESS_SHUTDOWN_DEADLINE_SECONDS``, default 25 s) for
  the whole shutdown, inside the container's stop grace period (30 s, set in
  the compose files): the process ends on its own before SIGKILL.
* THE DATA CLOSES ARE RESERVED their share
  (``OMNI_HARNESS_SHUTDOWN_DATA_RESERVE_SECONDS``, default 10 s): a service step
  is bounded by the time left minus the reserve, so stalled services can never
  eat the time the database needs to close. Each step also has its own bound
  (``OMNI_HARNESS_SHUTDOWN_STEP_SECONDS``, default 5 s).
* A STEP PAST ITS BOUND IS ABANDONED: cancelled, logged, left behind. Not
  asyncio.wait_for, which waits for the cancelled step to finish (aiosqlite's
  close awaits its stop in a finally, on the same dead thread).
* NOTHING ABANDONED HOLDS THE PROCESS: the last step cancels the abandoned
  steps again and waits for them within what is left; any still pending is
  then DETACHED from the loop's task registry, so the loop's own close
  (asyncio.run, as uvicorn runs it, cancels every remaining task and waits
  with no limit) cannot wait on it forever. Detaching is chosen over a hard
  process exit: it runs only after every data close has had its bound, kills
  nothing, skips no atexit handler or log flush, and leaves only a suspended
  coroutine that is never resumed.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


def _env_seconds(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        logger.warning("%s is not a number of seconds; using %.0f", name, default)
        return default


#: The data steps (marking in-flight runs interrupted, the database engine,
#: the store, the checkpointer, the stream bridge): each gets a fair share of
#: what is left for them.
DATA_STEPS = 5
#: A data close always gets at least this long, even if the deadline passed.
MIN_DATA_STEP_SECONDS = 0.25
#: The last step (the abandoned steps' second cancel) gets at least this long.
MIN_FINISH_SECONDS = 0.5


@dataclass
class _Shutdown:
    deadline: float | None = None
    data_left: int = DATA_STEPS
    #: (what, task) for every step abandoned past its bound.
    abandoned: list[tuple[str, asyncio.Task]] = field(default_factory=list)
    #: Tasks detached from the loop: held so they are never collected mid-await.
    detached: list[asyncio.Task] = field(default_factory=list)


_state = _Shutdown()


def deadline_seconds() -> float:
    return _env_seconds("OMNI_HARNESS_SHUTDOWN_DEADLINE_SECONDS", 25.0)


def data_reserve_seconds() -> float:
    return _env_seconds("OMNI_HARNESS_SHUTDOWN_DATA_RESERVE_SECONDS", 10.0)


def step_seconds() -> float:
    return _env_seconds("OMNI_HARNESS_SHUTDOWN_STEP_SECONDS", 5.0)


def begin() -> None:
    """Start the shutdown's clock (the first thing the lifespan does after its yield)."""
    global _state
    _state = _Shutdown(deadline=asyncio.get_running_loop().time() + deadline_seconds())


def _remaining() -> float:
    if _state.deadline is None:
        begin()
    return _state.deadline - asyncio.get_running_loop().time()


def service_bound(per_step: float | None = None) -> float:
    """A stoppable service's bound: its own, never into the data closes' reserve."""
    own = step_seconds() if per_step is None else per_step
    return max(0.0, min(own, _remaining() - data_reserve_seconds()))


def data_bound() -> float:
    """A data close's bound: a fair share of what is left for the data closes."""
    share = _remaining() / max(1, _state.data_left)
    _state.data_left = max(0, _state.data_left - 1)
    return max(MIN_DATA_STEP_SECONDS, min(step_seconds(), share))


async def step(work: Any, what: str, bound: float) -> bool:
    """Run one step for at most ``bound`` seconds; True if it finished.

    Past the bound the step is cancelled, recorded as abandoned (``finish``
    deals with it) and the shutdown carries on.
    """
    task = asyncio.ensure_future(work)
    done, _ = await asyncio.wait({task}, timeout=bound)
    if not done:
        task.cancel()
        task.add_done_callback(lambda t: t.cancelled() or t.exception())
        _state.abandoned.append((what, task))
        logger.warning("Shutdown: %s exceeded %.1fs; proceeding without it.", what, bound)
        return False
    if not task.cancelled() and task.exception() is not None:
        logger.warning("Shutdown: %s failed: %r", what, task.exception())
    return True


async def service_step(work: Any, what: str, per_step: float | None = None) -> bool:
    return await step(work, what, service_bound(per_step))


async def data_step(work: Any, what: str) -> bool:
    return await step(work, what, data_bound())


def _detach(task: asyncio.Task) -> None:
    """Take a task out of the loop's registry: the loop's close no longer waits on it."""
    unregister = getattr(asyncio.tasks, "_unregister_task", None)
    if unregister is None:  # pragma: no cover - a Python without it
        logger.error("Shutdown: cannot detach %r; the process may wait on it at exit", task)
        return
    unregister(task)
    _state.detached.append(task)


async def finish() -> list[str]:
    """The last step: cancel the abandoned steps again, wait within what is
    left, detach whatever still has not stopped. Returns what was detached."""
    pending = [(what, task) for what, task in _state.abandoned if not task.done()]
    if pending:
        for _what, task in pending:
            task.cancel()
        bound = max(MIN_FINISH_SECONDS, min(step_seconds(), _remaining()))
        await asyncio.wait([task for _what, task in pending], timeout=bound)
    stuck = [(what, task) for what, task in pending if not task.done()]
    for _what, task in stuck:
        _detach(task)
    if _state.abandoned:
        logger.warning(
            "Shutdown: %d step(s) did not stop within their bound: %s%s",
            len(_state.abandoned),
            ", ".join(what for what, _task in _state.abandoned),
            f"; still running after a second cancel and detached: {', '.join(what for what, _task in stuck)}" if stuck else "",
        )
    return [what for what, _task in stuck]


def abandoned() -> list[str]:
    """What this shutdown abandoned so far (for tests and the summary)."""
    return [what for what, _task in _state.abandoned]
