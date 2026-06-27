"""SQLAlchemy-backed WorkflowArtifactLinkRepository."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omniharness.persistence.workflow_artifact_links.model import WorkflowArtifactLinkRow


class WorkflowArtifactLinkRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def create(
        self,
        *,
        id: str,
        workflow_run_id: str,
        artifact_path: str,
        artifact_type: str | None = None,
    ) -> dict:
        row = WorkflowArtifactLinkRow(
            id=id,
            workflow_run_id=workflow_run_id,
            artifact_path=artifact_path,
            artifact_type=artifact_type,
            created_at=datetime.now(UTC),
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row.to_dict()

    async def list_by_run(self, workflow_run_id: str) -> list[dict]:
        stmt = select(WorkflowArtifactLinkRow).where(WorkflowArtifactLinkRow.workflow_run_id == workflow_run_id).order_by(WorkflowArtifactLinkRow.created_at.asc())
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [r.to_dict() for r in result.scalars()]
