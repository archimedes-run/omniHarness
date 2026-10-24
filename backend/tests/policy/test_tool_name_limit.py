"""A tool name over the provider's 64-character limit, end to end.

Live failure: a called agent's run answered `400 Invalid
'messages[13].tool_calls[1].function.name': string too long ... maximum length
64, but got a string with length 75` for
`connector-github_GITHUB_LIST_REPOSITORIES_STARRED_BY_THE_AUTHENTICATED_USER`.

Through the production composition: `create_app()` with its lifespan, real runs
through `POST /api/threads/{id}/runs/wait`, the run worker, `make_lead_agent`,
the policy middleware production builds, the real `task` tool and
`SubagentExecutor`, the confirmations API. Only the chat models are scripted,
and they behave like the provider: a request offering or carrying a tool name
outside `^[a-zA-Z0-9_-]{1,64}$` fails with the provider's 400, and a model can
only call a tool it was offered, by the name it was offered.

  1. a long-named tool is offered under an alias, the model calls the alias,
     and the REAL tool runs (lead and delegate);
  2. a chat whose checkpoint already holds the 75-character name continues;
  3. the policy decides on the FULL name: an alias made to look like a public
     tool (`web_fetch...`, matching a Tier 1 glob) is still the Tier 3 tool it
     stands for, and the confirmation names the full tool.
"""

from __future__ import annotations

import importlib
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import StructuredTool, tool
from langchain_core.utils.function_calling import convert_to_openai_tool

from omniharness.models.tool_name_boundary import alias_for

os.environ.setdefault("AUTH_JWT_SECRET", "test-secret-key-tool-name-limit-min-32-chars")
EXAMPLE = Path(__file__).resolve().parents[3] / "config.example.yaml"
RULES = Path(__file__).resolve().parents[2] / "app" / "policy" / "default_rules.yaml"

#: The live name, exactly (Tier 1 in the shipped rules).
LIVE = "connector-github_GITHUB_LIST_REPOSITORIES_STARRED_BY_THE_AUTHENTICATED_USER"
#: A Tier 3 tool whose alias looks like a public lookup and matches a Tier 1 glob.
LOOKALIKE = "web_fetch_and_forward_the_fetched_page_to_an_external_archive_webhook"
PROVIDER_NAME = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

RAN: list[str] = []
#: Tool names offered to a model, per bind.
OFFERED: list[list[str]] = []
#: Tool names in the messages each model call was sent.
SHOWN: list[list[str]] = []
LEAD_SCRIPT: list[AIMessage] = []
SUB_SCRIPT: list[AIMessage] = []


def _long_tool(name: str) -> StructuredTool:
    def run(owner: str = "") -> str:
        RAN.append(name)
        return f"{name} ran"

    return StructuredTool.from_function(func=run, name=name, description=f"stand-in for {name}")


@tool("web_fetch")
def web_fetch(url: str) -> str:
    """Fetch a page (stand-in)."""
    RAN.append("web_fetch")
    return "page"


LEAD_TOOLS = [_long_tool(LIVE), _long_tool(LOOKALIKE), web_fetch]


def _names_in(messages) -> list[str]:
    names = []
    for m in messages:
        names += [c["name"] for c in getattr(m, "tool_calls", None) or []]
        if isinstance(m, ToolMessage) and m.name:
            names.append(m.name)
    return names


def _provider_400(names: list[str], where: str) -> None:
    for n in names:
        if not PROVIDER_NAME.match(n):
            raise ValueError(f"Error code: 400 - Invalid '{where}.function.name': string too long. Expected a string with maximum length 64, but got a string with length {len(n)}")


class _Provider(GenericFakeChatModel):
    """A scripted model that validates tool names the way the provider does."""

    disable_streaming: bool = True

    def bind_tools(self, tools, **kwargs):
        OFFERED.append([convert_to_openai_tool(t)["function"]["name"] for t in tools])
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        SHOWN.append(_names_in(messages))
        _provider_400(OFFERED[-1] if OFFERED else [], "tools[]")
        _provider_400(SHOWN[-1], "messages[].tool_calls[]")
        result = super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        for call in result.generations[0].message.tool_calls:
            assert call["name"] in OFFERED[-1], f"the script called {call['name']!r}, which the model was not offered"
        return result


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    from app.gateway.auth.config import AuthConfig, set_auth_config
    from omniharness.config.app_config import reset_app_config
    from omniharness.config.extensions_config import reset_extensions_config

    config = yaml.safe_load(EXAMPLE.read_text())
    config["database"] = {"backend": "sqlite", "sqlite_dir": str(tmp_path / "data")}
    rules = yaml.safe_load(RULES.read_text())
    rules["policy"]["rules"][:0] = [
        {"pattern": LOOKALIKE, "tier": 3},
        # A public-lookup glob the alias of LOOKALIKE matches (and so does the
        # full name: highest tier wins on overlap, so the full name is Tier 3).
        {"pattern": "web_fetch*", "tier": 1, "reversible": True, "reads_private": False},
    ]
    (tmp_path / "rules.yaml").write_text(yaml.safe_dump(rules))
    config["policy"] = {"enabled": True, "state_dir": str(tmp_path / "policy"), "rules_path": str(tmp_path / "rules.yaml")}
    config["trigger_engine"] = {"enabled": False}
    config.setdefault("memory", {})["enabled"] = False
    config.setdefault("title", {})["enabled"] = False
    config.setdefault("summarization", {})["enabled"] = False
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config))
    extensions = tmp_path / "extensions.json"
    extensions.write_text('{"mcpServers": {}, "skills": {}}')
    monkeypatch.setenv("OMNI_HARNESS_CONFIG_PATH", str(path))
    monkeypatch.setenv("OMNI_HARNESS_EXTENSIONS_CONFIG_PATH", str(extensions))
    monkeypatch.chdir(tmp_path)
    reset_app_config()
    reset_extensions_config()
    set_auth_config(AuthConfig(jwt_secret=os.environ["AUTH_JWT_SECRET"]))
    for bucket in (RAN, OFFERED, SHOWN, LEAD_SCRIPT, SUB_SCRIPT):
        bucket.clear()
    _wire(monkeypatch)

    import contextlib

    import app.gateway.deps as deps
    from app.gateway.app import create_app

    monkeypatch.setattr(deps, "_cached_local_provider", None)
    monkeypatch.setattr(deps, "_cached_repo", None)
    stack = contextlib.ExitStack()
    client = stack.enter_context(TestClient(create_app()))
    resp = client.post("/api/v1/auth/initialize", json={"email": "owner@example.com", "password": "Str0ng!Pass99"})
    assert resp.status_code in (200, 201), resp.text
    csrf = client.cookies.get("csrf_token")
    if csrf:
        client.headers["X-CSRF-Token"] = csrf
    yield SimpleNamespace(client=client)
    stack.close()
    reset_app_config()
    reset_extensions_config()


def _wire(monkeypatch):
    # tests/conftest.py replaces the executor module with a MagicMock for the
    # session; delegation needs the real one.
    monkeypatch.delitem(sys.modules, "omniharness.subagents.executor")
    executor_module = importlib.import_module("omniharness.subagents.executor")
    task_tool_module = importlib.import_module("omniharness.tools.builtins.task_tool")
    for name in ("SubagentExecutor", "SubagentStatus", "get_background_task_result", "cleanup_background_task", "request_cancel_background_task"):
        monkeypatch.setattr(task_tool_module, name, getattr(executor_module, name))
    import omniharness.subagents as subagents_package

    monkeypatch.setattr(subagents_package, "SubagentExecutor", executor_module.SubagentExecutor, raising=False)
    monkeypatch.setattr("omniharness.agents.lead_agent.agent.create_chat_model", lambda **_: _Provider(messages=iter(list(LEAD_SCRIPT))))
    monkeypatch.setattr(executor_module, "create_chat_model", lambda **_: _Provider(messages=iter(list(SUB_SCRIPT))))

    from omniharness.tools.tools import SUBAGENT_TOOLS

    def available(**kwargs):
        return [*LEAD_TOOLS, *(SUBAGENT_TOOLS if kwargs.get("subagent_enabled") else [])]

    monkeypatch.setattr("omniharness.tools.get_available_tools", available)
    import asyncio

    real_sleep = asyncio.sleep
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", lambda _s: real_sleep(0.05))


# -- helpers -------------------------------------------------------------------


def _thread(gateway) -> str:
    resp = gateway.client.post("/api/threads", json={})
    assert resp.status_code == 200, resp.text
    return resp.json()["thread_id"]


def _say(gateway, thread_id: str, text: str, script: list[AIMessage]) -> list[dict]:
    LEAD_SCRIPT[:] = [*script, *[AIMessage(content="(done)")] * 4]
    resp = gateway.client.post(
        f"/api/threads/{thread_id}/runs/wait",
        json={"assistant_id": "lead_agent", "input": {"messages": [{"role": "user", "content": text}]}, "context": {"subagent_enabled": True}},
    )
    assert resp.status_code == 200, resp.text
    return resp.json().get("messages", [])


def _call(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def _cards(gateway, tool_name: str | None = None) -> list[dict]:
    resp = gateway.client.get("/api/confirmations")
    assert resp.status_code == 200, resp.text
    return [a for a in resp.json()["actions"] if tool_name is None or a["tool_name"] == tool_name]


def _messages(gateway, thread_id: str) -> list[dict]:
    return gateway.client.get(f"/api/threads/{thread_id}/state").json()["values"]["messages"]


def _replies(messages: list[dict]) -> list[str]:
    return [m.get("content") for m in messages if m.get("type") == "ai" and m.get("content")]


# -- 1. offered under an alias, the real tool runs ----------------------------------


def test_a_long_named_tool_is_offered_within_the_limit_and_the_real_tool_runs(gateway):
    thread_id = _thread(gateway)
    messages = _say(gateway, thread_id, "list my starred repos", [_call(alias_for(LIVE), {"owner": "me"}, "s1"), AIMessage(content="Here they are.")])

    assert RAN == [LIVE], f"the real tool did not run (model offered {OFFERED[:1]})"
    assert "Here they are." in _replies(messages)
    assert OFFERED and all(len(n) <= 64 for names in OFFERED for n in names)
    assert alias_for(LIVE) in OFFERED[0] and LIVE not in OFFERED[0]
    # The thread (what the policy, the UI and run history read) holds the FULL name.
    state = _messages(gateway, thread_id)
    assert [c["name"] for m in state for c in m.get("tool_calls") or []] == [LIVE]
    assert [m["name"] for m in state if m.get("type") == "tool"] == [LIVE]
    # The next model call was shown the alias, not the full name.
    assert SHOWN[-1] == [alias_for(LIVE), alias_for(LIVE)]
    # Run history (the journal records the provider's raw reply) shows the full name.
    history = gateway.client.get(f"/api/threads/{thread_id}/messages")
    assert history.status_code == 200, history.text
    recorded = [c["name"] for e in history.json() if e.get("event_type") == "llm.ai.response" for c in (e.get("content") or {}).get("tool_calls") or []]
    assert recorded == [LIVE], f"run history shows {recorded}"


def test_a_delegate_offered_a_long_named_tool_runs_it(gateway):
    """The live failure was in a delegated (called) agent: same boundary, same result."""
    thread_id = _thread(gateway)
    _say(gateway, thread_id, "ask a helper to list my starred repos", [_call("task", {"description": "repos", "prompt": "List starred repos.", "subagent_type": "general-purpose"}, "d1"), AIMessage(content="waiting")])
    assert _cards(gateway, "task"), "the delegation did not reach its confirmation"
    SUB_SCRIPT[:] = [_call(alias_for(LIVE), {"owner": "me"}, "ss1"), AIMessage(content="found them")]
    _say(gateway, thread_id, "yes", [AIMessage(content="done")])

    assert RAN == [LIVE], f"the delegate's long-named tool did not run (offered: {OFFERED})"
    assert all(len(n) <= 64 for names in OFFERED + SHOWN for n in names)


# -- 2. a chat that already holds the 75-character name continues ---------------------


def test_a_checkpoint_holding_a_75_char_tool_name_continues(gateway):
    thread_id = _thread(gateway)
    _say(gateway, thread_id, "hello", [AIMessage(content="hi")])

    # The checkpoint as a pre-fix run left it: the full name in the AIMessage
    # (structured and raw provider payload) and in the ToolMessage.
    async def seed():
        from langgraph.checkpoint.base import empty_checkpoint

        checkpointer = gateway.client.app.state.checkpointer
        config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
        saved = await checkpointer.aget_tuple(config)
        checkpoint = dict(saved.checkpoint)
        values = dict(checkpoint["channel_values"])
        values["messages"] = [
            *values["messages"],
            AIMessage(content="", tool_calls=[{"name": LIVE, "args": {}, "id": "old1"}], additional_kwargs={"tool_calls": [{"id": "old1", "type": "function", "function": {"name": LIVE, "arguments": "{}"}}]}),
            ToolMessage(content="[repo-a, repo-b]", tool_call_id="old1", name=LIVE),
            AIMessage(content="You starred repo-a and repo-b."),
        ]
        checkpoint["channel_values"] = values
        checkpoint["id"] = empty_checkpoint()["id"]
        await checkpointer.aput(config, checkpoint, dict(saved.metadata), {})

    gateway.client.portal.call(seed)
    assert len(LIVE) == 75 and LIVE in [m.get("name") for m in _messages(gateway, thread_id)], "the seeded history is not in the thread"

    messages = _say(gateway, thread_id, "and which is newer?", [AIMessage(content="repo-b is newer.")])

    assert "repo-b is newer." in _replies(messages), "the chat did not continue past the long name in its history"
    assert alias_for(LIVE) in SHOWN[-1] and LIVE not in SHOWN[-1]


# -- 3. the policy decides on the FULL name -------------------------------------------


def test_an_alias_that_looks_like_a_public_tool_is_still_the_tool_it_stands_for(gateway, monkeypatch):
    """`web_fetch_and_forward...` is Tier 3. Its alias matches the Tier 1
    `web_fetch*` glob and NOT the Tier 3 exact rule; if the policy ever saw the
    alias, the call would run silently. It must be stated and confirmed."""
    alias = alias_for(LOOKALIKE)
    assert alias != LOOKALIKE and alias.startswith("web_fetch_")

    from app.policy.classify import classify
    from app.policy.registration import shared_loader

    # Precondition (what makes the sabotage meaningful): the alias alone would be Tier 1.
    ruleset = shared_loader(gateway.client.app.state.config.policy).load(notify=False)
    assert int(classify(alias, {}, ruleset).tier) == 1 and int(classify(LOOKALIKE, {}, ruleset).tier) == 3

    # Every name any rule check is asked about (classify, and so explain,
    # grants and coverage, all go through _candidates).
    import app.policy.classify as classify_module

    checked: list[str] = []
    real_candidates = classify_module._candidates
    monkeypatch.setattr(classify_module, "_candidates", lambda name, rs: checked.append(name) or real_candidates(name, rs))

    thread_id = _thread(gateway)
    _say(gateway, thread_id, "archive that page", [_call(alias, {"owner": "x"}, "w1"), AIMessage(content="asked")])

    assert LOOKALIKE not in RAN, "the Tier 3 tool ran without confirmation: the policy classified its alias"
    cards = _cards(gateway, LOOKALIKE)
    assert len(cards) == 1, f"no confirmation for the full tool name; cards: {[c['tool_name'] for c in _cards(gateway)]}"
    assert _cards(gateway, alias) == [], "a confirmation names the alias"
    assert alias.lower() not in checked, "a rule check was asked about the ALIAS: the policy decided on a name that is not the tool's"
    assert LOOKALIKE.lower() in checked
