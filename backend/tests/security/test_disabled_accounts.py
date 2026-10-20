"""Disabled accounts (security baseline, user item A). Real HTTP, auth ON.

A disabled account is refused at login with exactly the wrong-password answer,
refused on every route, holds no permissions, and is never the owner. The
CLI's functions (app.gateway.auth.accounts) disable and enable it reversibly,
and the startup migration turns the live install's hand-made
'!disabled!<hash>' marker into the proper column.
"""

from __future__ import annotations

from _security_helpers import OWNER, SECOND, login


def _call(client, fn, *args, **kwargs):
    async def _go():
        return await fn(*args, **kwargs)

    return client.portal.call(_go)


def test_a_disabled_account_gets_the_wrong_password_answer(sec) -> None:
    from app.gateway.auth.accounts import set_disabled

    sec.admit_second()  # the door is open: only disabled_at can refuse it
    _call(sec.owner, set_disabled, SECOND[0], disabled=True, reason="test")
    _, right = login(sec.app, *SECOND)
    _, wrong = login(sec.app, SECOND[0], "Wr0ng!Password")
    assert right.status_code == 401
    assert right.json() == wrong.json()


def test_a_disabled_accounts_live_session_dies_and_reaches_nothing(sec) -> None:
    from app.gateway.auth.accounts import set_disabled

    sec.admit_second()
    other = sec.login_second()
    assert other.post("/api/threads/search", json={}).status_code == 200  # positive control
    _call(sec.owner, set_disabled, SECOND[0], disabled=True)
    assert other.post("/api/threads/search", json={}).status_code in (401, 403)
    # Even a freshly minted, correctly versioned token for it is refused.
    from fastapi.testclient import TestClient

    from app.gateway.auth import create_access_token
    from app.gateway.deps import get_local_provider

    async def _version():
        return (await get_local_provider().get_user(sec.second_id)).token_version

    fresh = TestClient(sec.app)
    fresh.cookies.set("access_token", create_access_token(sec.second_id, token_version=sec.owner.portal.call(_version)))
    assert fresh.get("/api/v1/auth/me").status_code == 403


def test_disable_is_reversible(sec) -> None:
    from app.gateway.auth.accounts import set_disabled

    sec.admit_second()
    _call(sec.owner, set_disabled, SECOND[0], disabled=True)
    assert login(sec.app, *SECOND)[1].status_code == 401
    _call(sec.owner, set_disabled, SECOND[0], disabled=False)
    assert login(sec.app, *SECOND)[1].status_code == 200


def test_a_disabled_account_is_never_the_owner(sec) -> None:
    """The owner is PINNED: disabling it (forced) locks everyone out; no other
    account, earlier or later, becomes the owner."""
    from app.gateway.auth.accounts import AccountError, set_disabled

    try:
        _call(sec.owner, set_disabled, OWNER[0], disabled=True)
        raise AssertionError("disabling the owner without --force must be refused")
    except AccountError:
        pass
    _call(sec.owner, set_disabled, OWNER[0], disabled=True, force=True)
    assert login(sec.app, *OWNER)[1].status_code == 401
    assert login(sec.app, *SECOND)[1].status_code == 401  # nobody else became the owner
    _call(sec.owner, set_disabled, OWNER[0], disabled=False)
    assert login(sec.app, *OWNER)[1].status_code == 200


def test_the_prefix_hack_migrates_to_disabled_at(make_gateway) -> None:
    """The live DB's hand-disabled accounts: '!disabled!<hash>'. Startup turns
    that into disabled_at, restores the hash, and the account stays refused
    until it is enabled, when its own password works again."""
    from app.gateway.auth.accounts import set_disabled
    from app.gateway.ownership import migrate_prefix_disabled_accounts, owner_user_id

    app, client = make_gateway(initialize=False)

    async def _seed():
        from sqlalchemy import update

        from app.gateway.deps import get_local_provider
        from omniharness.persistence.engine import get_session_factory
        from omniharness.persistence.user.model import UserRow

        provider = get_local_provider()
        first = await provider.create_user(email="first@example.com", password="F1rst!Strong", system_role="admin")
        await provider.create_user(email=OWNER[0], password=OWNER[1], system_role="admin")
        async with get_session_factory()() as s:
            row = await s.get(UserRow, str(first.id))
            await s.execute(update(UserRow).where(UserRow.id == str(first.id)).values(password_hash="!disabled!" + row.password_hash))
            await s.commit()
        return str(first.id)

    first_id = client.portal.call(_seed)
    assert client.portal.call(owner_user_id) == first_id  # the hazard the migration removes
    assert client.portal.call(migrate_prefix_disabled_accounts) == 1
    assert client.portal.call(migrate_prefix_disabled_accounts) == 0  # idempotent
    assert client.portal.call(owner_user_id) != first_id
    assert login(app, "first@example.com", "F1rst!Strong")[1].status_code == 401
    assert login(app, *OWNER)[1].status_code == 200
    _call(client, set_disabled, "first@example.com", disabled=False)
    assert login(app, "first@example.com", "F1rst!Strong")[1].status_code == 200  # hash restored, earliest again


_PUBLIC = {"/api/channels/openclaw/webhook", "/api/v1/auth/login/local", "/api/v1/auth/register", "/api/v1/auth/logout", "/api/v1/auth/setup-status", "/api/v1/auth/initialize"}


def test_a_re_enabled_non_owner_reaches_no_route_at_all(sec) -> None:
    """The single-owner door, on EVERY route of the production app (LangGraph-
    compatible runs, streaming, uploads, artifacts...): a session for an account
    that is enabled but not the owner is refused before any route runs."""
    import re

    from fastapi.testclient import TestClient

    from app.gateway.auth import create_access_token
    from app.gateway.auth.accounts import set_disabled
    from app.gateway.deps import get_local_provider

    _call(sec.owner, set_disabled, SECOND[0], disabled=True)
    _call(sec.owner, set_disabled, SECOND[0], disabled=False)  # re-enabled: still not the owner

    async def _version():
        return (await get_local_provider().get_user(sec.second_id)).token_version

    other = TestClient(sec.app)
    other.cookies.set("access_token", create_access_token(sec.second_id, token_version=sec.owner.portal.call(_version)))
    other.cookies.set("csrf_token", "c")
    other.headers["X-CSRF-Token"] = "c"
    checked, leaks = 0, []
    for route in sec.app.routes:
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", "")
        if not methods or path in _PUBLIC or path.startswith(("/docs", "/redoc", "/openapi", "/health")) or "preview-token" in path:
            continue
        url = re.sub(r"\{[^}]+\}", "x", path)
        for method in sorted(methods - {"HEAD", "OPTIONS"}):
            resp = other.request(method, url, json={} if method in ("POST", "PUT", "PATCH") else None)
            checked += 1
            if resp.status_code not in (401, 403):
                leaks.append((method, path, resp.status_code))
    assert checked > 150, checked
    assert not leaks, leaks
