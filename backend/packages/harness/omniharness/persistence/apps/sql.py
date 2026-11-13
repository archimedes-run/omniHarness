"""SQLAlchemy repository for the Apps platform (Spec 011, Slice 1).

Every cross-worker guarantee is a single conditional statement here:

  * a lease is held by whoever's UPDATE matched (`holder = me OR expired`);
  * one upstream call per source per interval: the UPDATE of `attempted_at`
    that matched (`attempted_at IS NULL OR attempted_at < now - interval`);
  * a request counter is an UPDATE ... SET count = count + 1, read back.
"""

from __future__ import annotations

import json
import secrets
import time

from sqlalchemy import delete, exists, func, insert, literal, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omniharness.persistence.apps.model import (
    AppApprovalCardRow,
    AppAuditRow,
    AppGrantRow,
    AppLeaseRow,
    AppOpenRow,
    AppPinsRow,
    AppRateRow,
    AppSourceCacheRow,
)

#: Rate windows older than this many minutes are pruned on the next hit.
_RATE_KEEP_WINDOWS = 5


def _now() -> float:
    return time.time()


class AppRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    # ---- grants ----------------------------------------------------------------

    async def active_grant(self, *, owner_id: str, app_id: str, manifest_hash: str) -> dict | None:
        async with self._sf() as s:
            row = (
                await s.scalars(select(AppGrantRow).where(AppGrantRow.owner_id == owner_id, AppGrantRow.app_id == app_id, AppGrantRow.manifest_hash == manifest_hash, AppGrantRow.revoked_at.is_(None)).order_by(AppGrantRow.id.desc()))
            ).first()
            return row.to_dict() if row is not None else None

    async def grants(self, *, owner_id: str, app_id: str) -> list[dict]:
        async with self._sf() as s:
            rows = await s.scalars(select(AppGrantRow).where(AppGrantRow.owner_id == owner_id, AppGrantRow.app_id == app_id).order_by(AppGrantRow.id.desc()))
            return [r.to_dict() for r in rows]

    async def granted_versions(self, *, owner_id: str, app_id: str) -> set[int]:
        """Versions the owner's button approved (a held version is served once it is one)."""
        async with self._sf() as s:
            rows = await s.scalars(select(AppGrantRow.version).where(AppGrantRow.owner_id == owner_id, AppGrantRow.app_id == app_id))
            return set(rows)

    async def create_grant(self, *, owner_id: str, app_id: str, manifest_hash: str, version: int, card_id: str | None) -> dict:
        async with self._sf() as s:
            row = AppGrantRow(owner_id=owner_id, app_id=app_id, manifest_hash=manifest_hash, version=version, card_id=card_id, approved_at=_now())
            s.add(row)
            await s.commit()
            return row.to_dict()

    async def revoke_all(self, *, owner_id: str, app_id: str) -> int:
        async with self._sf() as s:
            result = await s.execute(update(AppGrantRow).where(AppGrantRow.owner_id == owner_id, AppGrantRow.app_id == app_id, AppGrantRow.revoked_at.is_(None)).values(revoked_at=_now()))
            await s.commit()
            return int(result.rowcount or 0)

    # ---- approval cards -------------------------------------------------------

    async def create_card(self, *, owner_id: str, app_id: str, version: int, manifest_hash: str, thread_id: str | None, suggestion: bool, suggestion_source: str | None) -> dict:
        """A new pending card; any older pending card of the app is superseded."""
        async with self._sf() as s:
            now = _now()
            await s.execute(update(AppApprovalCardRow).where(AppApprovalCardRow.owner_id == owner_id, AppApprovalCardRow.app_id == app_id, AppApprovalCardRow.status == "pending").values(status="superseded", resolved_at=now))
            row = AppApprovalCardRow(
                id=secrets.token_hex(16),
                owner_id=owner_id,
                app_id=app_id,
                version=version,
                manifest_hash=manifest_hash,
                thread_id=thread_id,
                suggestion=suggestion,
                suggestion_source=suggestion_source,
                status="pending",
                created_at=now,
            )
            s.add(row)
            await s.commit()
            return row.to_dict()

    async def pending_card(self, *, owner_id: str, app_id: str) -> dict | None:
        async with self._sf() as s:
            row = (
                await s.scalars(select(AppApprovalCardRow).where(AppApprovalCardRow.owner_id == owner_id, AppApprovalCardRow.app_id == app_id, AppApprovalCardRow.status == "pending").order_by(AppApprovalCardRow.created_at.desc()))
            ).first()
            return row.to_dict() if row is not None else None

    async def cards_for_thread(self, *, owner_id: str, thread_id: str, limit: int = 50) -> list[dict]:
        async with self._sf() as s:
            rows = await s.scalars(select(AppApprovalCardRow).where(AppApprovalCardRow.owner_id == owner_id, AppApprovalCardRow.thread_id == thread_id).order_by(AppApprovalCardRow.created_at.desc()).limit(limit))
            return [r.to_dict() for r in rows]

    async def resolve_card(self, *, card_id: str, owner_id: str, status: str) -> bool:
        """pending -> `status`; False when the card was not pending (a second press)."""
        async with self._sf() as s:
            result = await s.execute(update(AppApprovalCardRow).where(AppApprovalCardRow.id == card_id, AppApprovalCardRow.owner_id == owner_id, AppApprovalCardRow.status == "pending").values(status=status, resolved_at=_now()))
            await s.commit()
            return bool(result.rowcount)

    # ---- cache ----------------------------------------------------------------

    async def cache_row(self, *, owner_id: str, app_id: str, source: str, manifest_hash: str) -> dict | None:
        async with self._sf() as s:
            row = await s.get(AppSourceCacheRow, (owner_id, app_id, source, manifest_hash))
            return row.to_dict() if row is not None else None

    async def cache_rows(self, *, owner_id: str, app_id: str) -> list[dict]:
        async with self._sf() as s:
            rows = await s.scalars(select(AppSourceCacheRow).where(AppSourceCacheRow.owner_id == owner_id, AppSourceCacheRow.app_id == app_id))
            return [r.to_dict() for r in rows]

    @staticmethod
    def _granted(owner_id: str, app_id: str, manifest_hash: str):
        """An active grant exists: checked INSIDE each cache write, so a revoke
        that lands mid-fetch leaves nothing to recreate or refill."""
        return exists().where(AppGrantRow.owner_id == owner_id, AppGrantRow.app_id == app_id, AppGrantRow.manifest_hash == manifest_hash, AppGrantRow.revoked_at.is_(None))

    async def claim_upstream(self, *, owner_id: str, app_id: str, source: str, manifest_hash: str, min_interval_s: float) -> bool:
        """True for exactly one caller per `min_interval_s`, across workers,
        and only while the (owner, app, hash) grant is active."""
        now = _now()
        async with self._sf() as s:
            if await s.get(AppSourceCacheRow, (owner_id, app_id, source, manifest_hash)) is None:
                cols = (AppSourceCacheRow.owner_id, AppSourceCacheRow.app_id, AppSourceCacheRow.source, AppSourceCacheRow.manifest_hash)
                row = select(literal(owner_id), literal(app_id), literal(source), literal(manifest_hash)).where(self._granted(owner_id, app_id, manifest_hash))
                try:
                    await s.execute(insert(AppSourceCacheRow).from_select(cols, row))
                    await s.commit()
                except IntegrityError:
                    await s.rollback()
        async with self._sf() as s:
            key = (AppSourceCacheRow.owner_id == owner_id, AppSourceCacheRow.app_id == app_id, AppSourceCacheRow.source == source, AppSourceCacheRow.manifest_hash == manifest_hash)
            due = (AppSourceCacheRow.attempted_at.is_(None)) | (AppSourceCacheRow.attempted_at < now - min_interval_s)
            result = await s.execute(update(AppSourceCacheRow).where(*key, due, self._granted(owner_id, app_id, manifest_hash)).values(attempted_at=now))
            await s.commit()
            return bool(result.rowcount)

    async def record_answer(self, *, owner_id: str, app_id: str, source: str, manifest_hash: str, state: str, data_json: str | None, reason: str | None) -> bool:
        """Store one answer. `data_json` (projected) replaces the last good
        data only for fresh/empty; failed and not_connected keep it. False when
        the row is gone or the grant ended (revoked meanwhile): nothing is stored."""
        now = _now()
        values: dict = {"state": state, "answered_at": now, "reason": reason}
        if state in ("fresh", "empty"):
            values.update(data=data_json, fetched_at=now)
        async with self._sf() as s:
            key = (AppSourceCacheRow.owner_id == owner_id, AppSourceCacheRow.app_id == app_id, AppSourceCacheRow.source == source, AppSourceCacheRow.manifest_hash == manifest_hash)
            result = await s.execute(update(AppSourceCacheRow).where(*key, self._granted(owner_id, app_id, manifest_hash)).values(**values))
            await s.commit()
            return bool(result.rowcount)

    async def delete_cache(self, *, owner_id: str, app_id: str) -> int:
        async with self._sf() as s:
            result = await s.execute(delete(AppSourceCacheRow).where(AppSourceCacheRow.owner_id == owner_id, AppSourceCacheRow.app_id == app_id))
            await s.commit()
            return int(result.rowcount or 0)

    # ---- opens ----------------------------------------------------------------

    async def mark_opened(self, *, owner_id: str, app_id: str) -> None:
        now = _now()
        async with self._sf() as s:
            row = await s.get(AppOpenRow, (owner_id, app_id))
            if row is None:
                s.add(AppOpenRow(owner_id=owner_id, app_id=app_id, opened_at=now))
            else:
                row.opened_at = now
            try:
                await s.commit()
            except IntegrityError:
                await s.rollback()

    async def opened_at(self, *, owner_id: str, app_id: str) -> float | None:
        async with self._sf() as s:
            row = await s.get(AppOpenRow, (owner_id, app_id))
            return row.opened_at if row is not None else None

    async def opened_since(self, cutoff: float) -> list[tuple[str, str]]:
        async with self._sf() as s:
            rows = await s.execute(select(AppOpenRow.owner_id, AppOpenRow.app_id).where(AppOpenRow.opened_at >= cutoff))
            return [(r[0], r[1]) for r in rows]

    # ---- leases ---------------------------------------------------------------

    async def acquire_lease(self, *, name: str, holder: str, ttl_s: float) -> bool:
        now = _now()
        async with self._sf() as s:
            if await s.get(AppLeaseRow, name) is None:
                s.add(AppLeaseRow(name=name, holder=holder, expires_at=now + ttl_s))
                try:
                    await s.commit()
                    return True
                except IntegrityError:
                    await s.rollback()
        async with self._sf() as s:
            result = await s.execute(update(AppLeaseRow).where(AppLeaseRow.name == name, (AppLeaseRow.holder == holder) | (AppLeaseRow.expires_at < now)).values(holder=holder, expires_at=now + ttl_s))
            await s.commit()
            return bool(result.rowcount)

    # ---- rate -----------------------------------------------------------------

    async def hit(self, *, owner_id: str, app_id: str) -> int:
        """Count one request in this minute's window; returns the count so far."""
        window = int(_now() // 60)
        async with self._sf() as s:
            key = (AppRateRow.owner_id == owner_id, AppRateRow.app_id == app_id, AppRateRow.window == window)
            result = await s.execute(update(AppRateRow).where(*key).values(count=AppRateRow.count + 1))
            if not result.rowcount:
                s.add(AppRateRow(owner_id=owner_id, app_id=app_id, window=window, count=1))
                try:
                    await s.commit()
                except IntegrityError:
                    await s.rollback()
                    await s.execute(update(AppRateRow).where(*key).values(count=AppRateRow.count + 1))
                    await s.commit()
            else:
                await s.commit()
            await s.execute(delete(AppRateRow).where(AppRateRow.owner_id == owner_id, AppRateRow.app_id == app_id, AppRateRow.window < window - _RATE_KEEP_WINDOWS))
            await s.commit()
            count = await s.scalar(select(func.coalesce(func.max(AppRateRow.count), 0)).where(*key))
            return int(count or 0)

    # ---- audit ----------------------------------------------------------------

    async def audit(self, *, owner_id: str, app_id: str, event: str, detail: dict | None = None) -> None:
        async with self._sf() as s:
            s.add(AppAuditRow(owner_id=owner_id, app_id=app_id, at=_now(), event=event, detail=json.dumps(detail or {}, sort_keys=True)))
            await s.commit()

    async def audit_entries(self, *, owner_id: str, app_id: str | None = None, limit: int = 200) -> list[dict]:
        async with self._sf() as s:
            query = select(AppAuditRow).where(AppAuditRow.owner_id == owner_id)
            if app_id is not None:
                query = query.where(AppAuditRow.app_id == app_id)
            rows = await s.scalars(query.order_by(AppAuditRow.id.desc()).limit(limit))
            return [{**r.to_dict(), "detail": json.loads(r.detail or "{}")} for r in rows]

    # ---- pins -----------------------------------------------------------------

    async def get_pins(self, *, user_id: str) -> list[str]:
        async with self._sf() as s:
            row = await s.get(AppPinsRow, user_id)
            if row is None:
                return []
            try:
                pins = json.loads(row.pins)
            except ValueError:
                return []
            return [p for p in pins if isinstance(p, str)] if isinstance(pins, list) else []

    async def set_pins(self, *, user_id: str, pins: list[str]) -> list[str]:
        async with self._sf() as s:
            row = await s.get(AppPinsRow, user_id)
            if row is None:
                s.add(AppPinsRow(user_id=user_id, pins=json.dumps(pins)))
            else:
                row.pins = json.dumps(pins)
            await s.commit()
            return list(pins)
