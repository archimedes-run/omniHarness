"""Who may act here, and on whose records (the security baseline).

ONE OWNER. OmniHarness is single-user until multi-user is designed. The owner
is explicit and deterministic: ``OMNI_HARNESS_OWNER_USER_ID`` if set, else the
earliest-created account of any role (on a fresh install, the one
``/initialize`` or the first ``/register`` creates). It is logged at startup,
by id only. Every other account is refused at the door, with a plain
reason, and holds no permissions. The internal principal (trigger engine,
channels; ``X-OmniHarness-Internal-Token``) is the system acting for the owner.

ONE OWNERSHIP CHECK. Every record that belongs to someone stores its owner's
user id, and every list/get/confirm/decline/edit/delete goes through
:func:`can_access` (a predicate) or :func:`require_access` (raises 404). The
rule, in full:

- the record's owner may access it;
- the internal principal may access everything (it is the system);
- the owner account may also access records owned by the system user
  (``DEFAULT_USER_ID``, what internal calls run as) and records with no owner
  (rows that predate ownership; see the migration below);
- nobody else may. A refusal is a 404, so a guessed id says nothing.

THREADS are checked by :func:`require_thread_access` (behind
``@require_permission(..., owner_check=True)``), which keeps the thread store's
existing, stricter rule: only ``threads_meta.user_id == caller`` (a missing row
is allowed for reads only). The owner does not gain the system's threads there;
that behaviour is unchanged from main.

ADOPTING THIS ON ANOTHER BRANCH (confirmations, grants/versions, run store):

1. Store the owner when the record is created: ``owner_id=principal_id(request)``
   in a route, or ``runtime.context["user_id"]`` inside a run (the server sets
   that key; a client can never supply it, see ``services.start_run``).
2. On every read and action::

       from app.gateway.ownership import require_access, filter_accessible
       await require_access(request, record.owner_id, what="confirmation")
       visible = await filter_accessible(request, records, lambda r: r.owner_id)

3. Destructive routes take ``@require_permission("threads", "delete")``.
4. Add a cross-user test through real HTTP (``tests/security/conftest.py`` has
   the fixture: an owner, a second account, and ``admit_additional_accounts``
   to prove the ownership check holds even if the door were open).

MIGRATION. Rows written before owners were stored (``threads_meta`` and
``runs`` with a NULL ``user_id``) are assigned to the owner account at startup
(:func:`assign_ownerless_rows_to_owner`). Pending actions are JSON files that
expire within minutes; one without ``owner_id`` is read as the owner's.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Any

from fastapi import HTTPException, Request

from omniharness.runtime.user_context import DEFAULT_USER_ID

logger = logging.getLogger(__name__)

#: The sentence a refused account reads. Plain, and says what to do.
SECOND_ACCOUNT_REFUSED = "This OmniHarness has a single owner account, and only the owner can sign in. Other accounts are refused until multi-user support is designed."

REGISTRATION_CLOSED = "Registration is closed: this OmniHarness already has its owner account. Multi-user accounts are not supported yet."

#: The system role of the internal principal (see internal_auth.get_internal_user).
INTERNAL_ROLE = "internal"

#: Owners that stand for "the system acting for the owner".
SYSTEM_OWNERS: frozenset[str] = frozenset({DEFAULT_USER_ID})


def admits_additional_accounts() -> bool:
    """False until multi-user is designed. The single seam the refusal hangs on.

    Tests set it True to prove the ownership checks hold on their own, with the
    door open, rather than only because the second account never got in.
    """
    return False


#: Explicit owner (an account id). Unset: the EARLIEST-CREATED account, any
#: role. Role is deliberately not the rule: a live install has an admin-role
#: account that is not the person who owns the data.
OWNER_ENV = "OMNI_HARNESS_OWNER_USER_ID"


async def owner_user_id() -> str | None:
    """The owner account's id. None on a fresh install (no accounts yet).

    ``OMNI_HARNESS_OWNER_USER_ID`` when set; otherwise the earliest-created
    account (ties broken by id). An explicit id that matches no account makes
    NOBODY the owner (fail closed), and startup logs it.
    """
    import os

    from sqlalchemy import select

    from omniharness.persistence.engine import get_session_factory
    from omniharness.persistence.user.model import UserRow

    sf = get_session_factory()
    if sf is None:
        return None
    explicit = os.environ.get(OWNER_ENV, "").strip()
    async with sf() as session:
        # A disabled account is never the owner.
        enabled = UserRow.disabled_at.is_(None)
        if explicit:
            row = (await session.execute(select(UserRow.id).where(UserRow.id == explicit, enabled))).scalar_one_or_none()
        else:
            row = (await session.execute(select(UserRow.id).where(enabled).order_by(UserRow.created_at, UserRow.id).limit(1))).scalar_one_or_none()
    return str(row) if row is not None else None


async def log_owner_at_startup() -> str | None:
    """Say, by id only, which account is the owner and why."""
    import os

    from omniharness.runtime.user_context import set_legacy_data_owner

    owner = await owner_user_id()
    # The legacy shared agents/ directory is the owner's (agents_config).
    set_legacy_data_owner(owner)
    explicit = os.environ.get(OWNER_ENV, "").strip()
    if owner is None and explicit:
        logger.error("%s=%s matches no account: no account can sign in until it names an existing one.", OWNER_ENV, explicit)
    elif owner is None:
        logger.info("No owner account yet (fresh install).")
    else:
        logger.info("Owner account: %s (%s). Every other account is refused.", owner, f"set by {OWNER_ENV}" if explicit else "earliest-created account")
    return owner


async def any_account_exists() -> bool:
    from sqlalchemy import func, select

    from omniharness.persistence.engine import get_session_factory
    from omniharness.persistence.user.model import UserRow

    sf = get_session_factory()
    if sf is None:
        return False
    async with sf() as session:
        count = (await session.execute(select(func.count()).select_from(UserRow))).scalar_one()
    return bool(count)


async def create_first_account(email: str, password: str, *, system_role: str = "admin") -> Any | None:
    """Create the install's FIRST account, atomically; None if one exists.

    The account and the single ``first_account_claim`` row (id=1) are inserted
    in ONE transaction. Concurrent first registrations, on any worker, race on
    that primary key and exactly one commits; every loser rolls back with no
    account. Callers check :func:`any_account_exists` first only to answer
    quickly; this is what makes it true under concurrency.
    """
    from sqlalchemy.exc import IntegrityError, OperationalError

    from app.gateway.auth.models import User
    from app.gateway.auth.password import hash_password_async
    from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
    from omniharness.persistence.engine import get_session_factory
    from omniharness.persistence.user.model import FirstAccountClaimRow

    sf = get_session_factory()
    if sf is None:
        raise RuntimeError("persistence is not initialised")
    if await any_account_exists():
        return None
    user = User(email=email, password_hash=await hash_password_async(password), system_role=system_role, needs_setup=False)
    async with sf() as session:
        try:
            session.add(FirstAccountClaimRow(id=1, user_id=str(user.id)))
            await session.flush()  # the claim first: a loser fails here, before any account row
            session.add(SQLiteUserRepository._user_to_row(user))
            await session.commit()
        except (IntegrityError, OperationalError):
            await session.rollback()
            return None
    return user


def is_disabled(user: Any) -> bool:
    return getattr(user, "disabled_at", None) is not None


def is_internal(user: Any) -> bool:
    return getattr(user, "system_role", None) == INTERNAL_ROLE


async def is_owner(user: Any) -> bool:
    if user is None or is_internal(user):
        return False
    owner = await owner_user_id()
    return owner is not None and str(getattr(user, "id", "")) == owner


async def account_admitted(user: Any) -> bool:
    """May this authenticated principal use the app at all? (Item a.)"""
    if user is None:
        return False
    if is_internal(user):
        return True
    if is_disabled(user):
        return False
    if await is_owner(user):
        return True
    return admits_additional_accounts()


def _request_user(request: Request) -> Any:
    user = getattr(getattr(request, "state", None), "user", None)
    if user is None:
        auth = getattr(getattr(request, "state", None), "auth", None)
        user = getattr(auth, "user", None)
    return user


def principal_id(request: Request) -> str:
    """The caller's user id, as decided by AuthMiddleware. Use it as owner_id."""
    user = _request_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return str(user.id)


async def can_access(request: Request, record_owner: str | None) -> bool:
    """The ownership rule (module docstring). The one predicate everything uses."""
    user = _request_user(request)
    if user is None:
        return False
    if is_internal(user):
        return True
    caller = str(user.id)
    if record_owner is not None and str(record_owner) == caller:
        return True
    if record_owner is None or str(record_owner) in SYSTEM_OWNERS:
        return await is_owner(user)
    return False


async def require_access(request: Request, record_owner: str | None, *, what: str = "item", ident: str = "") -> None:
    """Raise 404 unless the caller may access a record owned by ``record_owner``."""
    if not await can_access(request, record_owner):
        raise HTTPException(status_code=404, detail=f"{what} {ident} not found".replace("  ", " ").strip())


async def filter_accessible[T](request: Request, records: Iterable[T], owner_of: Callable[[T], str | None]) -> list[T]:
    """The records the caller may see, for list endpoints."""
    return [r for r in records if await can_access(request, owner_of(r))]


async def require_owner_account(request: Request) -> None:
    """FastAPI dependency: the OWNER account (or the internal principal) only.

    For install-wide records that belong to the owner as a whole rather than
    row by row: trigger rules and their firings and runs, automations, the
    inbox, the local Claude/Codex sessions on this machine. Use it as
    ``APIRouter(..., dependencies=[Depends(require_owner_account)])``.
    """
    user = _request_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if is_internal(user) or await is_owner(user):
        return
    raise HTTPException(status_code=403, detail="Only the owner account can see this.")


async def require_thread_access(request: Request, thread_id: str, *, require_existing: bool = False) -> None:
    """Raise 404 unless the caller owns ``thread_id`` (threads_meta.user_id).

    Used by ``@require_permission(..., owner_check=True)`` and by every route
    that reaches a thread some other way (a body field, a query parameter).
    A missing row is allowed for reads (an untracked legacy thread) and refused
    when ``require_existing`` (anything that writes or deletes).
    """
    from app.gateway.deps import get_thread_store

    caller = principal_id(request)
    thread_store = get_thread_store(request)
    allowed = await thread_store.check_access(thread_id, caller, require_existing=require_existing)
    if not allowed:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")


#: How the live install was hand-disabled before ``disabled_at`` existed: the
#: password hash prefixed so that verification fails closed.
LEGACY_DISABLED_PREFIX = "!disabled!"


async def migrate_prefix_disabled_accounts() -> int:
    """Startup migration: ``!disabled!<hash>`` becomes ``<hash>`` + ``disabled_at``.

    The account stays disabled (now by the proper column, which every check
    reads) and its real hash is restored, so ``accounts enable`` can bring it
    back intact. Idempotent.
    """
    from datetime import UTC, datetime

    from sqlalchemy import select

    from omniharness.persistence.engine import get_session_factory
    from omniharness.persistence.user.model import UserRow

    sf = get_session_factory()
    if sf is None:
        return 0
    changed = 0
    async with sf() as session:
        rows = (await session.execute(select(UserRow).where(UserRow.password_hash.like(f"{LEGACY_DISABLED_PREFIX}%")))).scalars().all()
        for row in rows:
            row.password_hash = row.password_hash[len(LEGACY_DISABLED_PREFIX) :]
            if row.disabled_at is None:
                row.disabled_at = datetime.now(UTC)
                row.disabled_reason = "migrated from the '!disabled!' password-hash prefix"
            row.token_version += 1
            changed += 1
            logger.info("Account %s: '!disabled!' prefix migrated to disabled_at (still disabled).", row.id)
        await session.commit()
    return changed


async def assign_ownerless_rows_to_owner() -> dict[str, int]:
    """Startup migration: NULL-owner threads/runs become the owner's.

    Before this baseline a NULL ``user_id`` meant "shared": any signed-in
    account could read it. Assigning such rows to the owner is the safe choice:
    the owner is the only person who could have created them on a single-user
    install, and no second account inherits them.
    """
    from sqlalchemy import update

    from omniharness.persistence.engine import get_session_factory
    from omniharness.persistence.run.model import RunRow
    from omniharness.persistence.thread_meta.model import ThreadMetaRow

    owner = await owner_user_id()
    sf = get_session_factory()
    if owner is None or sf is None:
        return {}
    counts: dict[str, int] = {}
    async with sf() as session:
        for name, model in (("threads_meta", ThreadMetaRow), ("runs", RunRow)):
            result = await session.execute(update(model).where(model.user_id.is_(None)).values(user_id=owner))
            counts[name] = int(result.rowcount or 0)
        await session.commit()
    if any(counts.values()):
        logger.info("Assigned owner-less rows to the owner account: %s", counts)
    return counts
