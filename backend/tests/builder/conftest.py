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
from builder_helpers import FS_READ, GMAIL_DRAFT, GMAIL_FETCH
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool


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
    # A second model without vision: a model change can add a tool (view_image).
    config["models"] = [*config["models"], {**config["models"][0], "name": "plain", "supports_vision": False}]
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

    # One connected app, Gmail, whose per-user loader answers with its tools
    # tagged as the real loader tags them (as tests/studio do).
    def load_connector_tools(user_id, toolkits):
        from omniharness.tools.source_tags import tag_source

        if not user_id or "GMAIL" not in {t.upper() for t in toolkits}:
            return []
        out = [
            StructuredTool.from_function(func=lambda **_k: "mail", name=name, description=doc, args_schema={"type": "object", "properties": {"q": {"type": "string"}}})
            for name, doc in ((GMAIL_FETCH, "Fetch emails."), (GMAIL_DRAFT, "Create an email draft."))
        ]
        for t in out:
            tag_source(t, "connector:GMAIL", user_id)
        return out

    monkeypatch.setattr("omniharness.tools.connector_tools.load_connector_tools", load_connector_tools)

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

        class Connections:
            async def list_by_user(self, user_id):
                return [{"toolkit": "GMAIL", "status": "active", "composio_connection_id": "ca_test"}]

        client.app.state.composio_connection_repo = Connections()
        client.app.state.composio_client = object()
        state.client = client
        state.user_id = str(me.get("id") or me.get("user", {}).get("id"))
        state.tmp = tmp_path
        yield state
    reset_app_config()
    reset_extensions_config()
