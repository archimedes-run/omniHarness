"""Revealing a stored MCP secret: owner only, password re-entered, logged by name.

Through the real app (create_app + lifespan, auth on, login cookies).
"""

from __future__ import annotations

import logging

from .conftest import OTHER_EMAIL, OTHER_PASSWORD, OWNER_PASSWORD

SECRET_VALUE = "ghp_SuperSecretValue_8f2k1"
KEY = "GITHUB_TOKEN"


def _store(studio) -> str:
    server_id = studio.make_server()
    resp = studio.client.put(f"/api/mcp-studio/servers/{server_id}/secrets", json={"secrets": {KEY: SECRET_VALUE}})
    assert resp.status_code == 200, resp.text
    return server_id


def _reveal(studio, server_id: str, password: str, key: str = KEY):
    return studio.client.post(f"/api/mcp-studio/servers/{server_id}/secrets/reveal", json={"key_name": key, "password": password})


def test_the_owner_with_the_right_password_sees_the_value(studio):
    server_id = _store(studio)
    resp = _reveal(studio, server_id, OWNER_PASSWORD)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"values": {KEY: SECRET_VALUE}}


def test_a_wrong_password_is_refused_without_the_value(studio):
    server_id = _store(studio)
    resp = _reveal(studio, server_id, "not-my-password")
    assert resp.status_code == 403, resp.text
    assert SECRET_VALUE not in resp.text


def test_another_account_cannot_reveal_the_owners_secret(studio):
    server_id = _store(studio)
    studio.login(OTHER_EMAIL, OTHER_PASSWORD)
    # Its own correct password does not help: the server is not theirs, and
    # the answer is the same 404 as a server that does not exist.
    resp = _reveal(studio, server_id, OTHER_PASSWORD)
    assert resp.status_code == 404, resp.text
    # Refused at the ownership check, not merely because the vault holds
    # nothing under this account's id.
    assert resp.json()["detail"] == "MCP server not found"
    assert SECRET_VALUE not in resp.text
    assert _reveal(studio, "no-such-server", OTHER_PASSWORD).status_code == 404


def test_the_old_get_reveal_route_is_gone(studio):
    server_id = _store(studio)
    resp = studio.client.get(f"/api/mcp-studio/servers/{server_id}/secrets/reveal")
    assert resp.status_code in (404, 405), resp.text
    assert SECRET_VALUE not in resp.text
    # A password in the query string is not read either.
    resp = studio.client.post(f"/api/mcp-studio/servers/{server_id}/secrets/reveal?password={OWNER_PASSWORD}&key_name={KEY}")
    assert resp.status_code == 422, resp.text
    assert SECRET_VALUE not in resp.text


def test_repeated_wrong_passwords_lock_reveal(studio):
    server_id = _store(studio)
    for _ in range(5):
        assert _reveal(studio, server_id, "guess").status_code == 403
    resp = _reveal(studio, server_id, OWNER_PASSWORD)
    assert resp.status_code == 429, resp.text
    assert SECRET_VALUE not in resp.text


def test_an_account_without_a_password_is_told_why(studio):
    server_id = _store(studio)
    from app.gateway.deps import get_local_provider

    provider = get_local_provider()
    user = studio.run(provider.get_user, studio.owner_id)
    user.password_hash = None
    studio.run(provider.update_user, user)
    resp = _reveal(studio, server_id, OWNER_PASSWORD)
    assert resp.status_code == 400, resp.text
    assert "without a password" in resp.json()["detail"]
    assert SECRET_VALUE not in resp.text


def test_each_call_is_logged_by_key_name_never_by_value(studio, caplog):
    server_id = _store(studio)
    caplog.set_level(logging.INFO, logger="app.gateway.routers.mcp_studio")
    assert _reveal(studio, server_id, "wrong").status_code == 403
    assert _reveal(studio, server_id, OWNER_PASSWORD).status_code == 200
    lines = [r.getMessage() for r in caplog.records if "mcp secret reveal" in r.getMessage()]
    assert len(lines) == 2, lines
    assert f"user={studio.owner_id}" in lines[0] and f"server={server_id}" in lines[0]
    assert f"key={KEY}" in lines[0] and "outcome=wrong_password" in lines[0]
    assert f"key={KEY}" in lines[1] and "outcome=revealed" in lines[1]
    assert SECRET_VALUE not in caplog.text
    assert OWNER_PASSWORD not in caplog.text
