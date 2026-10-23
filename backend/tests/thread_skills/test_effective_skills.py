"""The rule the lead agent uses for a run's skills (Feature 006).

The agent's set (its whitelist, or every enabled skill) minus what this chat
removed; with nothing removed, exactly what it was before, None included.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from omniharness.agents.lead_agent import agent as lead_agent
from omniharness.agents.lead_agent.agent import _effective_skill_names

ENABLED = {"deep-research", "spec-kit", "bootstrap"}


def _never() -> set[str]:
    raise AssertionError("the enabled list must not be read when nothing is removed")


@pytest.mark.parametrize("excluded", [None, [], (), "deep-research", 3])
def test_nothing_removed_changes_nothing(excluded):
    assert _effective_skill_names(None, excluded, enabled_skill_names=_never) is None
    assert _effective_skill_names({"spec-kit"}, excluded, enabled_skill_names=_never) == {"spec-kit"}


def test_a_removal_from_every_enabled_skill():
    assert _effective_skill_names(None, ["deep-research"], enabled_skill_names=lambda: set(ENABLED)) == {"spec-kit", "bootstrap"}


def test_a_removal_from_an_agent_whitelist():
    assert _effective_skill_names({"deep-research", "spec-kit"}, ["deep-research"], enabled_skill_names=_never) == {"spec-kit"}


def test_removing_a_skill_the_agent_lacks_adds_nothing():
    assert _effective_skill_names({"spec-kit"}, ["deep-research"], enabled_skill_names=_never) == {"spec-kit"}


def test_non_string_entries_are_ignored():
    assert _effective_skill_names({"spec-kit"}, [None, 7, "spec-kit"], enabled_skill_names=_never) == set()


def _build_capturing(cfg: dict, *, enabled=ENABLED):
    """Run _make_lead_agent with its heavy collaborators stubbed; return what
    the prompt template and the tool policy were given."""
    seen: dict = {}

    def fake_prompt(**kwargs):
        seen["prompt_skills"] = kwargs.get("available_skills")
        return "prompt"

    def fake_policy(available, *, app_config):
        seen["policy_skills"] = available
        return []

    model = SimpleNamespace(supports_thinking=False)
    app_config = SimpleNamespace(models=[SimpleNamespace(name="m")], get_model_config=lambda name: model)
    with (
        patch.object(lead_agent, "apply_prompt_template", side_effect=lambda *a, **k: fake_prompt(**k)),
        patch.object(lead_agent, "_load_enabled_skills_for_tool_policy", side_effect=fake_policy),
        patch.object(lead_agent, "_resolve_model_name", return_value="m"),
        patch.object(lead_agent, "load_agent_config", return_value=None),
        patch.object(lead_agent, "create_chat_model", return_value=object()),
        patch.object(lead_agent, "create_agent", return_value="agent"),
        patch.object(lead_agent, "_build_middlewares", return_value=[]),
        patch.object(lead_agent, "filter_tools_by_skill_allowed_tools", side_effect=lambda tools, *a, **k: tools),
        patch("omniharness.tools.get_available_tools", return_value=[]),
        patch("omniharness.tools.tools.resolve_model_tool_cap", return_value=None),
        patch("omniharness.agents.lead_agent.prompt.get_enabled_skills_for_config", return_value=[SimpleNamespace(name=n) for n in enabled]),
    ):
        lead_agent._make_lead_agent({"configurable": {}, "context": cfg}, app_config=app_config)
    return seen


def test_the_agent_gives_the_prompt_and_the_tool_policy_the_same_reduced_set():
    seen = _build_capturing({"excluded_skills": ["deep-research"]})
    assert seen["prompt_skills"] == {"spec-kit", "bootstrap"}
    assert seen["policy_skills"] == {"spec-kit", "bootstrap"}


def test_with_nothing_removed_the_agent_passes_none_as_before():
    seen = _build_capturing({})
    assert seen["prompt_skills"] is None
    assert seen["policy_skills"] is None


def test_the_real_skills_prompt_omits_a_removed_skill():
    """The section the system prompt is built from, given the agent's set."""
    from omniharness.agents.lead_agent import prompt

    skills = [SimpleNamespace(name=n, description=f"{n} does things", category="public", get_container_file_path=lambda base, n=n: f"{base}/{n}/SKILL.md") for n in sorted(ENABLED)]
    config = SimpleNamespace(skills=SimpleNamespace(container_path="/mnt/skills"), skill_evolution=SimpleNamespace(enabled=False))
    with patch.object(prompt, "get_enabled_skills_for_config", return_value=skills):
        effective = _effective_skill_names(None, ["deep-research"], enabled_skill_names=lambda: {s.name for s in skills})
        reduced = prompt.get_skills_prompt_section(effective, app_config=config)
        full = prompt.get_skills_prompt_section(None, app_config=config)
    assert "deep-research" in full
    assert "deep-research" not in reduced
    assert "spec-kit" in reduced
