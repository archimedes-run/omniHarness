"""Disable or re-enable an account, reversibly (security baseline).

Usage:
    python -m app.gateway.auth.accounts list
    python -m app.gateway.auth.accounts disable <email> [--reason TEXT] [--force]
    python -m app.gateway.auth.accounts enable <email>

A disabled account keeps its row, its password hash and its data. It is
refused at login with exactly the wrong-password answer, refused on every route
(AuthMiddleware, LangGraph auth), holds no permissions, and is never resolved
as the owner (app.gateway.ownership). Disabling also bumps ``token_version``,
so any session it holds dies at once.

Disabling the OWNER needs ``--force``: the owner is pinned, so nobody else
becomes the owner and every account is locked out until it is re-enabled.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime


class AccountError(RuntimeError):
    pass


async def set_disabled(email: str, *, disabled: bool, reason: str | None = None, force: bool = False) -> str:
    """Disable or enable the account with this email; returns its id."""
    from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
    from app.gateway.ownership import owner_user_id
    from omniharness.persistence.engine import get_session_factory

    sf = get_session_factory()
    if sf is None:
        raise AccountError("persistence engine not available (check config.database)")
    repo = SQLiteUserRepository(sf)
    user = await repo.get_user_by_email(email)
    if user is None:
        raise AccountError(f"no account with email {email!r}")
    if disabled:
        if not force and str(user.id) == await owner_user_id():
            raise AccountError("that is the owner account; disabling it locks EVERY account out until it is enabled again (or OMNI_HARNESS_OWNER_USER_ID names another). Pass --force if you mean it.")
        user.disabled_at = user.disabled_at or datetime.now(UTC)
        user.disabled_reason = reason or user.disabled_reason or "disabled by the operator"
        user.token_version += 1
    else:
        user.disabled_at = None
        user.disabled_reason = None
    await repo.update_user(user)
    return str(user.id)


async def list_accounts() -> list[dict]:
    from sqlalchemy import select

    from app.gateway.ownership import owner_user_id
    from omniharness.persistence.engine import get_session_factory
    from omniharness.persistence.user.model import UserRow

    sf = get_session_factory()
    if sf is None:
        raise AccountError("persistence engine not available (check config.database)")
    owner = await owner_user_id()
    async with sf() as session:
        rows = (await session.execute(select(UserRow).order_by(UserRow.created_at, UserRow.id))).scalars().all()
    return [{"id": r.id, "email": r.email, "role": r.system_role, "created_at": r.created_at.isoformat(), "disabled": r.disabled_at is not None, "owner": r.id == owner} for r in rows]


async def _run(args: argparse.Namespace) -> int:
    from omniharness.config import get_app_config
    from omniharness.persistence.engine import close_engine, init_engine_from_config

    await init_engine_from_config(get_app_config().database)
    try:
        if args.command == "list":
            for a in await list_accounts():
                flags = ", ".join(f for f, on in (("OWNER", a["owner"]), ("disabled", a["disabled"])) if on)
                print(f"{a['id']}  {a['email']}  role={a['role']}  created={a['created_at']}{'  [' + flags + ']' if flags else ''}")
            return 0
        user_id = await set_disabled(args.email, disabled=args.command == "disable", reason=getattr(args, "reason", None), force=getattr(args, "force", False))
        print(f"{args.command}d account {user_id}")
        return 0
    except AccountError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        await close_engine()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Disable or enable an OmniHarness account (reversible).")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list accounts, marking the owner and disabled ones")
    dis = sub.add_parser("disable", help="refuse this account everywhere")
    dis.add_argument("email")
    dis.add_argument("--reason", default=None)
    dis.add_argument("--force", action="store_true", help="allow disabling the owner account")
    ena = sub.add_parser("enable", help="undo disable")
    ena.add_argument("email")
    sys.exit(asyncio.run(_run(parser.parse_args(argv))))


if __name__ == "__main__":
    main()
