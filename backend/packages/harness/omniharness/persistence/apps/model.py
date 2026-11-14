"""ORM models for the Apps platform (Spec 011, Slice 1).

All in the gateway's shared SQL store, so every worker sees the same grants,
cache, leases and limits. Times are epoch seconds (float): compared in SQL for
leases and limits, identical on SQLite and Postgres.

Nothing here holds a raw tool result. `app_source_cache.data` is the PROJECTED
payload only (the declared fields of a catalog entry, clipped and capped).
"""

from __future__ import annotations

from sqlalchemy import Boolean, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from omniharness.persistence.base import Base


class AppGrantRow(Base):
    """One approval: (owner, app, manifest hash). Ended by Revoke only."""

    __tablename__ = "app_grants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    app_id: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    card_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    approved_at: Mapped[float] = mapped_column(Float, nullable=False)
    revoked_at: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (Index("ix_app_grants_owner_app", "owner_id", "app_id"),)


class AppApprovalCardRow(Base):
    """An App access card: drawn from the catalog, granted only by its button."""

    __tablename__ = "app_approval_cards"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    app_id: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    suggestion: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    suggestion_source: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # pending | approved | superseded
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    resolved_at: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (Index("ix_app_cards_owner_app", "owner_id", "app_id"), Index("ix_app_cards_thread", "thread_id"))


class AppSourceCacheRow(Base):
    """The shared cache: one row per (owner, app, source, manifest hash)."""

    __tablename__ = "app_source_cache"

    owner_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    app_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    manifest_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    # fresh | empty | not_connected | failed; NULL before the first answer.
    state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    #: The last good PROJECTED payload (JSON), or NULL.
    data: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: When `data` was fetched.
    fetched_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: When the latest answer (any state) was recorded.
    answered_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    #: When the latest upstream call was claimed: one per source per 60 s,
    #: across workers (a conditional UPDATE claims it).
    attempted_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class AppOpenRow(Base):
    """When the owner last opened an app (the refresher keeps the last 24 h warm)."""

    __tablename__ = "app_opens"

    owner_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    app_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    opened_at: Mapped[float] = mapped_column(Float, nullable=False)


class AppLeaseRow(Base):
    """A named lease (the refresher's), single holder across workers."""

    __tablename__ = "app_leases"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    holder: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[float] = mapped_column(Float, nullable=False)


class AppRateRow(Base):
    """Bridge requests per (owner, app, minute window), across workers."""

    __tablename__ = "app_rate"

    owner_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    app_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    window: Mapped[int] = mapped_column(Integer, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AppAuditRow(Base):
    """The apps audit log: approvals, revokes, refusals, registrations. Never data."""

    __tablename__ = "app_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    app_id: Mapped[str] = mapped_column(String(64), nullable=False)
    at: Mapped[float] = mapped_column(Float, nullable=False)
    event: Mapped[str] = mapped_column(String(48), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    __table_args__ = (Index("ix_app_audit_owner_app", "owner_id", "app_id"),)


class AppPinsRow(Base):
    """Apps pinned to the sidebar, in order (per-user preference)."""

    __tablename__ = "app_pins"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    pins: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
