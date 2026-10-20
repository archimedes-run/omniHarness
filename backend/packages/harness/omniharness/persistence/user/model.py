"""ORM model for the users table.

Lives in the harness persistence package so it is picked up by
``Base.metadata.create_all()`` alongside ``threads_meta``, ``runs``,
``run_events``, and ``feedback``. Using the shared engine means:

- One SQLite/Postgres database, one connection pool
- One schema initialisation codepath
- Consistent async sessions across auth and persistence reads
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from omniharness.persistence.base import Base


class UserRow(Base):
    __tablename__ = "users"

    # UUIDs are stored as 36-char strings for cross-backend portability.
    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # "admin" | "user" — kept as plain string to avoid ALTER TABLE pain
    # when new roles are introduced.
    system_role: Mapped[str] = mapped_column(String(16), nullable=False, default="user")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    # OAuth linkage (optional). A partial unique index enforces one
    # account per (provider, oauth_id) pair, leaving NULL/NULL rows
    # unconstrained so plain password accounts can coexist.
    oauth_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    oauth_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Auth lifecycle flags
    needs_setup: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    token_version: Mapped[int] = mapped_column(nullable=False, default=0)

    # Security baseline: a disabled account is refused everywhere (login with
    # the wrong-password answer, every route, no permissions) and is never the
    # owner. Reversible: ``python -m app.gateway.auth.accounts enable <email>``.
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    disabled_reason: Mapped[str | None] = mapped_column(String(256), nullable=True, default=None)

    __table_args__ = (
        Index(
            "idx_users_oauth_identity",
            "oauth_provider",
            "oauth_id",
            unique=True,
            sqlite_where=text("oauth_provider IS NOT NULL AND oauth_id IS NOT NULL"),
        ),
    )


class FirstAccountClaimRow(Base):
    """At most one row, ever: the claim on creating an install's FIRST account.

    Security baseline (single owner). ``/register`` and ``/initialize`` insert
    this row (id=1) in the same transaction as the account, so concurrent first
    registrations race on a primary key and exactly one commits, on any worker
    and any backend. See app.gateway.ownership.create_first_account.
    """

    __tablename__ = "first_account_claim"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
