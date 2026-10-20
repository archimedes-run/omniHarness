"""LedgerController port: how the harness's ledger tools reach the Project Ledger.

The ledger lives in the gateway (app/ledger). The harness must not import it,
so the gateway registers an implementation here at startup, exactly as it does
for the MCP build and preview controllers. The tools exist only when one is
registered.

Both methods are SYNCHRONOUS: a confirmed Tier 3 tool is run with a sync
`tool.invoke` from inside the running event loop (see
omniharness/persistence/ledger/sql.py).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LedgerController(Protocol):
    def read(self, *, user_id: str, project: str | None) -> str:
        """The ledger, or one project, as text the model can read."""
        ...

    def apply(self, *, user_id: str, changes: list[dict], thread_id: str | None) -> str:
        """Apply confirmed changes in one transaction; say what was done."""
        ...


_controller: LedgerController | None = None


def get_ledger_controller() -> LedgerController | None:
    return _controller


def set_ledger_controller(controller: LedgerController | None) -> None:
    global _controller
    _controller = controller
