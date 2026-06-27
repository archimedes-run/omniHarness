"""SQLAlchemy-backed WorkflowRepository implementation.

Each method acquires and releases its own short-lived session.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omniharness.persistence.workflows.model import WorkflowRow


class WorkflowRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def create(
        self,
        *,
        id: str,
        owner_id: str | None,
        title: str,
        description: str | None = None,
        instruction_prompt: str | None = None,
        trigger_type: str | None = "manual",
        approval_policy: str | None = "draft_only",
        created_by: str | None = "user",
    ) -> dict:
        now = datetime.now(UTC)
        row = WorkflowRow(
            id=id,
            owner_id=owner_id,
            title=title,
            description=description,
            status="draft",
            instruction_prompt=instruction_prompt,
            trigger_type=trigger_type,
            approval_policy=approval_policy,
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row.to_dict()

    async def get(self, id: str, *, owner_id: str | None = None) -> dict | None:
        async with self._sf() as session:
            row = await session.get(WorkflowRow, id)
            if row is None:
                return None
            if owner_id is not None and row.owner_id != owner_id:
                return None
            return row.to_dict()

    async def list_by_owner(self, owner_id: str | None, *, limit: int = 100) -> list[dict]:
        stmt = select(WorkflowRow)
        if owner_id is not None:
            stmt = stmt.where(WorkflowRow.owner_id == owner_id)
        stmt = stmt.order_by(WorkflowRow.created_at.desc()).limit(limit)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [r.to_dict() for r in result.scalars()]

    async def update(self, id: str, *, owner_id: str | None = None, title: str | None = None, description: str | None = None, status: str | None = None) -> dict | None:
        async with self._sf() as session:
            row = await session.get(WorkflowRow, id)
            if row is None:
                return None
            if owner_id is not None and row.owner_id != owner_id:
                return None
            if title is not None:
                row.title = title
            if description is not None:
                row.description = description
            if status is not None:
                row.status = status
            row.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(row)
            return row.to_dict()

    async def set_current_version(self, id: str, version_id: str) -> dict | None:
        """Set current_version_id on a workflow (called after v1 is created)."""
        async with self._sf() as session:
            row = await session.get(WorkflowRow, id)
            if row is None:
                return None
            row.current_version_id = version_id
            row.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(row)
            return row.to_dict()

    async def archive(self, id: str, *, owner_id: str | None = None) -> dict | None:
        async with self._sf() as session:
            row = await session.get(WorkflowRow, id)
            if row is None:
                return None
            if owner_id is not None and row.owner_id != owner_id:
                return None
            row.status = "archived"
            row.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(row)
            return row.to_dict()
