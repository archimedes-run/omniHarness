"""SQLAlchemy-backed WorkflowRunRepository with status state machine."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omniharness.persistence.workflow_runs.model import WorkflowRunRow

# ---------------------------------------------------------------------------
# Status state machine
# ---------------------------------------------------------------------------

#: Legal transitions for WorkflowRun.status.
#: waiting_approval is reserved for Phase 6; no outgoing transitions defined yet.
_LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"running", "canceled"}),
    "running": frozenset({"succeeded", "failed", "canceled", "expired"}),
    "waiting_approval": frozenset(),  # Phase 6 — reserved, no transitions yet
    "succeeded": frozenset(),
    "failed": frozenset(),
    "canceled": frozenset(),
    "expired": frozenset(),
}

#: Terminal statuses — completed_at is set when entering one of these.
_TERMINAL_STATUSES: frozenset[str] = frozenset({"succeeded", "failed", "canceled", "expired"})


class IllegalStatusTransition(Exception):
    """Raised when a requested WorkflowRun status transition is not permitted."""


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class WorkflowRunRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def create_or_get_by_key(
        self,
        *,
        workflow_id: str,
        idempotency_key: str,
        id: str,
        trigger_type: str = "manual",
        trigger_payload: dict | None = None,
        initiated_by: str | None = None,
    ) -> tuple[dict, bool]:
        """Return (run_dict, created).

        If a WorkflowRun with this idempotency_key already exists, return it
        (created=False) without creating a duplicate.  Otherwise insert and
        return the new row (created=True).

        For manual runs the caller should supply a unique per-invocation token
        so manual runs never deduplicate.  For scheduled/event runs the caller
        supplies compute_idempotency_key(...) so identical triggers deduplicate.
        """
        # Fast path: check for existing run first.
        async with self._sf() as session:
            stmt = select(WorkflowRunRow).where(WorkflowRunRow.idempotency_key == idempotency_key)
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing is not None:
                return existing.to_dict(), False

        # Slow path: insert; handle race via IntegrityError on unique constraint.
        now = datetime.now(UTC)
        row = WorkflowRunRow(
            id=id,
            workflow_id=workflow_id,
            trigger_type=trigger_type,
            trigger_payload=trigger_payload or {},
            status="queued",
            idempotency_key=idempotency_key,
            initiated_by=initiated_by,
            created_at=now,
            updated_at=now,
        )
        try:
            async with self._sf() as session:
                session.add(row)
                await session.commit()
                await session.refresh(row)
                return row.to_dict(), True
        except IntegrityError:
            # Another writer raced and inserted the same key.
            async with self._sf() as session:
                stmt = select(WorkflowRunRow).where(WorkflowRunRow.idempotency_key == idempotency_key)
                existing = (await session.execute(stmt)).scalar_one_or_none()
                if existing is not None:
                    return existing.to_dict(), False
            raise  # unexpected — re-raise if we still can't find it

    async def get(self, id: str) -> dict | None:
        async with self._sf() as session:
            row = await session.get(WorkflowRunRow, id)
            return row.to_dict() if row else None

    async def list_by_workflow(self, workflow_id: str, *, limit: int = 100) -> list[dict]:
        stmt = select(WorkflowRunRow).where(WorkflowRunRow.workflow_id == workflow_id).order_by(WorkflowRunRow.created_at.desc()).limit(limit)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [r.to_dict() for r in result.scalars()]

    async def transition_status(self, run_id: str, new_status: str) -> dict:
        """Transition a WorkflowRun to new_status, enforcing legal transitions.

        Raises:
            ValueError: if the run does not exist.
            IllegalStatusTransition: if the transition is not permitted.
        """
        async with self._sf() as session:
            row = await session.get(WorkflowRunRow, run_id)
            if row is None:
                raise ValueError(f"WorkflowRun {run_id!r} not found")
            current = row.status
            if new_status not in _LEGAL_TRANSITIONS.get(current, frozenset()):
                raise IllegalStatusTransition(f"Cannot transition WorkflowRun from {current!r} to {new_status!r}")
            row.status = new_status
            now = datetime.now(UTC)
            row.updated_at = now
            if new_status == "running" and row.started_at is None:
                row.started_at = now
            if new_status in _TERMINAL_STATUSES:
                row.completed_at = now
            await session.commit()
            await session.refresh(row)
            return row.to_dict()

    async def cancel(self, run_id: str) -> dict:
        """Convenience: cancel a queued or running WorkflowRun."""
        return await self.transition_status(run_id, "canceled")
