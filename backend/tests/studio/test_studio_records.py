"""Agent Studio and Skill Studio records, through the production gateway (T301, T305).

An agent carries a name for people and the projects it works on, beside its
slug; a self-update by the agent keeps both. A skill made in Skill Studio goes
through the same checks the skill_manage tool's create runs, and its files are
listed and added only under the support folders.
"""

from __future__ import annotations

SKILL_MD = """---
name: status-format
description: Use when reporting the status of a project.
---

# Status report format

Open with one line: on track, at risk, or blocked.
"""


def test_an_agent_keeps_its_display_name_and_projects(studio) -> None:
    c = studio.client
    resp = c.post("/api/agents", json={"name": "evening-wrap-up", "display_name": "Evening wrap-up", "projects": ["p1"], "soul": "You wrap up."})
    assert resp.status_code == 201, resp.text
    assert (resp.json()["display_name"], resp.json()["projects"]) == ("Evening wrap-up", ["p1"])

    resp = c.put("/api/agents/evening-wrap-up", json={"projects": ["p1", "p2"], "base_version": 1})
    assert resp.status_code == 200, resp.text
    agent = c.get("/api/agents/evening-wrap-up").json()
    assert (agent["display_name"], agent["projects"]) == ("Evening wrap-up", ["p1", "p2"]), "an update of one field dropped another"

    [listed] = c.get("/api/agents").json()["agents"]
    assert listed["display_name"] == "Evening wrap-up"


def test_an_agents_self_update_keeps_what_people_set(studio) -> None:
    """update_agent rewrites config.yaml; it must not drop the Studio fields."""
    from omniharness.config.agents_config import load_agent_config
    from omniharness.runtime.user_context import reset_current_user, set_current_user
    from omniharness.tools.builtins.update_agent_tool import update_agent

    studio.client.post("/api/agents", json={"name": "researcher", "display_name": "Researcher", "projects": ["p9"]})
    runtime = type("R", (), {"context": {"agent_name": "researcher", "user_id": studio.user_id}, "tool_call_id": "t", "state": {}})()
    token = set_current_user(type("U", (), {"id": studio.user_id})())
    try:
        update_agent.func(runtime=runtime, description="Finds things")
    finally:
        reset_current_user(token)
    cfg = load_agent_config("researcher", user_id=studio.user_id)
    assert (cfg.description, cfg.display_name, cfg.projects) == ("Finds things", "Researcher", ["p9"])


def test_a_skill_is_created_and_its_files_listed_and_added(studio, allow_scans) -> None:
    c = studio.client
    resp = c.post("/api/skills/custom", json={"name": "status-format", "content": SKILL_MD})
    assert resp.status_code == 201, resp.text
    assert resp.json()["description"] == "Use when reporting the status of a project."
    assert c.post("/api/skills/custom", json={"name": "status-format", "content": SKILL_MD}).status_code == 409

    assert c.get("/api/skills/custom/status-format/files").json()["files"] == []
    resp = c.post("/api/skills/custom/status-format/files", json={"path": "references/example-report.md", "content": "# Example\n"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["files"] == [{"path": "references/example-report.md", "size": 10}]


def test_a_skill_file_outside_the_support_folders_is_refused(studio, allow_scans) -> None:
    c = studio.client
    c.post("/api/skills/custom", json={"name": "status-format", "content": SKILL_MD})
    for path in ("../escape.md", "SKILL.md", "notes.md", "references/../../x.md"):
        resp = c.post("/api/skills/custom/status-format/files", json={"path": path, "content": "x"})
        assert resp.status_code == 400, (path, resp.text)


def test_a_skill_whose_frontmatter_names_another_skill_is_refused(studio, allow_scans) -> None:
    resp = studio.client.post("/api/skills/custom", json={"name": "other", "content": SKILL_MD})
    assert resp.status_code == 400
    assert "must match" in resp.json()["detail"]


def test_a_blocked_scan_writes_nothing(studio, monkeypatch) -> None:
    import app.gateway.routers.skills as skills_router
    from omniharness.skills.security_scanner import ScanResult

    async def block(content, *, executable=False, location="", app_config=None):
        return ScanResult("block", "looks like an injection")

    monkeypatch.setattr(skills_router, "scan_skill_content", block)
    resp = studio.client.post("/api/skills/custom", json={"name": "status-format", "content": SKILL_MD})
    assert resp.status_code == 400
    assert not (studio.tmp / "skills" / "custom" / "status-format").exists()
