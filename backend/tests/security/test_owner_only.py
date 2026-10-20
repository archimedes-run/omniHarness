"""Item 0a: registration closes once the owner exists; other accounts are refused.

Real HTTP against `create_app()` + lifespan, auth ON.
"""

from __future__ import annotations

from _security_helpers import OWNER, SECOND, login


def test_first_registration_on_a_fresh_install_creates_the_owner(make_gateway) -> None:
    app, client = make_gateway(initialize=False)
    resp = client.post("/api/v1/auth/register", json={"email": OWNER[0], "password": OWNER[1]})
    assert resp.status_code == 201, resp.text
    assert resp.json()["system_role"] == "admin"
    # ...and that owner can use the app.
    owner, login_resp = login(app, *OWNER)
    assert login_resp.status_code == 200
    assert owner.post("/api/threads/search", json={}).status_code == 200


def test_second_registration_is_refused_with_a_plain_reason(sec) -> None:
    resp = sec.owner.post("/api/v1/auth/register", json={"email": "third@example.com", "password": "Thr33!Strong"})
    assert resp.status_code == 403
    detail = resp.json()["detail"]
    assert detail["code"] == "registration_closed"
    assert "Registration is closed" in detail["message"]
    # Nothing was created: that password does not sign anyone in.
    _, again = login(sec.app, "third@example.com", "Thr33!Strong")
    assert again.status_code == 401


def test_a_second_account_cannot_sign_in(sec) -> None:
    """Refused with EXACTLY the wrong-password answer, so the form is not an
    oracle for which passwords are right (review round)."""
    client, resp = login(sec.app, *SECOND)
    _, wrong = login(sec.app, SECOND[0], "Wr0ng!Password")
    assert resp.status_code == 401
    assert resp.json() == wrong.json()
    assert resp.json()["detail"]["code"] == "invalid_credentials"
    assert "access_token" not in client.cookies


def test_a_second_accounts_valid_session_is_refused_on_every_route(sec) -> None:
    """Even holding a valid, correctly signed session (e.g. issued before this
    baseline), a second account reaches nothing."""
    from fastapi.testclient import TestClient

    from app.gateway.auth import create_access_token

    client = TestClient(sec.app)
    client.cookies.set("access_token", create_access_token(sec.second_id, token_version=0))
    client.cookies.set("csrf_token", "csrf-pair")
    client.headers["X-CSRF-Token"] = "csrf-pair"
    for method, path in (("get", "/api/v1/auth/me"), ("post", "/api/threads/search"), ("get", "/api/confirmations"), ("get", "/api/agents")):
        resp = getattr(client, method)(path, **({"json": {}} if method == "post" else {}))
        assert resp.status_code == 403, (path, resp.status_code, resp.text)
        assert resp.json()["detail"]["code"] == "account_not_permitted"


def test_the_owner_keeps_every_permission(sec) -> None:
    created = sec.owner.post("/api/threads", json={})
    assert created.status_code == 200, created.text
    tid = created.json()["thread_id"]
    assert sec.owner.get(f"/api/threads/{tid}").status_code == 200
    # threads:delete
    assert sec.owner.delete(f"/api/threads/{tid}").status_code == 200


# ── who the owner is: explicit and deterministic, never "an admin" ───────


def _live_shape(make_gateway):
    """The live install's shape: the person who owns the data has role "user"
    and was created first; an admin-role account was created later. Both are
    inserted directly (no HTTP route creates a second account any more)."""
    app, client = make_gateway(initialize=False)

    async def _accounts():
        from app.gateway.deps import get_local_provider

        provider = get_local_provider()
        first = await provider.create_user(email="first@example.com", password="F1rst!Strong", system_role="user")
        admin = await provider.create_user(email=OWNER[0], password=OWNER[1], system_role="admin")
        return str(first.id), str(admin.id)

    first_id, admin_id = client.portal.call(_accounts)
    return app, first_id, admin_id


def test_the_owner_is_the_earliest_account_not_the_admin(make_gateway) -> None:
    app, _, _ = _live_shape(make_gateway)
    _, first = login(app, "first@example.com", "F1rst!Strong")
    assert first.status_code == 200, first.text
    _, admin = login(app, *OWNER)
    assert admin.status_code == 401


def test_an_explicit_owner_setting_wins(make_gateway, monkeypatch) -> None:
    app, _, admin_id = _live_shape(make_gateway)
    _, admin = login(app, *OWNER)
    assert admin.status_code == 401
    monkeypatch.setenv("OMNI_HARNESS_OWNER_USER_ID", admin_id)
    _, admin = login(app, *OWNER)
    assert admin.status_code == 200, admin.text
    _, first = login(app, "first@example.com", "F1rst!Strong")
    assert first.status_code == 401


def test_an_explicit_owner_that_matches_no_account_admits_nobody(make_gateway, monkeypatch) -> None:
    app, _, _ = _live_shape(make_gateway)
    monkeypatch.setenv("OMNI_HARNESS_OWNER_USER_ID", "no-such-account")
    for email, password in (("first@example.com", "F1rst!Strong"), OWNER):
        _, resp = login(app, email, password)
        assert resp.status_code == 401, email
