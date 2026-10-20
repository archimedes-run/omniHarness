"""One versioned store for agent and skill config, through the production gateway.

Every write is a version (who, when, what changed, source); undo restores an
earlier version as a new one; a write based on an old version is refused.
"""

from __future__ import annotations

import yaml

SKILL_MD = "---\nname: status-format\ndescription: Use when reporting status.\n---\n\n# Status\n"


def _versions(c, name):
    return c.get(f"/api/agents/{name}/versions").json()


def test_agent_writes_are_versions_with_undo_and_stale_refusal(studio) -> None:
    c = studio.client
    created = c.post("/api/agents", json={"name": "wrap-up", "soul": "v1 soul", "description": "first", "source": "draft"}).json()
    assert created["version"] == 1

    edited = c.put("/api/agents/wrap-up", json={"soul": "v2 soul", "base_version": 1})
    assert edited.status_code == 200, edited.text
    assert edited.json()["version"] == 2

    # A second tab still on version 1 cannot overwrite version 2.
    stale = c.put("/api/agents/wrap-up", json={"description": "from an old tab", "base_version": 1})
    assert stale.status_code == 409
    assert "version 1" in stale.json()["detail"] and "version 2" in stale.json()["detail"]
    assert c.get("/api/agents/wrap-up").json()["description"] == "first"

    history = _versions(c, "wrap-up")
    assert history["current"] == 2
    assert [(v["version"], v["source"], v["changed"]) for v in history["versions"]] == [(2, "manual", ["soul"]), (1, "draft", ["created"])]
    assert history["versions"][0]["who"] == f"user:{studio.user_id}"

    # Undo restores version 1 AS version 3; nothing is rewritten.
    undone = c.post("/api/agents/wrap-up/undo", json={"to_version": 1, "base_version": 2})
    assert undone.status_code == 200, undone.text
    assert [(v["version"], v["source"]) for v in undone.json()["versions"]][:1] == [(3, "undo")]
    assert c.get("/api/agents/wrap-up").json()["soul"] == "v1 soul"
    assert c.post("/api/agents/wrap-up/undo", json={"to_version": 2, "base_version": 2}).status_code == 409


def test_a_deleted_agent_comes_back_with_undo(studio) -> None:
    c = studio.client
    c.post("/api/agents", json={"name": "gone-soon", "soul": "keep me"})
    assert c.delete("/api/agents/gone-soon").status_code == 204
    assert c.get("/api/agents/gone-soon").status_code == 404
    history = _versions(c, "gone-soon")
    assert history["versions"][0]["deleted"] is True
    assert c.post("/api/agents/gone-soon/undo", json={"to_version": 1, "base_version": 2}).status_code == 200
    assert c.get("/api/agents/gone-soon").json()["soul"] == "keep me"


def test_an_agent_from_before_versioning_gets_a_baseline(studio) -> None:
    """Its first edit can be undone back to what it was."""
    agent_dir = studio.tmp / "home" / "users" / studio.user_id / "agents" / "old-timer"
    agent_dir.mkdir(parents=True)
    (agent_dir / "config.yaml").write_text(yaml.safe_dump({"name": "old-timer", "description": "from before"}))
    (agent_dir / "SOUL.md").write_text("old soul")
    c = studio.client
    assert c.get("/api/agents/old-timer").json()["version"] == 0
    assert c.put("/api/agents/old-timer", json={"soul": "new soul", "base_version": 0}).status_code == 200
    history = _versions(c, "old-timer")
    assert [(v["version"], v["source"]) for v in history["versions"]] == [(2, "manual"), (1, "existing")]
    c.post("/api/agents/old-timer/undo", json={"to_version": 1, "base_version": 2})
    assert c.get("/api/agents/old-timer").json()["soul"] == "old soul"


def test_an_agents_self_update_is_a_proposal_by_the_agent(studio) -> None:
    from omniharness.runtime.user_context import reset_current_user, set_current_user
    from omniharness.tools.builtins.update_agent_tool import update_agent

    studio.client.post("/api/agents", json={"name": "researcher", "soul": "s"})
    runtime = type("R", (), {"context": {"agent_name": "researcher"}, "tool_call_id": "t"})()
    token = set_current_user(type("U", (), {"id": studio.user_id})())
    try:
        update_agent.func(runtime=runtime, description="Finds things")
    finally:
        reset_current_user(token)
    latest = _versions(studio.client, "researcher")["versions"][0]
    assert (latest["who"], latest["source"], latest["changed"]) == ("agent:researcher", "proposal", ["config.description"])


def test_skill_writes_are_versions_with_undo_and_stale_refusal(studio, allow_scans) -> None:
    c = studio.client
    assert c.post("/api/skills/custom", json={"name": "status-format", "content": SKILL_MD}).json()["version"] == 1
    edited = c.put("/api/skills/custom/status-format", json={"content": SKILL_MD.replace("# Status", "# Status v2"), "base_version": 1, "source": "draft"})
    assert edited.status_code == 200, edited.text
    assert edited.json()["version"] == 2
    stale = c.put("/api/skills/custom/status-format", json={"content": SKILL_MD, "base_version": 1})
    assert stale.status_code == 409

    added = c.post("/api/skills/custom/status-format/files", json={"path": "references/a.md", "content": "A", "base_version": 2})
    assert added.status_code == 200, added.text
    history = c.get("/api/skills/custom/status-format/versions").json()
    assert [(v["version"], v["source"], v["changed"]) for v in history["versions"]] == [(3, "manual", ["references/a.md"]), (2, "draft", ["SKILL.md"]), (1, "manual", ["created"])]

    undone = c.post("/api/skills/custom/status-format/undo", json={"to_version": 1, "base_version": 3})
    assert undone.status_code == 200, undone.text
    assert "# Status v2" not in c.get("/api/skills/custom/status-format").json()["content"]
    assert c.get("/api/skills/custom/status-format/files").json()["files"] == [], "undo kept a file the old version did not have"


def test_a_deleted_skill_comes_back_with_undo(studio, allow_scans) -> None:
    c = studio.client
    c.post("/api/skills/custom", json={"name": "status-format", "content": SKILL_MD})
    assert c.delete("/api/skills/custom/status-format").status_code == 200
    assert c.get("/api/skills/custom/status-format").status_code == 404
    assert c.post("/api/skills/custom/status-format/undo", json={"to_version": 1, "base_version": 2}).status_code == 200
    assert c.get("/api/skills/custom/status-format").json()["content"] == SKILL_MD


def _granted(c, name) -> list[str]:
    return [k["id"] for k in c.get(f"/api/studio/agents/{name}/autonomy").json()["classes"] if k["granted"]]


def _grant(c, name, granted: list[str]) -> None:
    version = c.get(f"/api/studio/agents/{name}/autonomy").json()["version"]
    assert c.put(f"/api/studio/agents/{name}/autonomy", json={"granted": granted, "base_version": version}).status_code == 200


def test_undo_restores_content_and_never_brings_back_a_revoked_grant(studio) -> None:
    """Undo restores content only. A version taken while a grant was on does
    not switch it back on: the grant changes only through Autonomy's Save."""
    c = studio.client
    c.post("/api/agents", json={"name": "wrap-up", "soul": "s", "description": "one"})  # v1
    _grant(c, "wrap-up", ["tasks"])  # v2
    assert c.put("/api/agents/wrap-up", json={"description": "two", "base_version": 2}).status_code == 200  # v3
    _grant(c, "wrap-up", [])  # v4: revoked
    resp = c.post("/api/agents/wrap-up/undo", json={"to_version": 3, "base_version": 4})
    assert resp.status_code == 200, resp.text
    assert c.get("/api/agents/wrap-up").json()["description"] == "two"
    assert _granted(c, "wrap-up") == [], "undo silently restored a revoked grant"
    # What the runtime reads agrees (config.yaml, via the store).
    from omniharness.config import config_versions

    assert config_versions.current_agent_snapshot(studio.user_id, "wrap-up")["config"].get("autonomy") == []


def test_undo_never_silently_drops_a_grant_either(studio) -> None:
    c = studio.client
    c.post("/api/agents", json={"name": "wrap-up", "soul": "s", "description": "one"})  # v1
    assert c.put("/api/agents/wrap-up", json={"description": "two", "base_version": 1}).status_code == 200  # v2
    _grant(c, "wrap-up", ["tasks", "notes"])  # v3
    assert c.post("/api/agents/wrap-up/undo", json={"to_version": 1, "base_version": 3}).status_code == 200
    assert c.get("/api/agents/wrap-up").json()["description"] == "one"
    assert _granted(c, "wrap-up") == ["tasks", "notes"]


def test_only_the_autonomy_action_changes_grants(studio) -> None:
    """Any other writer of an agent's config (the store's other callers, the
    agent updating itself, setup in chat) keeps the grants as they are."""
    from omniharness.config import config_versions

    c = studio.client
    c.post("/api/agents", json={"name": "wrap-up", "soul": "s"})
    snapshot = config_versions.current_agent_snapshot(studio.user_id, "wrap-up")
    smuggled = {**snapshot, "config": {**snapshot["config"], "autonomy": ["tasks", "notes", "archive"]}}
    config_versions.write_agent(studio.user_id, "wrap-up", smuggled, who="agent:wrap-up", source="proposal")
    assert _granted(c, "wrap-up") == []
