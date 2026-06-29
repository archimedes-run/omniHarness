"""SQLAlchemy-backed WorkflowVersionRepository."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omniharness.persistence.workflow_versions.model import WorkflowVersionRow


class WorkflowVersionRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def create(
        self,
        *,
        id: str,
        workflow_id: str,
        version_number: int,
        instruction_prompt: str | None = None,
        created_by: str = "user",
    ) -> dict:
        row = WorkflowVersionRow(
            id=id,
            workflow_id=workflow_id,
            version_number=version_number,
            instruction_prompt=instruction_prompt,
            created_by=created_by,
            created_at=datetime.now(UTC),
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row.to_dict()

    async def get(self, id: str) -> dict | None:
        async with self._sf() as session:
            row = await session.get(WorkflowVersionRow, id)
            return row.to_dict() if row else None

    async def set_spec_json(self, version_id: str, spec_json: dict) -> dict | None:
        """Persist a validated spec_json on this version (overwrites on regenerate)."""
        async with self._sf() as session:
            row = await session.get(WorkflowVersionRow, version_id)
            if row is None:
                return None
            row.spec_json = spec_json
            await session.commit()
            await session.refresh(row)
            return row.to_dict()

    async def list_by_workflow(self, workflow_id: str, *, limit: int = 50) -> list[dict]:
        stmt = select(WorkflowVersionRow).where(WorkflowVersionRow.workflow_id == workflow_id).order_by(WorkflowVersionRow.version_number.asc()).limit(limit)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [r.to_dict() for r in result.scalars()]
