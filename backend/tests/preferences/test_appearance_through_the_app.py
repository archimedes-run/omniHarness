"""Settings > Appearance is remembered per user, on the server (Feature 006).

Through `create_app()` and its lifespan: if startup stops registering the
preferences repository, or the router is not mounted, these fail.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_a_user_who_never_chose_gets_system_and_is_told_it_is_the_default(gateway):
    resp = gateway.client.get("/api/preferences/appearance")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"appearance": "system", "chosen": False}


def test_the_choice_is_stored_and_read_back(gateway):
    put = gateway.client.put("/api/preferences/appearance", json={"appearance": "dark"})
    assert put.status_code == 200, put.text
    assert put.json() == {"appearance": "dark", "chosen": True}
    assert gateway.client.get("/api/preferences/appearance").json() == {"appearance": "dark", "chosen": True}

    gateway.client.put("/api/preferences/appearance", json={"appearance": "light"})
    assert gateway.client.get("/api/preferences/appearance").json() == {"appearance": "light", "chosen": True}


def test_it_is_persisted_in_the_gateway_database(gateway):
    from omniharness.persistence.user_preferences import UserPreferenceRow

    gateway.client.put("/api/preferences/appearance", json={"appearance": "dark"})
    me = gateway.client.get("/api/v1/auth/me").json()
    user_id = str(me.get("id") or me.get("user", {}).get("id"))

    repo = gateway.app.state.user_preference_repo

    async def read():
        async with repo._sf() as session:
            return await session.get(UserPreferenceRow, user_id)

    # On the app's own event loop: the session factory is bound to it.
    row = gateway.client.portal.call(read)
    assert row is not None and row.appearance == "dark"


def test_an_unknown_appearance_is_refused(gateway):
    resp = gateway.client.put("/api/preferences/appearance", json={"appearance": "sepia"})
    assert resp.status_code == 422
    assert gateway.client.get("/api/preferences/appearance").json()["chosen"] is False


def test_it_needs_a_signed_in_user(gateway):
    anonymous = TestClient(gateway.app)
    assert anonymous.get("/api/preferences/appearance").status_code == 401
