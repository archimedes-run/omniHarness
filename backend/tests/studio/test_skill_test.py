"""Skill Test (T305, Clarification 6), through the production gateway.

Only on request; the runtime's own path (the lead prompt from
apply_prompt_template, the model _resolve_model_name picks, built by
create_chat_model, offered the run's tools); a few tries; reported as what was
observed ("loaded 2 of 3") with the model named. Never writes.
"""

from __future__ import annotations

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

SKILL_MD = "---\nname: status-format\ndescription: Use when reporting the status of a project.\n---\n\n# Status\n"
OTHER_MD = "---\nname: cite-claims\ndescription: Use when stating facts.\n---\n\n# Cite\n"


class RecordingFake(GenericFakeChatModel):
    seen: list = []

    def bind_tools(self, tools, **kwargs):
        RecordingFake.tools = [t.name for t in tools]
        return self

    async def ainvoke(self, messages, config=None, **kwargs):
        RecordingFake.seen.append(messages)
        return await super().ainvoke(messages, config=config, **kwargs)


def _read(path: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": "read_file", "args": {"path": path, "description": "load skill"}, "id": "r"}])


@pytest.fixture
def runtime_model(monkeypatch):
    import omniharness.models as models

    state = type("S", (), {"replies": [], "calls": []})()
    RecordingFake.seen = []

    def factory(name=None, thinking_enabled=False, app_config=None, **kwargs):
        state.calls.append(name)
        return RecordingFake(messages=iter(state.replies))

    monkeypatch.setattr(models, "create_chat_model", factory)
    return state


def _skills(studio) -> None:
    for name, md in (("status-format", SKILL_MD), ("cite-claims", OTHER_MD)):
        d = studio.tmp / "skills" / "custom" / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(md)


def test_skill_test_reports_what_it_observed_and_names_the_model(studio, runtime_model) -> None:
    from omniharness.agents.lead_agent.agent import _resolve_model_name
    from omniharness.config import get_app_config

    _skills(studio)
    before = {str(p): p.stat().st_mtime for p in (studio.tmp / "skills").rglob("*")}
    runtime_model.replies = [
        _read("/mnt/skills/custom/status-format/SKILL.md"),
        AIMessage(content="Here is a tweet."),
        AIMessage(content="", tool_calls=[{"name": "read_file", "args": {"path": "/mnt/skills/custom/status-format/SKILL.md"}, "id": "a"}, {"name": "read_file", "args": {"path": "/mnt/skills/custom/cite-claims/SKILL.md"}, "id": "b"}]),
    ]
    resp = studio.client.post("/api/skills/status-format/test", json={"message": "Where are we on HackMIT judging?"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["loaded"], body["total"], body["listed"]) == (2, 3, True)
    assert [t["loaded"] for t in body["tries"]] == [True, False, True]
    assert body["tries"][2]["other_skills"] == ["cite-claims"]
    assert body["model"] == _resolve_model_name(None, app_config=get_app_config()) == runtime_model.calls[0]
    # The runtime's own prompt: the skill list with this skill's description,
    # and the run's own tools, read_file among them.
    system = RecordingFake.seen[0][0].content
    assert "<skill_system>" in system and "Use when reporting the status of a project." in system
    assert "read_file" in RecordingFake.tools
    assert {str(p): p.stat().st_mtime for p in (studio.tmp / "skills").rglob("*")} == before, "a skill test wrote something"


def test_a_skill_a_run_would_never_list_is_not_sent_to_the_model(studio, runtime_model) -> None:
    _skills(studio)
    assert studio.client.post("/api/agents", json={"name": "no-skills", "skills": []}).status_code == 201
    body = studio.client.post("/api/skills/status-format/test", json={"message": "status?", "agent_name": "no-skills"}).json()
    assert (body["listed"], body["total"], body["tries"]) == (False, 0, [])
    assert runtime_model.calls == []


def test_a_failed_try_is_reported_not_hidden(studio, runtime_model, monkeypatch) -> None:
    _skills(studio)

    async def boom(self, messages, config=None, **kwargs):
        raise TimeoutError("model took too long")

    monkeypatch.setattr(RecordingFake, "ainvoke", boom)
    body = studio.client.post("/api/skills/status-format/test", json={"message": "status?", "tries": 2}).json()
    assert body["loaded"] == 0 and [t["error"] for t in body["tries"]] == ["TimeoutError: model took too long"] * 2


def test_tries_are_few(studio) -> None:
    assert studio.client.post("/api/skills/status-format/test", json={"message": "x", "tries": 10}).status_code == 422


def test_an_unknown_skill_is_404(studio) -> None:
    assert studio.client.post("/api/skills/nope/test", json={"message": "x"}).status_code == 404
