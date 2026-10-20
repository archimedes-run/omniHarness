"""An optional display name, per user, on the server (Feature 006).

Through `create_app()` and its lifespan. The fallback when unset is the email
before "@", returned as `display_name_effective` so every UI uses one rule.
"""

from __future__ import annotations


def test_unset_falls_back_to_the_email_local_part(gateway):
    body = gateway.client.get("/api/preferences").json()
    assert body["display_name"] is None
    assert body["display_name_effective"] == "owner"
    assert body["appearance"] == "system" and body["appearance_chosen"] is False


def test_a_set_name_is_stored_and_wins(gateway):
    put = gateway.client.put("/api/preferences/display-name", json={"display_name": "  Rishabh  "})
    assert put.status_code == 200, put.text
    assert put.json()["display_name"] == "Rishabh"
    body = gateway.client.get("/api/preferences").json()
    assert body["display_name"] == "Rishabh"
    assert body["display_name_effective"] == "Rishabh"


def test_clearing_it_returns_to_the_fallback(gateway):
    gateway.client.put("/api/preferences/display-name", json={"display_name": "R"})
    for cleared in (None, "", "   "):
        body = gateway.client.put("/api/preferences/display-name", json={"display_name": cleared}).json()
        assert body["display_name"] is None
        assert body["display_name_effective"] == "owner"


def test_the_name_and_the_appearance_live_side_by_side(gateway):
    gateway.client.put("/api/preferences/appearance", json={"appearance": "dark"})
    gateway.client.put("/api/preferences/display-name", json={"display_name": "R"})
    body = gateway.client.get("/api/preferences").json()
    assert (body["appearance"], body["appearance_chosen"], body["display_name"]) == ("dark", True, "R")


def test_a_name_too_long_is_refused(gateway):
    resp = gateway.client.put("/api/preferences/display-name", json={"display_name": "x" * 65})
    assert resp.status_code == 422
    assert gateway.client.get("/api/preferences").json()["display_name"] is None
