"""Per-agent integrations and tools (006-G), through the production composition.

`create_app()` with its real lifespan, auth on, real HTTP. The REAL
`get_available_tools` assembles every run's tools, from:

  * config.yaml's tools (config.example.yaml: web, file:read, file:write);
  * two MCP servers in extensions_config.json: `filesystem` (shipped, pinned)
    and `notes` (the user's own), whose loaded tools sit in the MCP cache the
    agent reads (the server processes themselves are not started);
  * one connected Composio toolkit, Gmail, whose per-user loader
    (`connector_tools.load_connector_tools`) answers with three tools, tagged
    as the real loader tags them.

Only chat models are fakes; each records the tool names it was BOUND with,
which is what the model is offered.

Gates:
  * an agent with an allowlist is offered exactly the core tools plus the
    tools it names, on EVERY run path: chat, a scheduled 006-F firing, an
    @-call and a delegation (`task`, confirmed from its card);
  * an agent saved before 006-G (no allowlist) keeps exactly its old tools;
  * the catalog's tier badge is the policy classifier's (a relabelled rule,
    and the bash runtime floor, both show), never hard-coded;
  * the allowlist and the avatar are validated server-side; another account
    cannot change them; the agent changing itself cannot touch its tools.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool

GMAIL_FETCH = "connector-gmail_GMAIL_FETCH_EMAILS"
GMAIL_DRAFT = "connector-gmail_GMAIL_CREATE_EMAIL_DRAFT"
GMAIL_TRASH = "connector-gmail_GMAIL_MOVE_TO_TRASH"
#: No rule names it on purpose (email is read-and-draft only): refused, so
#: never offered, assigned or not.
GMAIL_SEND = "connector-gmail_GMAIL_SEND_EMAIL"
NOTES_READ = "notes_read_note"
NOTES_DELETE = "notes_delete_note"
FS_READ = "filesystem_read_file"
FS_EDIT = "filesystem_edit_file"

ASSIGNED = {GMAIL_FETCH, "web_search", NOTES_READ}
#: Present in the install, and NOT assigned to the agent.
UNASSIGNED = {GMAIL_DRAFT, GMAIL_TRASH, GMAIL_SEND, "web_fetch", NOTES_DELETE, FS_READ, FS_EDIT, "read_file", "write_file", "ls", "ledger_apply", "ledger_read"}

ACCESS = {"integrations": sorted(["connector:GMAIL", "builtin:web", "local:notes"]), "tools": sorted(ASSIGNED)}


def _tool(name: str, doc: str) -> StructuredTool:
    def run(**_kwargs) -> str:
        return f"{name} ran"

    return StructuredTool.from_function(func=run, name=name, description=doc, args_schema={"type": "object", "properties": {"q": {"type": "string"}}})


MCP_TOOLS = [
    _tool(FS_READ, "Read a file from the workspace."),
    _tool(FS_EDIT, "Edit a file in the workspace."),
    _tool(NOTES_READ, "Read one note."),
    _tool(NOTES_DELETE, "Delete a note for good."),
]


def _gmail_tools(user_id: str) -> list:
    from omniharness.tools.source_tags import tag_source

    out = [_tool(GMAIL_FETCH, "Fetch emails. Lists recent messages."), _tool(GMAIL_DRAFT, "Create an email draft."), _tool(GMAIL_TRASH, "Move a message to Trash."), _tool(GMAIL_SEND, "Send an email.")]
    for t in out:
        tag_source(t, "connector:GMAIL", user_id)
    return out


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

    os.environ.setdefault("AUTH_JWT_SECRET", "test-secret-key-studio-composition-min-32")
    example = Path(__file__).resolve().parents[3] / "config.example.yaml"
    config = yaml.safe_load(example.read_text())
    config["database"] = {"backend": "sqlite", "sqlite_dir": str(tmp_path / "data")}
    rules = yaml.safe_load((Path(__file__).resolve().parents[2] / "app" / "policy" / "default_rules.yaml").read_text())
    # The user's own MCP server's tools need rules (007: an unruled tool is
    # refused and never offered, which would make "not offered" vacuous).
    rules["policy"]["rules"][:0] = [{"pattern": NOTES_READ, "tier": 1}, {"pattern": NOTES_DELETE, "tier": 3}]
    (tmp_path / "rules.yaml").write_text(yaml.safe_dump(rules))
    config["policy"] = {"enabled": True, "state_dir": str(tmp_path / "policy"), "rules_path": str(tmp_path / "rules.yaml")}
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
    servers = {"filesystem": {"enabled": True, "type": "stdio", "command": "true"}, "notes": {"enabled": True, "type": "stdio", "command": "true", "description": "My notes"}}
    extensions.write_text(json.dumps({"mcpServers": servers, "skills": {}}))
    monkeypatch.setenv("OMNI_HARNESS_CONFIG_PATH", str(path))
    monkeypatch.setenv("OMNI_HARNESS_EXTENSIONS_CONFIG_PATH", str(extensions))
    monkeypatch.setenv("OMNI_HARNESS_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    reset_app_config()
    reset_extensions_config()
    set_auth_config(AuthConfig(jwt_secret=os.environ["AUTH_JWT_SECRET"]))

    # The MCP cache the agent reads, as if both servers had loaded.
    import omniharness.mcp.cache as cache

    monkeypatch.setattr(cache, "_cache_initialized", True)
    monkeypatch.setattr(cache, "_mcp_tools_cache", list(MCP_TOOLS))
    monkeypatch.setattr(cache, "get_cached_mcp_tools", lambda: list(MCP_TOOLS))
    # The per-user Composio loader: Gmail is connected for whoever asks.
    loads: list[tuple[str, list[str]]] = []

    def load_connector_tools(user_id, toolkits):
        loads.append((user_id, sorted(toolkits)))
        return _gmail_tools(user_id) if user_id and "GMAIL" in {t.upper() for t in toolkits} else []

    monkeypatch.setattr("omniharness.tools.connector_tools.load_connector_tools", load_connector_tools)
    import app.gateway.tool_catalog as catalog

    monkeypatch.setattr(catalog, "_CONNECTOR_CACHE", {})

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

    state = SimpleNamespace(lead=[], sub=[], lead_script=[], sub_script=[], loads=loads)

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


def _make(gw, name: str = "mailer", **fields) -> dict:
    resp = gw.client.post("/api/agents", json={"name": name, "soul": f"You are {name}.", "skills": [], **fields})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _thread(gw) -> str:
    resp = gw.client.post("/api/threads", json={})
    assert resp.status_code == 200, resp.text
    return resp.json()["thread_id"]


def _say(gw, thread_id: str, text: str, *, agent: str = "lead_agent", subagents: bool = False) -> dict:
    body = {"assistant_id": agent, "input": {"messages": [{"role": "user", "content": text}]}}
    if subagents:
        body["context"] = {"subagent_enabled": True}
    resp = gw.client.post(f"/api/threads/{thread_id}/runs/wait", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _offered(bound: list[list[str]]) -> set[str]:
    assert bound, "no model was bound to tools: the run did not happen"
    return set(bound[-1])


def _assert_allowlist(tools: set[str], where: str) -> None:
    assert ASSIGNED <= tools, f"{where}: an assigned tool was not offered: {sorted(ASSIGNED - tools)} (offered {sorted(tools)})"
    leaked = UNASSIGNED & tools
    assert not leaked, f"{where}: tools the agent was NOT given were offered: {sorted(leaked)}"


# -- every run path ------------------------------------------------------------


def test_chat_offers_only_the_assigned_tools(gw) -> None:
    _make(gw, tools=ACCESS)
    _say(gw, _thread(gw), "what came in today?", agent="mailer")
    tools = _offered(gw.lead)
    _assert_allowlist(tools, "chat")
    assert {"present_files", "ask_clarification"} <= tools, "the core tools were dropped"
    # Its own connector loaded for the run's user, whatever the chat picked.
    assert (gw.user_id, ["GMAIL"]) in gw.loads


def test_a_scheduled_firing_offers_only_the_assigned_tools(gw) -> None:
    from test_agent_schedules import _cycle, _engine, _rules_file, _schedule

    studio = SimpleNamespace(client=gw.client, tmp=gw.tmp)
    _rules_file(studio)
    _make(gw, tools=ACCESS)
    engine = _engine(studio)
    _schedule(studio, agent="mailer")
    _cycle(engine)
    [(_, _, body)] = engine.runs()
    assert body["assistant_id"] == "mailer"
    _assert_allowlist(_offered(gw.lead), "scheduled firing")


def test_an_at_call_offers_only_the_called_agents_assigned_tools(gw) -> None:
    _make(gw, tools=ACCESS)
    thread_id = _thread(gw)
    assert gw.client.post(f"/api/threads/{thread_id}/participants", json={"agent": "mailer"}).status_code == 200
    gw.sub_script[:] = [AIMessage(content="Two emails came in.")]
    out = _say(gw, thread_id, "@mailer what came in today?")
    assert out["messages"][-1]["name"] == "mailer", out["messages"][-1]
    _assert_allowlist(_offered(gw.sub), "@-call")


def test_a_delegation_inherits_the_agents_allowlist(gw) -> None:
    _make(gw, tools=ACCESS)
    thread_id = _thread(gw)
    delegate = {"name": "task", "args": {"description": "check mail", "prompt": "List today's email.", "subagent_type": "general-purpose"}, "id": "d1"}
    gw.lead_script[:] = [AIMessage(content="", tool_calls=[delegate]), AIMessage(content="Waiting for you.")]
    _say(gw, thread_id, "ask a helper to check my mail", agent="mailer", subagents=True)
    _assert_allowlist(_offered(gw.lead), "delegating agent")
    assert "task" in set(gw.lead[-1]), "subagents were on, so the agent should have been offered task"
    [card] = [a for a in gw.client.get("/api/confirmations").json()["actions"] if a["tool_name"] == "task"]
    gw.sub_script[:] = [AIMessage(content="Two emails.")]
    resp = gw.client.post(f"/api/confirmations/{card['id']}/confirm", json={})
    assert resp.status_code == 200 and resp.json()["outcome"] == "executed", resp.text
    _assert_allowlist(_offered(gw.sub), "delegate")


# -- old agents, the lead ----------------------------------------------------------


def test_an_agent_saved_before_006g_keeps_exactly_its_old_tools(gw) -> None:
    from omniharness.config import get_app_config
    from omniharness.tools.tools import get_available_tools

    _make(gw, "legacy", tool_groups=["web", "file:read"])
    tid = _thread(gw)
    # This chat stores a selection with no connector in it (a new chat would
    # start with the user's connected apps on: app.gateway.tool_selection).
    assert gw.client.put(f"/api/threads/{tid}/tools", json={"sources": []}).status_code == 200
    _say(gw, tid, "hello", agent="legacy")
    offered = _offered(gw.lead)
    # What main assembles for it: its groups, the pinned MCP server, no
    # connector (none selected in this chat), plus update_agent.
    expected = {t.name for t in get_available_tools(groups=["web", "file:read"], app_config=get_app_config(), selected_sources={"local:session-watcher", "local:filesystem"}, user_id=gw.user_id)} | {"update_agent"}
    assert {"web_search", "web_fetch", "read_file", FS_READ} <= offered, offered
    assert not {GMAIL_FETCH, NOTES_READ, "write_file"} & offered, offered
    assert offered == expected, f"an agent without an allowlist changed tools: +{sorted(offered - expected)} -{sorted(expected - offered)}"


def test_the_lead_agent_is_unchanged(gw) -> None:
    _say(gw, _thread(gw), "hello")
    offered = _offered(gw.lead)
    assert {"web_search", "write_file", FS_READ} <= offered, offered
    assert NOTES_READ not in offered, "the lead got an unselected source"


def test_an_empty_allowlist_leaves_only_the_core_tools(gw) -> None:
    _make(gw, "quiet", tools={"integrations": [], "tools": []})
    _say(gw, _thread(gw), "hello", agent="quiet")
    offered = _offered(gw.lead)
    assert not (ASSIGNED | UNASSIGNED) & offered, offered
    assert {"present_files", "ask_clarification", "update_agent"} <= offered


def test_assigning_an_unruled_tool_never_makes_it_offered(gw) -> None:
    """Assigning never lowers a tier: a tool no rule names stays refused."""
    _make(gw, "sender", tools={"integrations": ["connector:GMAIL"], "tools": [GMAIL_FETCH, GMAIL_SEND]})
    _say(gw, _thread(gw), "hello", agent="sender")
    offered = _offered(gw.lead)
    assert GMAIL_FETCH in offered and GMAIL_SEND not in offered, offered


def test_a_tool_named_without_its_integration_is_not_offered(gw) -> None:
    _make(gw, "half", tools={"integrations": ["builtin:web"], "tools": ["web_search", GMAIL_FETCH, NOTES_READ]})
    _say(gw, _thread(gw), "hello", agent="half")
    offered = _offered(gw.lead)
    assert "web_search" in offered
    assert not {GMAIL_FETCH, NOTES_READ} & offered, offered


# -- the agent cannot change its own tools ------------------------------------------


def test_update_agent_from_a_run_never_changes_the_allowlist(gw) -> None:
    from omniharness.config import config_versions

    _make(gw, tools=ACCESS)
    snapshot, version = config_versions.current_agent_state(gw.user_id, "mailer")
    widened = dict(snapshot["config"], tools={"integrations": ACCESS["integrations"], "tools": sorted(ASSIGNED | UNASSIGNED)})
    config_versions.write_agent(gw.user_id, "mailer", {"config": widened, "soul": snapshot["soul"]}, who="agent:mailer", source="proposal", base_version=version)
    assert gw.client.get("/api/agents/mailer").json()["tools"] == ACCESS
    # The owner's own edit does change it.
    current = gw.client.get("/api/agents/mailer").json()
    narrowed = {"integrations": ["builtin:web"], "tools": ["web_search"]}
    resp = gw.client.put("/api/agents/mailer", json={"tools": narrowed, "base_version": current["version"]})
    assert resp.status_code == 200 and resp.json()["tools"] == narrowed, resp.text


# -- the catalog: tiers from the classifier -------------------------------------------


def _catalog(gw) -> dict:
    resp = gw.client.get("/api/studio/tool-catalog")
    assert resp.status_code == 200, resp.text
    return {i["id"]: i for i in resp.json()["integrations"]}


def _tiers(catalog: dict) -> dict[str, int | None]:
    return {t["name"]: t["tier"] for i in catalog.values() for t in i["tools"]}


def test_the_catalog_lists_every_source_with_the_classifiers_tier(gw) -> None:
    from app.policy.explain import explain
    from app.policy.registration import shared_loader
    from omniharness.config import get_app_config

    catalog = _catalog(gw)
    assert catalog["connector:GMAIL"]["status"] == "connected" and catalog["connector:GMAIL"]["kind"] == "app"
    assert catalog["connector:SLACK"]["status"] == "not_connected" and catalog["connector:SLACK"]["tools"] == []
    assert catalog["local:filesystem"]["kind"] == "mcp" and catalog["local:notes"]["kind"] == "custom"
    assert {"builtin:web", "builtin:file:read", "builtin:ledger"} <= set(catalog)
    tiers = _tiers(catalog)
    assert (tiers[GMAIL_FETCH], tiers[GMAIL_DRAFT], tiers[GMAIL_TRASH], tiers[GMAIL_SEND]) == (1, 2, 3, None)
    assert (tiers[NOTES_READ], tiers[NOTES_DELETE]) == (1, 3)
    ruleset = shared_loader(get_app_config().policy).load(notify=False)
    for name, tier in tiers.items():
        decision = explain(name, {}, ruleset)
        assert tier == (None if decision.refused else int(decision.tier)), f"{name}: catalog says {tier}, the classifier says {decision.tier}"
    # The core tools are not assignable, so not listed.
    assert not {"present_files", "ask_clarification", "task"} & set(tiers)


def test_a_relabelled_rule_changes_the_badge(gw) -> None:
    rules_path = gw.tmp / "rules.yaml"
    rules = yaml.safe_load(rules_path.read_text())
    for rule in rules["policy"]["rules"]:
        if rule["pattern"] == GMAIL_FETCH:
            rule["tier"] = 3
    rules_path.write_text(yaml.safe_dump(rules))
    import app.gateway.tool_catalog as catalog

    catalog._CONNECTOR_CACHE.clear()
    assert _tiers(_catalog(gw))[GMAIL_FETCH] == 3


def test_the_bash_runtime_floor_shows_in_the_badge(gw, monkeypatch) -> None:
    """bash is Tier 2 in the rules but Tier 3 outside the hardened sandbox
    (runtime_floors): the badge is the floor, as dispatch is."""
    monkeypatch.setattr("omniharness.tools.tools.is_host_bash_allowed", lambda _config: True)
    tiers = _tiers(_catalog(gw))
    assert tiers.get("bash") == 3, tiers.get("bash")


def test_common_tools_come_first_and_are_marked(gw) -> None:
    gmail = _catalog(gw)["connector:GMAIL"]["tools"]
    names = [t["name"] for t in gmail]
    assert names[0] == GMAIL_FETCH and gmail[0]["common"] is True
    assert {t["short"] for t in gmail} == {"GMAIL_FETCH_EMAILS", "GMAIL_CREATE_EMAIL_DRAFT", "GMAIL_MOVE_TO_TRASH", "GMAIL_SEND_EMAIL"}
    assert gmail[0]["label"] == "Fetch emails"


# -- validation and ownership ---------------------------------------------------------


@pytest.mark.parametrize("avatar", ["not-real", "../../etc/passwd", "MERLO", ""])
def test_an_unknown_avatar_is_refused(gw, avatar) -> None:
    resp = gw.client.post("/api/agents", json={"name": "faces", "avatar": avatar})
    assert resp.status_code == 422, resp.text


def test_avatar_is_saved_and_a_new_agent_gets_a_random_one(gw) -> None:
    from omniharness.config.agents_config import AGENT_AVATARS

    assert _make(gw, "picked", avatar="snooze")["avatar"] == "snooze"
    assert _make(gw, "random")["avatar"] in AGENT_AVATARS
    current = gw.client.get("/api/agents/picked").json()
    bad = gw.client.put("/api/agents/picked", json={"avatar": "nope", "base_version": current["version"]})
    assert bad.status_code == 422
    good = gw.client.put("/api/agents/picked", json={"avatar": "croak", "base_version": current["version"]})
    assert good.status_code == 200 and good.json()["avatar"] == "croak"


@pytest.mark.parametrize(
    "tools",
    [
        {"integrations": ["gmail"], "tools": []},
        {"integrations": ["local:"], "tools": []},
        {"integrations": ["connector:GMAIL"], "tools": ["has space"]},
        {"integrations": "connector:GMAIL", "tools": []},
    ],
)
def test_a_malformed_allowlist_is_refused(gw, tools) -> None:
    assert gw.client.post("/api/agents", json={"name": "bad-tools", "tools": tools}).status_code == 422


def test_an_unreadable_allowlist_on_disk_fails_closed(gw) -> None:
    from omniharness.config.agents_config import load_agent_config

    _make(gw, tools=ACCESS)
    config_file = Path(gw.tmp / "home" / "users" / gw.user_id / "agents" / "mailer" / "config.yaml")
    data = yaml.safe_load(config_file.read_text())
    data["tools"] = "everything"
    config_file.write_text(yaml.safe_dump(data))
    assert load_agent_config("mailer", user_id=gw.user_id).tools.tools == []
