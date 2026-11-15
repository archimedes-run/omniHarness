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
"""

from __future__ import annotations

import asyncio
import contextvars
import functools
from collections.abc import Callable
from typing import Any

_UNSET = object()


async def call_off_loop[T](fn: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """``fn(*args, **kwargs)`` in a worker thread, keeping its context changes."""
    context = contextvars.copy_context()
    try:
        result = await asyncio.get_running_loop().run_in_executor(None, functools.partial(context.run, fn, *args, **kwargs))
    except Exception:
        # Raised (not cancelled: then the thread may still be running, and its
        # half-made changes are not kept): what it set before raising stays
        # set, as it would inline.
        _adopt(context)
        raise
    _adopt(context)
    return result


def _adopt(context: contextvars.Context) -> None:
    """Set, in the current context, every variable `context` holds differently."""
    for var, value in context.items():
        if var.get(_UNSET) is not value:
            var.set(value)
