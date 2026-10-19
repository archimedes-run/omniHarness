"""The policy layer is on by default and fails CLOSED (audit P-1, P-2).

Before: `PolicyConfig.enabled` defaulted False and only the gitignored
config.yaml turned it on, so a fresh clone ran with no gate (Article XIV). And
when the policy middleware failed to build, `build_policy_middleware` returned
None — agents ran with no gate at all, behind one log line. Article II: no
feature may bypass the policy engine.

Now: on unless explicitly opted out, and when it is on but cannot be built,
every tool call is refused with the reason.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool as make_tool

from omniharness.agents.middlewares import policy_hook
from omniharness.config.policy_config import PolicyConfig

RAN: list[str] = []


class _ToolCallingModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


@make_tool
def write_note(text: str) -> str:
    """Write a note."""
    RAN.append(text)
    return "written"


@pytest.fixture(autouse=True)
def _builder_restored():
    saved = policy_hook._builder
    RAN.clear()
    yield
    policy_hook.register_policy_middleware_builder(saved)


def _config(enabled: bool = True):
    return SimpleNamespace(policy=SimpleNamespace(enabled=enabled))


def _broken_builder(app_config):
    raise FileNotFoundError("rules file /etc/policy.yaml not found")


def test_policy_is_on_by_default_in_the_shipped_code() -> None:
    """Article XIV: the default lives in tracked code, not in config.yaml."""
    assert PolicyConfig().enabled is True


def test_an_explicit_opt_out_installs_no_gate() -> None:
    """The one way to run without the policy layer is to say so."""
    policy_hook.register_policy_middleware_builder(_broken_builder)

    assert policy_hook.build_policy_middleware(_config(enabled=False)) is None


@pytest.mark.parametrize(
    ("builder", "said"),
    [(_broken_builder, "rules file /etc/policy.yaml not found"), (None, "no policy layer is installed")],
    ids=["builder-raises", "never-installed"],
)
def test_a_policy_that_cannot_be_built_refuses_tool_calls(builder, said) -> None:
    policy_hook.register_policy_middleware_builder(builder)

    gate = policy_hook.build_policy_middleware(_config())

    assert gate is not None, "no gate: tool calls would run unchecked"
    calls = []
    result = gate.wrap_tool_call(SimpleNamespace(tool_call={"name": "write_note", "args": {}, "id": "tc1"}), lambda req: calls.append(req))
    assert calls == [], "the refusing gate ran the tool"
    assert isinstance(result, ToolMessage) and result.status == "error"
    assert said in result.content and "write_note" in result.content


def test_an_agent_whose_policy_failed_does_not_run_its_tools() -> None:
    """The production shape: the middleware list every agent is built from,
    and a real agent loop dispatching a real tool call."""
    from omniharness.agents.middlewares.tool_error_handling_middleware import build_lead_runtime_middlewares
    from omniharness.config.app_config import AppConfig
    from omniharness.config.database_config import DatabaseConfig
    from omniharness.config.sandbox_config import SandboxConfig

    policy_hook.register_policy_middleware_builder(_broken_builder)
    app_config = AppConfig(sandbox=SandboxConfig(use="omniharness.sandbox.local:LocalSandboxProvider"), database=DatabaseConfig(), policy=PolicyConfig(enabled=True))
    gate = build_lead_runtime_middlewares(app_config=app_config, lazy_init=True)[-1]
    model = _ToolCallingModel(
        messages=iter(
            [
                AIMessage(content="", tool_calls=[{"name": "write_note", "args": {"text": "hello"}, "id": "tc1"}]),
                AIMessage(content="I could not write it."),
            ]
        )
    )
    agent = create_agent(model=model, tools=[write_note], middleware=[gate])

    out = agent.invoke({"messages": [HumanMessage(content="write hello")]})

    assert RAN == [], "a tool ran while the policy layer was broken"
    refusal = next(m for m in out["messages"] if isinstance(m, ToolMessage))
    assert "permission policy" in refusal.content
