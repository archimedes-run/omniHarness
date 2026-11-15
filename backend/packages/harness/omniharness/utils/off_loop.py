"""Run a synchronous tool assembly off the event loop, as if it ran inline.

Tool assembly (``get_available_tools`` and what calls it) is synchronous and
can wait a long time: connector toolkits start a process each and list their
tools over it. Called from a coroutine on the gateway's event loop, that wait
blocked every request the process serves (a page open froze the gateway for
about 75 seconds while one toolkit listed nothing).

``call_off_loop`` runs the call in a worker thread instead, in a copy of the
caller's context, and then applies to the caller's context every context
variable the call set. Assembly sets some that the caller reads afterwards
(the deferred-tool registry ``tool_search`` uses, for one), so the result is
the same as calling inline: only the thread differs.

Assembly has its own small pool, never the loop's default one: that pool also
serves the run journal's batch writes, card statements, password hashing and
DNS lookups, which must not queue behind toolkits starting up.

A cancelled caller stops waiting at once and the thread's result is dropped:
building tools has no side effect that must finish, and a stop or restart
must not wait for a toolkit that is not answering.
"""

from __future__ import annotations

import asyncio
import contextvars
import functools
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

#: Threads for tool assembly. Identical tools-count requests share one
#: assembly (routers/thread_tools), so a few page opens do not fill it.
ASSEMBLY_WORKERS = 6
_ASSEMBLY_POOL = ThreadPoolExecutor(max_workers=ASSEMBLY_WORKERS, thread_name_prefix="tool-assembly")

_UNSET = object()


async def call_off_loop[T](fn: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """``fn(*args, **kwargs)`` in the assembly pool, keeping its context changes."""
    context = contextvars.copy_context()
    try:
        result = await asyncio.get_running_loop().run_in_executor(_ASSEMBLY_POOL, functools.partial(context.run, fn, *args, **kwargs))
    except Exception:
        # Raised (not cancelled: then the thread may still be running, and
        # nothing of it is kept): what it set before raising stays set, as it
        # would inline.
        _adopt(context)
        raise
    _adopt(context)
    return result


def _adopt(context: contextvars.Context) -> None:
    """Set, in the current context, every variable `context` holds differently."""
    for var, value in context.items():
        if var.get(_UNSET) is not value:
            var.set(value)
