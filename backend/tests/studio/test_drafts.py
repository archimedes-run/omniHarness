"""Draft from one sentence, through the production gateway (T302, FR-301).

The model fills the large fields and the result comes back for review:
nothing is written until the user saves. The model is the one a run would
use, and its suggestions are checked against what exists.
"""

from __future__ import annotations

import json
from pathlib import Path

AGENT_REPLY = json.dumps(
    {
        "display_name": "Evening wrap-up",
        "description": "Tells you what moved and what's stuck",
        "instructions": "You are my evening wrap-up.\n1. What moved today.\n2. What is stuck.",
        "tool_groups": ["web", "teleport"],
        "skills": ["ghost-skill"],
    }
)


def _tree(root: Path) -> dict[str, float]:
    return {str(p): p.stat().st_mtime for p in root.rglob("*")} if root.exists() else {}


def test_an_agent_draft_fills_the_fields_and_writes_nothing(studio, fake_model) -> None:
    from omniharness.agents.lead_agent.agent import _resolve_model_name
    from omniharness.config import get_app_config

    before = _tree(studio.tmp / "home"), _tree(studio.tmp / "skills")
    fake_model.replies.append(f"Here it is:\n```json\n{AGENT_REPLY}\n```")

    resp = studio.client.post("/api/drafts/agent", json={"sentence": "Every weekday evening, tell me what moved and what's stuck"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["agent"]["display_name"] == "Evening wrap-up"
    assert body["agent"]["instructions"].startswith("You are my evening wrap-up.")
    # Only what exists: the made-up group and skill are left out, and named.
    assert body["agent"]["tool_groups"] == ["web"]
    assert body["agent"]["skills"] == []
    assert sorted(body["dropped"]) == ["ghost-skill", "teleport"]
    # The model a run would use, by the runtime's own resolver.
    assert fake_model.calls == [_resolve_model_name(None, app_config=get_app_config())] == [body["model"]]
    assert (_tree(studio.tmp / "home"), _tree(studio.tmp / "skills")) == before, "a draft wrote something"
    assert studio.client.get("/api/agents").json()["agents"] == []


def test_an_agents_draft_uses_that_agents_model(studio, fake_model, monkeypatch) -> None:
    """An agent with its own model drafts with it, as its runs would."""
    import app.gateway.routers.drafts as drafts

    seen = []
    monkeypatch.setattr(drafts, "_resolve_model_name", lambda requested, app_config=None: seen.append(requested) or "default")
    studio.client.post("/api/agents", json={"name": "researcher", "model": "default"})
    fake_model.replies.append(AGENT_REPLY)
    assert studio.client.post("/api/drafts/agent", json={"sentence": "x", "agent_name": "researcher"}).status_code == 200
    assert seen == ["default"]


def test_a_skill_draft_returns_when_and_body(studio, fake_model) -> None:
    fake_model.replies.append(json.dumps({"description": "Use when reporting status.", "body": "# Status\n\n- Moved"}))
    resp = studio.client.post("/api/drafts/skill", json={"sentence": "how I want status reported"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["skill"] == {"description": "Use when reporting status.", "body": "# Status\n\n- Moved"}
    assert not any((studio.tmp / "skills" / "custom").iterdir())


def test_an_unreadable_draft_says_so(studio, fake_model) -> None:
    fake_model.replies.append("I cannot help with that.")
    resp = studio.client.post("/api/drafts/agent", json={"sentence": "x"})
    assert resp.status_code == 502
    assert "not readable" in resp.json()["detail"]


def test_an_unknown_kind_is_refused(studio) -> None:
    assert studio.client.post("/api/drafts/project", json={"sentence": "x"}).status_code == 422
