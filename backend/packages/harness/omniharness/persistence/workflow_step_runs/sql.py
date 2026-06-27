"""SQLAlchemy-backed WorkflowStepRunRepository."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omniharness.persistence.workflow_step_runs.model import WorkflowStepRunRow


class WorkflowStepRunRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def create(
        self,
        *,
        id: str,
        workflow_run_id: str,
        step_key: str,
        step_index: int = 0,
    ) -> dict:
        now = datetime.now(UTC)
        row = WorkflowStepRunRow(
            id=id,
            workflow_run_id=workflow_run_id,
            step_key=step_key,
            step_index=step_index,
            status="queued",
            created_at=now,
            updated_at=now,
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row.to_dict()

    async def list_by_run(self, workflow_run_id: str) -> list[dict]:
        stmt = select(WorkflowStepRunRow).where(WorkflowStepRunRow.workflow_run_id == workflow_run_id).order_by(WorkflowStepRunRow.step_index.asc())
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [r.to_dict() for r in result.scalars()]

    async def update_status(
        self,
        id: str,
        new_status: str,
        *,
        error_summary: str | None = None,
    ) -> dict | None:
        async with self._sf() as session:
            row = await session.get(WorkflowStepRunRow, id)
            if row is None:
                return None
            row.status = new_status
            now = datetime.now(UTC)
            row.updated_at = now
            if new_status == "running" and row.started_at is None:
                row.started_at = now
            if new_status in {"succeeded", "failed", "skipped", "canceled"}:
                row.completed_at = now
            if error_summary is not None:
                row.error_summary = error_summary
            await session.commit()
            await session.refresh(row)
            return row.to_dict()
