"""The gateway's LedgerController: the ledger tools' way in (Feature 005)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .service import LedgerError, LedgerService


@dataclass
class GatewayLedgerController:
    service: LedgerService

    def read(self, *, user_id: str, project: str | None) -> str:
        return self.service.read_text(user_id=user_id, project=project, today=date.today())

    def apply(self, *, user_id: str, changes: list[dict], thread_id: str | None) -> str:
        from app.policy.provenance import CONFIRMED, GRANTED, current_execution, current_write_id, mark_committed

        # Who made it, truthfully: a confirmed plan, a Tier 2 write the reply
        # disclosed, or a write under a standing grant in a scheduled run.
        how = current_execution()
        actor = "assistant_confirmed" if how == CONFIRMED else ("assistant_granted" if how == GRANTED else "assistant_disclosed")
        # A write with a write id (unconfirmed, or a confirmed "Apply all"
        # batch) is undoable: its changes carry the id, and the result names
        # it for the disclosure's Undo.
        write_id = current_write_id()
        try:
            done = self.service.apply(user_id=user_id, changes=changes, thread_id=thread_id, actor=actor, pending_action_id=write_id)
        except LedgerError as exc:
            # Nothing was written: apply validates and writes in one transaction.
            return f"Nothing was changed: {exc}."
        mark_committed()  # the transaction committed: this write happened
        text = " ".join(done)
        return f"{text} [undo {write_id}]" if write_id else text
