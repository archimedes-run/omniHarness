"""The gateway built the way production builds it, for the chat builder (Spec 010 Slice 2).

`create_app()` with its real lifespan, auth on, real HTTP, the shipped policy
rules (copied, plus nothing), a writable automations rules file and a skills
directory, all in a temporary home. Only chat models are fakes: each records
the tool names it was BOUND with (what the model is offered) and answers from
its script. Draft ids are made predictable (`d-test-1`, `d-test-2`, ...) so a
script can name the draft its own earlier call made.

The one content-reading tool is a pinned MCP server's `filesystem_read_file`
(in the MCP cache, the server process is not started), whose result is set by
the test: it is how a page or an email reaches a turn.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
from itertools import count
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool

FS_READ = "filesystem_read_file"


class Recorder(GenericFakeChatModel):
    """Answers from its script; records the tool names it was bound with."""

    sink: list = []

    def bind_tools(self, tools, **kwargs):
        self.sink.append(sorted(getattr(t, "name", None) or (t.get("name") if isinstance(t, dict) else str(t)) for t in tools))
        return self


@pytest.fixture
def gw(tmp_path, monkeypatch):
    import os

    from fastapi.testclient import TestClient

    from app.gateway.auth.config import AuthConfig, set_auth_config
    from omniharness.config.app_config import reset_app_config
    from omniharness.config.extensions_config import reset_extensions_config

    os.environ.setdefault("AUTH_JWT_SECRET", "test-secret-key-builder-composition-min-32")
    root = Path(__file__).resolve().parents[3]
    config = yaml.safe_load((root / "config.example.yaml").read_text())
    config["database"] = {"backend": "sqlite", "sqlite_dir": str(tmp_path / "data")}
    # The SHIPPED rules, unchanged: the builder's tiers come from them.
    (tmp_path / "rules.yaml").write_text((root / "backend" / "app" / "policy" / "default_rules.yaml").read_text())
    config["policy"] = {"enabled": True, "state_dir": str(tmp_path / "policy"), "rules_path": str(tmp_path / "rules.yaml")}
    (tmp_path / "rules.json").write_text(json.dumps({"rules": []}))
    config["trigger_engine"] = {"enabled": False, "rules_path": str(tmp_path / "rules.json"), "state_dir": str(tmp_path / "triggers")}
    config["agents_api"] = {"enabled": True}
    config.setdefault("memory", {})["enabled"] = False
    config.setdefault("title", {})["enabled"] = False
    config.setdefault("summarization", {})["enabled"] = False
    config.setdefault("skills", {})["path"] = str(tmp_path / "skills")
    (tmp_path / "skills" / "public").mkdir(parents=True)
    (tmp_path / "skills" / "custom").mkdir(parents=True)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config))
    extensions = tmp_path / "extensions.json"
    extensions.write_text(json.dumps({"mcpServers": {"filesystem": {"enabled": True, "type": "stdio", "command": "true"}}, "skills": {}}))
    monkeypatch.setenv("OMNI_HARNESS_CONFIG_PATH", str(path))
    monkeypatch.setenv("OMNI_HARNESS_EXTENSIONS_CONFIG_PATH", str(extensions))
    monkeypatch.setenv("OMNI_HARNESS_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    reset_app_config()
    reset_extensions_config()
    set_auth_config(AuthConfig(jwt_secret=os.environ["AUTH_JWT_SECRET"]))

    state = SimpleNamespace(lead=[], sub=[], lead_script=[], sub_script=[], read_result="Nothing here.")

    def read(**_kwargs) -> str:
        return state.read_result

    fs_read = StructuredTool.from_function(func=read, name=FS_READ, description="Read a file.", args_schema={"type": "object", "properties": {"path": {"type": "string"}}})
    import omniharness.mcp.cache as cache

    monkeypatch.setattr(cache, "_cache_initialized", True)
    monkeypatch.setattr(cache, "_mcp_tools_cache", [fs_read])
    monkeypatch.setattr(cache, "get_cached_mcp_tools", lambda: [fs_read])

    # Predictable draft ids.
    ids = count(1)
    monkeypatch.setattr("app.gateway.builder.drafts.new_draft_id", lambda: f"d-test-{next(ids)}")

    # Chat models: the lead's and every subagent's (delegate or @-called).
    monkeypatch.delitem(sys.modules, "omniharness.subagents.executor")
    executor_module = importlib.import_module("omniharness.subagents.executor")
    task_tool_module = importlib.import_module("omniharness.tools.builtins.task_tool")
    for name in ("SubagentExecutor", "SubagentStatus", "get_background_task_result", "cleanup_background_task", "request_cancel_background_task"):
        monkeypatch.setattr(task_tool_module, name, getattr(executor_module, name))
    import omniharness.subagents as subagents_package

    monkeypatch.setattr(subagents_package, "SubagentExecutor", executor_module.SubagentExecutor, raising=False)
    real_sleep = asyncio.sleep
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", lambda _s: real_sleep(0.05))

    def lead_model(**_):
        model = Recorder(messages=iter(list(state.lead_script) + [AIMessage(content="Done.")] * 3))
        model.sink = state.lead
        return model

    def sub_model(**_):
        model = Recorder(messages=iter(list(state.sub_script) + [AIMessage(content="Sub done.")] * 3))
        model.sink = state.sub
        return model

    monkeypatch.setattr("omniharness.agents.lead_agent.agent.create_chat_model", lead_model)
    monkeypatch.setattr(executor_module, "create_chat_model", sub_model)

    import app.gateway.deps as deps
    from app.gateway.app import create_app

    monkeypatch.setattr(deps, "_cached_local_provider", None)
    monkeypatch.setattr(deps, "_cached_repo", None)
    with TestClient(create_app()) as client:
        resp = client.post("/api/v1/auth/initialize", json={"email": "owner@example.com", "password": "Str0ng!Pass99"})
        assert resp.status_code in (200, 201), resp.text
        csrf = client.cookies.get("csrf_token")
        if csrf:
            client.headers["X-CSRF-Token"] = csrf
        me = client.get("/api/v1/auth/me").json()
        state.client = client
        state.user_id = str(me.get("id") or me.get("user", {}).get("id"))
        state.tmp = tmp_path
        yield state
    reset_app_config()
    reset_extensions_config()


# -- helpers the tests share ---------------------------------------------------


def call(name: str, args: dict, ident: str) -> dict:
    return {"name": name, "args": args, "id": ident}


def script(gw, *steps) -> None:
    """The lead's next replies: each a list of tool calls, or a final text."""
    gw.lead_script[:] = [AIMessage(content="", tool_calls=step) if isinstance(step, list) else AIMessage(content=step) for step in steps]


def new_thread(gw) -> str:
    resp = gw.client.post("/api/threads", json={})
    assert resp.status_code == 200, resp.text
    return resp.json()["thread_id"]


def say(gw, thread_id: str, text: str, *, agent: str = "lead_agent", context: dict | None = None) -> dict:
    body: dict = {"assistant_id": agent, "input": {"messages": [{"role": "user", "content": text}]}}
    if context:
        body["context"] = context
    resp = gw.client.post(f"/api/threads/{thread_id}/runs/wait", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def offered(bound: list[list[str]]) -> set[str]:
    assert bound, "no model was bound to tools: the run did not happen"
    return set(bound[-1])


def cards(gw, tool: str | None = None) -> list[dict]:
    actions = gw.client.get("/api/confirmations").json()["actions"]
    return [a for a in actions if tool is None or a["tool_name"] == tool]


def make_agent(gw, name: str, **fields) -> dict:
    resp = gw.client.post("/api/agents", json={"name": name, "soul": f"You are {name}.", "skills": [], **fields})
    assert resp.status_code == 201, resp.text
    return resp.json()


def agent_state(gw, name: str):
    from omniharness.config import config_versions

    return config_versions.current_agent_state(gw.user_id, name)


def agent_history(gw, name: str):
    from omniharness.config import config_versions

    return config_versions.agent_history(gw.user_id, name)


def history_records(gw, name: str) -> list[dict]:
    """The agent's history file, read back as written."""
    from omniharness.config import config_versions

    path = config_versions._agent_paths(gw.user_id, name)[0]
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []
