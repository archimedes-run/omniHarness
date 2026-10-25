"""The gateway's LedgerController: the ledger tools' way in (Feature 005)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .service import LedgerError, LedgerService


@dataclass
class GatewayLedgerController:
    service: LedgerService

    def project_id(self, *, user_id: str, project: str) -> str | None:
        """The id of the user's project this name or id refers to, or None."""
        try:
            with self.service.repo.transaction() as s:
                return self.service._project(s, user_id, project, {})["id"]
        except LedgerError:
            return None

    def check_plan(self, *, user_id: str, changes: list[dict], thread_id: str | None) -> tuple[str | None, list[dict]]:
        """(why this plan could not be applied or None, what each change
        resolved to). Writes nothing (LedgerService.validate). The policy
        layer calls it before a ledger_apply plan becomes a confirmation card
        (PolicyMiddleware._check_ledger_plan): an invalid plan is refused to
        the model instead of failing after the user approved it, and a valid
        one is pinned to what it resolved to (service.PIN_KEY)."""
        try:
            return None, self.service.validate(user_id=user_id, changes=changes, thread_id=thread_id)
        except LedgerError as exc:
            return str(exc), []

    def validate(self, *, user_id: str, changes: list[dict], thread_id: str | None) -> str | None:
        """Why this plan could not be applied, or None (see check_plan)."""
        return self.check_plan(user_id=user_id, changes=changes, thread_id=thread_id)[0]

    def task(self, *, user_id: str, project: str | None, task: str) -> dict | None:
        """The user's task this reference names, as ledger_apply would resolve
        it (by id, short id, title or close title; without a project, by id or
        exact title), with its current values; None when it names none or
        more than one. The declined-stays-declined rule compares updates by
        it (grants.change_summaries)."""
        try:
            with self.service.repo.transaction() as s:
                if project not in (None, ""):
                    found = self.service._project(s, user_id, project, {})
                    row = self.service._task(s, found, task, str(project))
                else:
                    row = self.service._task_anywhere(s, user_id, task)
        except LedgerError:
            return None
        return {k: row.get(k) for k in ("id", "title", "status", "due_date", "owner")}

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
            if how == CONFIRMED:
                # Confirmed on its card: the user approved it and it did not
                # happen. That is a FAILURE the card must show, not a result
                # string that reads as "executed" (review round 3).
                raise RuntimeError(f"Nothing was changed: {exc}.") from exc
            return f"Nothing was changed: {exc}."
        mark_committed()  # the transaction committed: this write happened
        from app.gateway.display_safe import model_line

        # The tool's result: the MODEL reads it, so links stay real (a
        # defanged one was copied into answers as hxxps://a[.]example). Each
        # line is still one line with no control or bidi characters, so
        # content cannot start a line of its own. The chat's ledger step
        # defangs it on display (ledger-write-step.tsx, safeField).
        text = " ".join(model_line(line) for line in done)
        return f"{text} [undo {write_id}]" if write_id else text
