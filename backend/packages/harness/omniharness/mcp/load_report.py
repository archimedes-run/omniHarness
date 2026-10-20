"""What happened when each MCP server's tools were last loaded (FR-040, FR-041).

The loader catches a failing server, logs "Skipping MCP server '<name>'", and
carries on; the only downstream symptom was an agent that behaved as though the
feature did not exist. This keeps the outcome, per server, where a surface can
read it: loaded with N tools, or failed with the reason.

Per process: under several gateway workers each reports its own last load.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class ServerLoad:
    name: str
    loaded: bool
    tool_count: int
    error: str | None
    at: datetime
    #: The names the tools were registered under (prefixed), so a surface can
    #: say which of them the policy refuses for want of a rule (007).
    tool_names: tuple[str, ...] = ()


_LAST: dict[str, ServerLoad] = {}


def record_loaded(name: str, tool_count: int, tool_names: tuple[str, ...] | list[str] = ()) -> None:
    _LAST[name] = ServerLoad(name=name, loaded=True, tool_count=tool_count, error=None, at=datetime.now(UTC), tool_names=tuple(tool_names))


def record_failed(name: str, error: BaseException) -> None:
    # The single exception inside a task group, not "unhandled errors in a
    # TaskGroup (1 sub-exception)" — the operator needs the cause.
    while isinstance(error, BaseExceptionGroup) and len(error.exceptions) == 1:
        error = error.exceptions[0]
    _LAST[name] = ServerLoad(name=name, loaded=False, tool_count=0, error=f"{type(error).__name__}: {error}", at=datetime.now(UTC))


def last_loads() -> dict[str, ServerLoad]:
    return dict(_LAST)
