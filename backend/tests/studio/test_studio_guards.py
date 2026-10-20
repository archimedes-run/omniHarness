"""Agent and Skill Studio guards, through the production gateway (review round 2).

* the autonomy routes obey the custom-agent API switch, like /api/agents;
* Skill Test and Draft read the CALLER's agent (user_id passed explicitly,
  not left to the ambient user context);
* a custom skill is capped: SKILL.md at most 64 KiB, at most 50 files
  (SKILL.md included), at most 2 MiB in all, on every write path (HTTP,
  the archive installer, and the store the agent's skill_manage uses).
"""

from __future__ import annotations

import io
import zipfile
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

SKILL_MD = "---\nname: status-format\ndescription: Use when reporting status.\n---\n\n# Status\n"


@pytest.fixture
def agents_api_off(monkeypatch):
    import app.gateway.routers.agents as agents

    monkeypatch.setattr(agents, "get_agents_api_config", lambda: SimpleNamespace(enabled=False))


def test_the_autonomy_routes_are_off_when_the_agents_api_is_off(studio, agents_api_off) -> None:
    c = studio.client
    assert c.get("/api/agents").status_code == 403  # the switch, as the agents API sees it
    assert c.get("/api/studio/agents/lead_agent/autonomy").status_code == 403
    assert c.put("/api/studio/agents/lead_agent/autonomy", json={"granted": ["tasks"], "base_version": 0}).status_code == 403
    assert c.get("/api/studio/agents/lead_agent/grant-uses").status_code == 403


@pytest.fixture
def someone_else_ambient(monkeypatch):
    """The ambient user, as agents_config would read it implicitly, is not the
    caller: only an explicitly passed user_id finds the caller's agent."""
    import omniharness.config.agents_config as agents_config

    monkeypatch.setattr(agents_config, "get_effective_user_id", lambda: "someone-else")


def test_skill_test_reads_the_callers_agent(studio, someone_else_ambient, monkeypatch) -> None:
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

    import omniharness.models as models

    seen = []

    class Recording(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

        async def ainvoke(self, messages, config=None, **kwargs):
            seen.append(messages[0].content)
            return await super().ainvoke(messages, config=config, **kwargs)

    monkeypatch.setattr(models, "create_chat_model", lambda **kw: Recording(messages=iter([AIMessage(content="no")])))
    d = studio.tmp / "skills" / "custom" / "status-format"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(SKILL_MD)
    assert studio.client.post("/api/agents", json={"name": "researcher", "soul": "SOUL-MARKER-7f3"}).status_code == 201
    resp = studio.client.post("/api/skills/status-format/test", json={"message": "status?", "tries": 1, "agent_name": "researcher"})
    assert resp.status_code == 200, resp.text
    assert seen and "SOUL-MARKER-7f3" in seen[0]


def test_a_draft_reads_the_callers_agent(studio, fake_model, someone_else_ambient, monkeypatch) -> None:
    import app.gateway.routers.drafts as drafts

    asked = []
    monkeypatch.setattr(drafts, "_resolve_model_name", lambda requested, app_config=None: asked.append(requested) or "default")
    studio.client.post("/api/agents", json={"name": "researcher", "model": "default"})
    fake_model.replies.append('{"instructions": "x"}')
    assert studio.client.post("/api/drafts/agent", json={"sentence": "x", "agent_name": "researcher"}).status_code == 200
    assert asked == ["default"], "the draft did not find the caller's agent, so it did not use its model"


def test_skill_md_over_64_kib_is_refused_and_nothing_is_written(studio, allow_scans) -> None:
    c = studio.client
    big = SKILL_MD + "x" * (64 * 1024)
    resp = c.post("/api/skills/custom", json={"name": "status-format", "content": big})
    assert resp.status_code == 400 and "64 KiB" in resp.json()["detail"], resp.text
    assert not (studio.tmp / "skills" / "custom" / "status-format").exists()
    assert c.post("/api/skills/custom", json={"name": "status-format", "content": SKILL_MD}).status_code == 201
    edit = c.put("/api/skills/custom/status-format", json={"content": big, "base_version": 1})
    assert edit.status_code == 400 and "64 KiB" in edit.json()["detail"]
    assert c.get("/api/skills/custom/status-format").json()["content"] == SKILL_MD


def test_a_skill_holds_at_most_50_files(studio, allow_scans) -> None:
    c = studio.client
    assert c.post("/api/skills/custom", json={"name": "status-format", "content": SKILL_MD}).status_code == 201
    for i in range(49):
        assert c.post("/api/skills/custom/status-format/files", json={"path": f"references/r{i}.md", "content": "r"}).status_code == 200
    resp = c.post("/api/skills/custom/status-format/files", json={"path": "references/one-too-many.md", "content": "r"})
    assert resp.status_code == 400 and "at most 50" in resp.json()["detail"], resp.text
    assert len(c.get("/api/skills/custom/status-format/files").json()["files"]) == 49


def test_a_skill_holds_at_most_2_mib(studio, allow_scans) -> None:
    c = studio.client
    assert c.post("/api/skills/custom", json={"name": "status-format", "content": SKILL_MD}).status_code == 201
    for i in range(4):
        assert c.post("/api/skills/custom/status-format/files", json={"path": f"references/big{i}.md", "content": "y" * 500_000}).status_code == 200
    resp = c.post("/api/skills/custom/status-format/files", json={"path": "references/big4.md", "content": "y" * 500_000})
    assert resp.status_code == 400 and "2 MiB" in resp.json()["detail"], resp.text


def test_an_installed_archive_obeys_the_same_limits(studio) -> None:
    from omniharness.config.paths import get_paths

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("status-format/SKILL.md", SKILL_MD)
        for i in range(50):
            zf.writestr(f"status-format/references/r{i}.md", "r")
    target = get_paths().resolve_virtual_path("t-install", "/mnt/user-data/outputs/status-format.skill", user_id=studio.user_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(buf.getvalue())
    resp = studio.client.post("/api/skills/install", json={"thread_id": "t-install", "path": "/mnt/user-data/outputs/status-format.skill"})
    assert resp.status_code == 400 and "at most 50" in resp.json()["detail"], resp.text
    assert not (studio.tmp / "skills" / "custom" / "status-format").exists()
