"""MCP servers are built in MCP Studio only.

`mcp_build` and the `mcp-server-builder` skill reach only the build run the
Studio router starts for one server: never an ordinary chat, a custom agent, a
delegate, an @-called agent, a scheduled, resumed or workflow run. The tool
checks the run again when it is called, against the server's own record.

Through the real app (MCP builder on, so the build controller is registered)
and the real tool assembly a run uses.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from omniharness.runtime.mcp.studio import STUDIO_BUILD_KEY

BUILDER_SKILL = "mcp-server-builder"


@pytest.fixture
def as_owner(studio):
    from omniharness.runtime.user_context import reset_current_user, set_current_user

    token = set_current_user(SimpleNamespace(id=studio.owner_id))
    yield studio
    reset_current_user(token)


def _lead_tools(cfg: dict) -> set[str]:
    from omniharness.agents.lead_agent.agent import lead_agent_tools

    return {t.name for t in lead_agent_tools(cfg)}


def _studio_cfg(studio, server_id: str = "srv-1", **extra) -> dict:
    return {"user_id": studio.owner_id, STUDIO_BUILD_KEY: server_id, **extra}


# -- what each kind of run is offered ------------------------------------------


def test_an_ordinary_chat_is_not_offered_mcp_build(as_owner):
    tools = _lead_tools({"user_id": as_owner.owner_id, "subagent_enabled": True})
    assert "mcp_build" not in tools
    assert "task" in tools, "the ordinary chat's tool list did not assemble"


def test_the_studio_build_run_is_offered_mcp_build_and_little_else(as_owner):
    tools = _lead_tools(_studio_cfg(as_owner, subagent_enabled=True))
    assert "mcp_build" in tools
    # No delegation, builder, ledger, artifact, preview or coding-job tools.
    for name in ("task", "call_agent", "builder_draft", "builder_save", "ledger_read", "ledger_apply", "artifact_create", "preview", "code_job", "research"):
        assert name not in tools, name


@pytest.mark.parametrize(
    "marker",
    [
        {"agent_name": "some-agent"},
        {"is_bootstrap": True},
        {"called_agent": "helper"},
        {"resume_action": {"ids": ["a1"]}},
        {"continue_action": {"agent": "x"}},
        {"turn_provenance": "synthetic-trigger", "trigger_rule_id": "rule-1"},
        {"workflow_run_id": "wf-1"},
        {"invited_agent": "general-purpose"},
        {"delegation_chain": ["lead_agent", "general-purpose"]},
        {"tool_surface": {"kind": "subagent", "subagent_type": "general-purpose"}},
    ],
    ids=lambda m: next(iter(m)),
)
def test_no_other_kind_of_run_counts_as_the_studio_build_run(marker):
    from omniharness.runtime.mcp.studio import studio_build_server_id

    assert studio_build_server_id({STUDIO_BUILD_KEY: "srv-1"}) == "srv-1"
    assert studio_build_server_id({STUDIO_BUILD_KEY: "srv-1", **marker}) is None


def test_a_scheduled_run_is_not_offered_mcp_build_even_with_the_key(as_owner):
    cfg = _studio_cfg(as_owner, turn_provenance="synthetic-trigger", trigger_rule_id="rule-1")
    assert "mcp_build" not in _lead_tools(cfg)


def test_a_delegate_or_called_agent_is_not_offered_mcp_build(as_owner):
    from omniharness.tools.builtins.task_tool import subagent_base_tools

    for called in (False, True):
        names = {t.name for t in subagent_base_tools(model_name=None, tool_groups=None, app_config=None, artifact_tools=called)}
        assert "mcp_build" not in names


def test_no_caller_gets_mcp_build_without_a_studio_server(as_owner):
    from omniharness.tools.tools import get_available_tools

    assert "mcp_build" not in {t.name for t in get_available_tools(subagent_enabled=True)}
    assert "mcp_build" in {t.name for t in get_available_tools(subagent_enabled=True, mcp_build_server_id="srv-1")}


def test_a_client_cannot_set_the_studio_key_on_a_run(as_owner):
    from app.gateway.services import apply_server_owned_context

    config = {"context": {STUDIO_BUILD_KEY: "srv-1"}, "configurable": {STUDIO_BUILD_KEY: "srv-1"}, "metadata": {STUDIO_BUILD_KEY: "srv-1"}}
    metadata = {STUDIO_BUILD_KEY: "srv-1"}
    apply_server_owned_context(config, metadata, user_id=as_owner.owner_id, selected_sources=None, agent_name=None, synthetic_rule_id=None)
    for container in (config["context"], config["configurable"], config["metadata"], metadata):
        assert STUDIO_BUILD_KEY not in container


def test_a_resumed_run_does_not_inherit_the_studio_key():
    from app.gateway.resume import _body_from_surface

    body = _body_from_surface({"kind": "lead", "config": {STUDIO_BUILD_KEY: "srv-1", "model_name": "m"}})
    assert STUDIO_BUILD_KEY not in (body.context or {})


def test_ordinary_chats_are_told_mcps_are_built_in_studio(as_owner):
    from omniharness.agents.lead_agent.prompt import mcp_studio_section

    assert "MCP Studio" in mcp_studio_section(False)
    assert mcp_studio_section(True) == ""


# -- the skill ------------------------------------------------------------------


def test_the_builder_skill_is_listed_only_to_the_studio_build_run(as_owner):
    from omniharness.agents.lead_agent.agent import _resolve_lead_inputs
    from omniharness.agents.lead_agent.prompt import get_enabled_skills_for_config, get_skills_prompt_section

    config = as_owner.client.app.state.config
    assert BUILDER_SKILL in {s.name for s in get_enabled_skills_for_config(config)}, "the skill is not enabled here, so this test proves nothing"

    ordinary = _resolve_lead_inputs({"user_id": as_owner.owner_id}, app_config=config).available_skills
    assert f"<name>{BUILDER_SKILL}</name>" not in get_skills_prompt_section(ordinary, app_config=config)

    listed = _resolve_lead_inputs({"user_id": as_owner.owner_id, "excluded_skills": []}, app_config=config).available_skills
    assert listed is None or BUILDER_SKILL not in listed

    studio = _resolve_lead_inputs(_studio_cfg(as_owner), app_config=config).available_skills
    assert studio == {BUILDER_SKILL}
    assert f"<name>{BUILDER_SKILL}</name>" in get_skills_prompt_section(studio, app_config=config)


def test_an_agent_that_names_the_builder_skill_does_not_get_it():
    from omniharness.agents.lead_agent.agent import _studio_skill_names

    assert _studio_skill_names({BUILDER_SKILL, "deep-research"}, {"agent_name": "x"}) == {"deep-research"}


def test_a_delegate_never_loads_the_builder_skill(as_owner, monkeypatch):
    from omniharness.subagents.config import SubagentConfig
    from omniharness.subagents.executor import SubagentExecutor

    for skills in (None, [BUILDER_SKILL]):
        executor = SubagentExecutor(config=SubagentConfig(name="general-purpose", description="d", system_prompt="p", skills=skills), tools=[], app_config=as_owner.client.app.state.config)
        assert BUILDER_SKILL not in {s.name for s in executor._load_skills_sync()}


# -- the tool, called -------------------------------------------------------------


class _Controller:
    def __init__(self, allowed: bool) -> None:
        self.allowed = allowed
        self.submitted: list[str] = []
        self.checked: list[dict] = []

    async def studio_build_allowed(self, **kw) -> bool:
        self.checked.append(kw)
        return self.allowed

    async def submit_source_and_test(self, *, server_id: str, user_id: str, source_code: str):
        from omniharness.runtime.mcp.controller import MCPBuildStatus

        self.submitted.append(server_id)
        return MCPBuildStatus(server_id=server_id, phase="failed", error="no runner")


def _call(context: dict, server_id: str, controller) -> str:
    from omniharness.runtime.mcp import controller as port
    from omniharness.tools.builtins.mcp_build_tool import mcp_build_tool

    previous = port.get_mcp_build_controller()
    port.set_mcp_build_controller(controller)
    try:
        runtime = SimpleNamespace(context=context, config={}, state={}, stream_writer=None, store=None, tool_call_id="c1")
        result = asyncio.run(mcp_build_tool.coroutine(server_id=server_id, source_code="print(1)\n", runtime=runtime, tool_call_id="c1"))
    finally:
        if previous is None:
            port.reset_mcp_build_controller()
        else:
            port.set_mcp_build_controller(previous)
    return str(result.update["messages"][0].content)


def test_a_forged_mcp_build_call_from_an_ordinary_chat_is_refused():
    controller = _Controller(allowed=True)
    text = _call({"user_id": "u1", "thread_id": "t1"}, "srv-1", controller)
    assert text.startswith("Not run:") and "MCP Studio" in text
    assert controller.submitted == []


def test_the_studio_build_run_cannot_build_another_server():
    controller = _Controller(allowed=True)
    text = _call({"user_id": "u1", "thread_id": "t1", STUDIO_BUILD_KEY: "srv-1"}, "srv-2", controller)
    assert text.startswith("Not run:") and "srv-1" in text
    assert controller.submitted == []


def test_a_studio_key_the_servers_record_does_not_confirm_is_refused():
    controller = _Controller(allowed=False)
    text = _call({"user_id": "u1", "thread_id": "t1", STUDIO_BUILD_KEY: "srv-1"}, "srv-1", controller)
    assert text.startswith("Not run:")
    assert controller.submitted == []
    assert controller.checked == [{"server_id": "srv-1", "thread_id": "t1", "user_id": "u1"}]


def test_the_studio_build_run_builds_its_own_server():
    controller = _Controller(allowed=True)
    text = _call({"user_id": "u1", "thread_id": "t1", STUDIO_BUILD_KEY: "srv-1"}, "srv-1", controller)
    assert '"phase": "failed"' in text
    assert controller.submitted == ["srv-1"]


# -- the server-owned link the tool checks -----------------------------------------


def test_the_router_links_the_server_to_its_build_thread_and_marks_the_run(studio, monkeypatch):
    import app.gateway.routers.mcp_studio as router

    captured: dict = {}

    async def _fake_run_agent(*args, **kwargs):
        captured["config"] = kwargs["config"]

    monkeypatch.setattr(router, "run_agent", _fake_run_agent)
    resp = studio.client.post("/api/mcp-studio/servers", json={"name": "Weather"})
    assert resp.status_code == 201, resp.text
    server_id, thread_id = resp.json()["server_id"], resp.json()["thread_id"]
    manager = studio.client.app.state.mcp_server_manager
    for _ in range(50):
        if "config" in captured:
            break
        studio.run(asyncio.sleep, 0.01)
    assert captured["config"]["context"][STUDIO_BUILD_KEY] == server_id
    assert studio.run(manager.studio_build_allowed, server_id=server_id, thread_id=thread_id, user_id=studio.owner_id) is True
    # Another thread, or another account: not the build run.
    assert studio.run(manager.studio_build_allowed, server_id=server_id, thread_id="other-thread", user_id=studio.owner_id) is False
    assert studio.run(manager.studio_build_allowed, server_id=server_id, thread_id=thread_id, user_id=studio.other_id) is False
