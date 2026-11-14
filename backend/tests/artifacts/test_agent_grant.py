"""Grants are never silent (Spec 012): the artifact tools reach the built-in
assistant and its delegates, and a custom agent only when its allowlist names
`builtin:artifacts`. Driven through the real tool assembly a run uses."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

ARTIFACT = {"artifact_create", "artifact_update", "artifact_read", "artifact_list"}


@pytest.fixture
def as_owner(gateway):
    from omniharness.runtime.user_context import reset_current_user, set_current_user

    token = set_current_user(SimpleNamespace(id=gateway.user_id))
    yield gateway
    reset_current_user(token)


def _lead_tools(gw, agent_name=None) -> set[str]:
    from omniharness.agents.lead_agent.agent import lead_agent_tools

    cfg = {"user_id": gw.user_id, "subagent_enabled": True}
    if agent_name:
        cfg["agent_name"] = agent_name
    return {t.name for t in lead_agent_tools(cfg)}


def _make(gw, name, **fields):
    resp = gw.client.post("/api/agents", json={"name": name, "soul": "x", "skills": [], **fields})
    assert resp.status_code == 201, resp.text


def test_the_built_in_assistant_has_all_four(as_owner):
    assert ARTIFACT <= _lead_tools(as_owner)


def test_a_legacy_custom_agent_has_none_and_studio_shows_it_unticked(as_owner):
    _make(as_owner, "legacy-writer", tool_groups=["web"])
    assert as_owner.client.get("/api/agents/legacy-writer").json().get("tools") is None, "a legacy agent has no allowlist"
    assert not (ARTIFACT & _lead_tools(as_owner, "legacy-writer"))
    # The integration is offered for granting, and nothing about the agent says it has it.
    catalog = as_owner.client.get("/api/studio/tool-catalog").json()["integrations"]
    artifacts = next(i for i in catalog if i["id"] == "builtin:artifacts")
    assert {t["name"] for t in artifacts["tools"]} == ARTIFACT


def test_a_custom_agent_with_the_grant_has_all_four(as_owner):
    _make(as_owner, "granted-writer", tools={"integrations": ["builtin:artifacts"], "tools": sorted(ARTIFACT)})
    assert ARTIFACT <= _lead_tools(as_owner, "granted-writer")


def test_saving_a_legacy_agents_page_changes_nothing_unintended(as_owner):
    """The Studio page saves the ticks it shows; artifacts are unticked, so the
    saved allowlist leaves them out and the agent still has none."""
    _make(as_owner, "legacy-saver", tool_groups=["web"])
    before = _lead_tools(as_owner, "legacy-saver")
    current = as_owner.client.get("/api/agents/legacy-saver").json()
    shown = sorted(before - {"present_files", "ask_clarification", "view_image", "task", "tool_search", "call_agent", "write_todos"})
    resp = as_owner.client.put("/api/agents/legacy-saver", json={"tools": {"integrations": ["builtin:web"], "tools": shown}, "base_version": current["version"]})
    assert resp.status_code == 200, resp.text
    after = _lead_tools(as_owner, "legacy-saver")
    assert not (ARTIFACT & after)
    assert after <= before | {"research"} or after == before


def test_delegates_inherit_from_the_agent_that_delegates(as_owner):
    from omniharness.agents.lead_agent.agent import lead_run_metadata
    from omniharness.tools.builtins.task_tool import subagent_base_tools

    _make(as_owner, "legacy-boss", tool_groups=["web"])
    lead_meta = lead_run_metadata({"user_id": as_owner.user_id})
    custom_meta = lead_run_metadata({"user_id": as_owner.user_id, "agent_name": "legacy-boss"})
    assert lead_meta["artifact_tools"] is True and custom_meta["artifact_tools"] is False
    of_lead = {t.name for t in subagent_base_tools(model_name=None, tool_groups=None, app_config=None, artifact_tools=lead_meta["artifact_tools"])}
    of_custom = {t.name for t in subagent_base_tools(model_name=None, tool_groups=["web"], app_config=None, tool_access=custom_meta["tool_access"], artifact_tools=custom_meta["artifact_tools"])}
    assert ARTIFACT <= of_lead and not (ARTIFACT & of_custom)
