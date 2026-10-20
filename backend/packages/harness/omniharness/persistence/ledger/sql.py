"""The Project Ledger repository. SYNCHRONOUS, on purpose.

The assistant writes to the ledger through a Tier 3 tool, and a confirmed
Tier 3 tool is run with a synchronous `tool.invoke` from inside the gateway's
running event loop (chat and the confirmation card both do this). An async
repository cannot be awaited from there. So the ledger has its own synchronous
engine on the same database (sqlite3 / psycopg), and the HTTP routes run it in
FastAPI's threadpool.

Every write records who made it (FR-007). Updates carry the version they were
based on; a stale one raises StaleWrite with the current row, so two tabs never
overwrite each other silently.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from omniharness.persistence.ledger.model import (
    LedgerChangeRow,
    LedgerGoalRow,
    LedgerLinkRow,
    LedgerNoteRow,
    LedgerProjectRow,
    LedgerTaskRow,
)
from omniharness.persistence.timestamps import utc_iso

_ROWS = {"project": LedgerProjectRow, "goal": LedgerGoalRow, "task": LedgerTaskRow, "note": LedgerNoteRow, "link": LedgerLinkRow}


class StaleWrite(Exception):
    """The row changed since the caller read it. Carries the current row."""

    def __init__(self, current: dict) -> None:
        super().__init__("changed since it was read")
        self.current = current


def sync_url(async_url: str) -> str:
    """The same database through a synchronous driver."""
    return async_url.replace("sqlite+aiosqlite://", "sqlite://").replace("postgresql+asyncpg://", "postgresql+psycopg://")


def make_sync_engine(async_url: str) -> Engine:
    url = sync_url(async_url)
    args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=args, pool_pre_ping=True)


def _plain(value: Any) -> Any:
    if isinstance(value, datetime):
        # SQLite drops the zone of a DateTime(timezone=True) column; every
        # time here is written in UTC, so say so. Without it a browser read
        # the time as local and showed "updated in about 4 hours" (EDT).
        return utc_iso(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def to_dict(row: Any) -> dict:
    return {c.key: _plain(getattr(row, c.key)) for c in row.__table__.columns}


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


class LedgerRepository:
    def __init__(self, engine: Engine) -> None:
        self._sf = sessionmaker(engine, expire_on_commit=False)
        # One write transaction at a time in this process. A task's short id
        # is read from its project's counter and written back; `with_for_update`
        # does nothing on SQLite, so two concurrent applies (parallel
        # ledger_apply calls in one model step, now that routine ledger writes
        # run at Tier 2) both read T-2 and the second fails its unique check.
        self._write_lock = threading.Lock()

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        """One unit of work: a confirmed ledger_apply is all or nothing."""
        with self._write_lock, self._sf() as session, session.begin():
            yield session

    # ---- writes (inside a transaction) -------------------------------------

    def create(self, s: Session, entity: str, *, owner_id: str | None, actor: str, pending_action_id: str | None = None, **fields: Any) -> dict:
        row_type = _ROWS[entity]
        if entity == "task":
            project = s.get(LedgerProjectRow, fields["project_id"], with_for_update=True)
            if project is None:
                raise LookupError(f"no project {fields['project_id']}")
            fields["short_id"] = f"T-{project.next_task}"
            project.next_task += 1
        row = row_type(id=_new_id(), **({"owner_id": owner_id} if entity == "project" else {}), **fields)
        s.add(row)
        s.flush()
        after = to_dict(row)
        self._record(s, owner_id, entity, row.id, actor, pending_action_id, None, after)
        return after

    def update(self, s: Session, entity: str, entity_id: str, *, owner_id: str | None, actor: str, version: int | None, pending_action_id: str | None = None, **fields: Any) -> dict | None:
        row = s.get(_ROWS[entity], entity_id, with_for_update=True)
        if row is None:
            return None
        before = to_dict(row)
        if version is not None and row.version != version:
            raise StaleWrite(before)
        for key, value in fields.items():
            setattr(row, key, value)
        if entity == "task" and "status" in fields:
            row.done_at = datetime.now(UTC) if fields["status"] == "done" else None
        row.version += 1
        s.flush()
        after = to_dict(row)
        self._record(s, owner_id, entity, entity_id, actor, pending_action_id, before, after)
        return after

    def link(self, s: Session, *, owner_id: str | None, actor: str, pending_action_id: str | None = None, **fields: Any) -> dict:
        """Idempotent: linking the same pair twice returns the existing link."""
        existing = s.scalars(
            select(LedgerLinkRow).where(
                LedgerLinkRow.from_kind == fields["from_kind"],
                LedgerLinkRow.from_id == fields["from_id"],
                LedgerLinkRow.to_kind == fields["to_kind"],
                LedgerLinkRow.to_ref == fields["to_ref"],
            )
        ).first()
        if existing is not None:
            return to_dict(existing)
        return self.create(s, "link", owner_id=owner_id, actor=actor, pending_action_id=pending_action_id, **fields)

    def unlink(self, s: Session, link_id: str, *, owner_id: str | None, actor: str) -> bool:
        row = s.get(LedgerLinkRow, link_id)
        if row is None:
            return False
        self._record(s, owner_id, "link", link_id, actor, None, to_dict(row), None)
        s.execute(delete(LedgerLinkRow).where(LedgerLinkRow.id == link_id))
        return True

    @staticmethod
    def _record(s: Session, owner_id, entity, entity_id, actor, pending_action_id, before, after) -> None:
        s.add(LedgerChangeRow(owner_id=owner_id, entity=entity, entity_id=entity_id, actor=actor, pending_action_id=pending_action_id, before=before, after=after))

    # ---- reads ---------------------------------------------------------------

    def projects(self, owner_id: str | None) -> list[dict]:
        with self._sf() as s:
            rows = s.scalars(select(LedgerProjectRow).where(LedgerProjectRow.owner_id == owner_id).order_by(LedgerProjectRow.updated_at.desc()))
            return [to_dict(r) for r in rows]

    def project(self, project_id: str, owner_id: str | None) -> dict | None:
        with self._sf() as s:
            row = s.get(LedgerProjectRow, project_id)
            return to_dict(row) if row is not None and row.owner_id == owner_id else None

    def children(self, entity: str, project_id: str) -> list[dict]:
        row_type = _ROWS[entity]
        with self._sf() as s:
            rows = s.scalars(select(row_type).where(row_type.project_id == project_id).order_by(row_type.created_at))
            return [to_dict(r) for r in rows]

    def get(self, entity: str, entity_id: str) -> dict | None:
        with self._sf() as s:
            row = s.get(_ROWS[entity], entity_id)
            return to_dict(row) if row is not None else None

    def links_from(self, from_kind: str, from_id: str) -> list[dict]:
        with self._sf() as s:
            rows = s.scalars(select(LedgerLinkRow).where(LedgerLinkRow.from_kind == from_kind, LedgerLinkRow.from_id == from_id).order_by(LedgerLinkRow.created_at))
            return [to_dict(r) for r in rows]

    def links_to(self, to_kind: str, to_ref: str) -> list[dict]:
        with self._sf() as s:
            rows = s.scalars(select(LedgerLinkRow).where(LedgerLinkRow.to_kind == to_kind, LedgerLinkRow.to_ref == to_ref))
            return [to_dict(r) for r in rows]

    def changes_since(self, owner_id: str | None, since: datetime) -> list[dict]:
        """Every change this owner's ledger recorded at or after `since`, oldest first."""
        with self._sf() as s:
            rows = s.scalars(select(LedgerChangeRow).where(LedgerChangeRow.owner_id == owner_id, LedgerChangeRow.at >= since).order_by(LedgerChangeRow.id))
            return [to_dict(r) for r in rows]

    def changes(self, entity_id: str) -> list[dict]:
        with self._sf() as s:
            rows = s.scalars(select(LedgerChangeRow).where(LedgerChangeRow.entity_id == entity_id).order_by(LedgerChangeRow.id))
            return [to_dict(r) for r in rows]
