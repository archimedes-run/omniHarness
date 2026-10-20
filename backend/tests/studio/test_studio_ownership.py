"""A second account cannot see or act on the owner's agents, grants, versions
or custom skills (review round 2, adopting the security baseline's ownership).

Real HTTP against the production gateway (the studio fixture: create_app() and
its lifespan, auth on, real cookies). The door is OPENED first
(`ownership.admits_additional_accounts`), so each refusal holds because of the
ownership check, not because the second account was turned away at sign-in.

How ownership is held:
  * agents, their config versions and their grants live under the owning
    account's own directory (users/{id}/agents, users/{id}/agent_versions,
    users/{id}/lead_agent), and every route resolves them from the caller's id,
    which the server sets (never a body field). Another account's id reaches
    another directory, so the owner's agent is a 404 to it.
  * a custom skill records its owner in its version history (owner_id), and
    every /skills/custom/{name} route and Skill Test checks it with
    ownership.require_access; lists show only the caller's.
  * grant uses are audit lines carrying the user id; the route filters on it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

SECOND = ("second@example.com", "An0ther!Pass77")
SKILL_MD = "---\nname: status-format\ndescription: Use when reporting status.\n---\n\n# Status\n"


@pytest.fixture
def other(studio, monkeypatch) -> TestClient:
    from app.gateway.deps import get_local_provider

    async def create():
        return await get_local_provider().create_user(email=SECOND[0], password=SECOND[1], system_role="user")

    studio.client.portal.call(create)
    monkeypatch.setattr("app.gateway.ownership.admits_additional_accounts", lambda: True)
    client = TestClient(studio.client.app)
    resp = client.post("/api/v1/auth/login/local", data={"username": SECOND[0], "password": SECOND[1]})
    assert resp.status_code == 200, resp.text
    if client.cookies.get("csrf_token"):
        client.headers["X-CSRF-Token"] = client.cookies.get("csrf_token")
    assert client.get("/api/agents").status_code == 200, "the second account is not admitted, so these tests would pass for the wrong reason"
    return client


def _owner_setup(c) -> None:
    assert c.post("/api/agents", json={"name": "wrap-up", "soul": "the owner's", "description": "mine"}).status_code == 201
    version = c.get("/api/studio/agents/wrap-up/autonomy").json()["version"]
    assert c.put("/api/studio/agents/wrap-up/autonomy", json={"granted": ["tasks"], "base_version": version}).status_code == 200
    assert c.put("/api/agents/wrap-up", json={"description": "edited", "base_version": version + 1}).status_code == 200
    lead = c.get("/api/studio/agents/lead_agent/autonomy").json()["version"]
    assert c.put("/api/studio/agents/lead_agent/autonomy", json={"granted": ["notes"], "base_version": lead}).status_code == 200


def test_a_second_account_cannot_see_undo_grant_or_edit_the_owners_agent(studio, other) -> None:
    owner = studio.client
    _owner_setup(owner)

    assert other.get("/api/agents/wrap-up").status_code == 404
    assert "wrap-up" not in [a["name"] for a in other.get("/api/agents").json()["agents"]]
    assert other.get("/api/agents/wrap-up/versions").status_code == 404
    assert other.post("/api/agents/wrap-up/undo", json={"to_version": 1, "base_version": 3}).status_code == 404
    assert other.get("/api/studio/agents/wrap-up/autonomy").status_code == 404
    assert other.put("/api/studio/agents/wrap-up/autonomy", json={"granted": ["tasks", "notes", "archive"], "base_version": 3}).status_code == 404
    assert other.put("/api/agents/wrap-up", json={"description": "hijacked"}).status_code == 404
    assert other.delete("/api/agents/wrap-up").status_code == 404
    assert other.get("/api/studio/agents/wrap-up/grant-uses").json() == []

    # The lead agent: the second account's writes land in its own namespace.
    lead = other.get("/api/studio/agents/lead_agent/autonomy").json()
    assert not any(k["granted"] for k in lead["classes"])
    assert other.put("/api/studio/agents/lead_agent/autonomy", json={"granted": [], "base_version": lead["version"]}).status_code == 200

    # The owner's records are exactly as they were.
    mine = owner.get("/api/agents/wrap-up").json()
    assert (mine["description"], mine["soul"]) == ("edited", "the owner's")
    assert [k["id"] for k in owner.get("/api/studio/agents/wrap-up/autonomy").json()["classes"] if k["granted"]] == ["tasks"]
    assert [k["id"] for k in owner.get("/api/studio/agents/lead_agent/autonomy").json()["classes"] if k["granted"]] == ["notes"]
    assert owner.get("/api/agents/wrap-up/versions").json()["current"] == 3


def test_a_second_account_cannot_see_undo_or_edit_the_owners_skill(studio, other, allow_scans) -> None:
    owner = studio.client
    assert owner.post("/api/skills/custom", json={"name": "status-format", "content": SKILL_MD}).status_code == 201
    assert owner.put("/api/skills/custom/status-format", json={"content": SKILL_MD + "\nv2\n", "base_version": 1}).status_code == 200

    base = "/api/skills/custom/status-format"
    assert other.get(base).status_code == 404
    assert other.get(f"{base}/versions").status_code == 404
    assert other.get(f"{base}/history").status_code == 404
    assert other.get(f"{base}/files").status_code == 404
    assert other.post(f"{base}/undo", json={"to_version": 1, "base_version": 2}).status_code == 404
    assert other.put(base, json={"content": SKILL_MD + "\nhijacked\n", "base_version": 2}).status_code == 404
    assert other.post(f"{base}/files", json={"path": "references/x.md", "content": "x"}).status_code == 404
    assert other.post(f"{base}/rollback", json={"history_index": 0}).status_code == 404
    assert other.delete(base).status_code == 404
    assert other.post("/api/skills/status-format/test", json={"message": "status?"}).status_code == 404
    assert "status-format" not in [s["name"] for s in other.get("/api/skills/custom").json()["skills"]]
    assert "status-format" not in [s["name"] for s in other.get("/api/skills").json()["skills"]]

    # Positive control: the owner still has it, untouched.
    assert owner.get(base).json()["content"] == SKILL_MD + "\nv2\n"
    assert "status-format" in [s["name"] for s in owner.get("/api/skills/custom").json()["skills"]]


def test_a_skill_belongs_to_the_account_that_made_it(studio, other, allow_scans) -> None:
    """The recorded owner is what decides: the second account reaches its own
    skill, and the owner account does not reach it either."""
    md = SKILL_MD.replace("status-format", "their-skill")
    assert other.post("/api/skills/custom", json={"name": "their-skill", "content": md}).status_code == 201
    assert other.get("/api/skills/custom/their-skill").status_code == 200
    assert other.put("/api/skills/custom/their-skill", json={"content": md + "\nv2\n", "base_version": 1}).status_code == 200
    assert studio.client.get("/api/skills/custom/their-skill").status_code == 404
    assert "their-skill" not in [s["name"] for s in studio.client.get("/api/skills/custom").json()["skills"]]
