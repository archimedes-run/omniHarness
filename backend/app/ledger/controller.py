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
        from app.policy.provenance import CONFIRMED, GRANTED, current_execution

        # Who made it, truthfully: a confirmed plan, a Tier 2 write the reply
        # disclosed, or a write under a standing grant in a scheduled run.
        how = current_execution()
        actor = "assistant_confirmed" if how == CONFIRMED else ("assistant_granted" if how == GRANTED else "assistant_disclosed")
        try:
            done = self.service.apply(user_id=user_id, changes=changes, thread_id=thread_id, actor=actor)
        except LedgerError as exc:
            # Nothing was written: apply validates and writes in one transaction.
            return f"Nothing was changed: {exc}."
        return " ".join(done)
