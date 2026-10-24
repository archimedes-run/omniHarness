"""Tool names reach a model provider <= 64 characters (the provider's limit).

Live failure: a called agent's run answered `400 Invalid
'messages[13].tool_calls[1].function.name': string too long ... maximum length
64, but got a string with length 75`. The name was the connector tool
`connector-github_GITHUB_LIST_REPOSITORIES_STARRED_BY_THE_AUTHENTICATED_USER`
(the connector loader prefixes the upstream slug with `connector-<toolkit>_`).

The fix is ONE boundary (omniharness.models.tool_name_boundary) between every
agent and its model. These tests:

  * pin the alias scheme (deterministic, <= 64, provider charset, collision-free,
    fail closed);
  * GUARD: enumerate every tool source through the real loaders (built-ins,
    config tools, agent tools, MCP servers, a built MCP server, connector
    toolkits) and push every name through the boundary to a recording model;
  * GATE: every agent's middleware chain installs the boundary, and every
    direct `bind_tools` in the code base goes through it.

The end-to-end behaviour (dispatch, policy on the full name, an existing chat
recovering) is tested over HTTP in tests/policy/test_tool_name_limit.py.
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import re
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import yaml
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool

from omniharness.models import tool_name_boundary as boundary
from omniharness.models.tool_name_boundary import MODEL_SAFE_TOOL_NAME, ToolNameAliases, ToolNameBoundaryModel, ToolNameCollisionError, alias_for

BACKEND = Path(__file__).resolve().parents[1]
RULES = BACKEND / "app" / "policy" / "default_rules.yaml"
EXAMPLE = BACKEND.parent / "config.example.yaml"

#: The name from the live failure, exactly.
LIVE = "connector-github_GITHUB_LIST_REPOSITORIES_STARRED_BY_THE_AUTHENTICATED_USER"


def _tool(name: str) -> StructuredTool:
    return StructuredTool.from_function(func=lambda q="": q, name=name, description=f"tool {name}")


class _Recording(GenericFakeChatModel):
    """A model that records the tool names it is offered and shown, and calls back every tool it was offered."""

    offered: list = []
    shown: list = []

    def bind_tools(self, tools, **kwargs):
        self.offered[:] = [convert_to_openai_tool(t)["function"]["name"] for t in tools]
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.shown[:] = [n for m in messages for n in boundary.message_tool_names(m)]
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


# -- the alias scheme -------------------------------------------------------------


def test_the_live_name_gets_a_short_deterministic_alias():
    assert len(LIVE) == 75
    alias = alias_for(LIVE)
    assert len(alias) <= 64 and MODEL_SAFE_TOOL_NAME.match(alias)
    assert alias == alias_for(LIVE), "not deterministic"
    assert alias.endswith("_" + hashlib.sha256(LIVE.encode()).hexdigest()[:10])
    assert alias.startswith("connector-github_GITHUB_LIST_REPOSITORIES"), "the model should still read what the tool is"


def test_safe_names_pass_unchanged_and_unsafe_characters_are_aliased():
    assert alias_for("web_fetch") == "web_fetch"
    assert alias_for("connector-gmail_GMAIL_SEND_EMAIL") == "connector-gmail_GMAIL_SEND_EMAIL"
    dotted = alias_for("my.server.tool")
    assert MODEL_SAFE_TOOL_NAME.match(dotted) and dotted != "my.server.tool"


def test_names_sharing_a_long_prefix_get_different_aliases():
    a, b = "x" * 70 + "_one", "x" * 70 + "_two"
    aliases = ToolNameAliases([a, b])
    assert aliases.to_model(a) != aliases.to_model(b)
    assert aliases.to_full(aliases.to_model(a)) == a and aliases.to_full(aliases.to_model(b)) == b


def test_an_alias_never_takes_another_offered_tools_name():
    """A tool literally named like the alias: the alias is lengthened, never shared."""
    squatter = alias_for(LIVE)
    aliases = ToolNameAliases([LIVE, squatter])
    assert aliases.to_model(squatter) == squatter
    assert aliases.to_model(LIVE) != squatter
    assert aliases.to_full(squatter) == squatter and aliases.to_full(aliases.to_model(LIVE)) == LIVE
    assert len(aliases.to_model(LIVE)) <= 64


def test_no_collision_free_alias_fails_closed(monkeypatch):
    monkeypatch.setattr(boundary, "_DIGEST_LENGTHS", (10,))
    with pytest.raises(ToolNameCollisionError):
        ToolNameAliases([LIVE, alias_for(LIVE)])
    aliases = ToolNameAliases([LIVE])
    with pytest.raises(ToolNameCollisionError):
        aliases.add([alias_for(LIVE)])  # a history name equal to an alias already minted


def test_a_name_with_a_trailing_newline_is_not_model_safe():
    from omniharness.models.tool_name_boundary import alias_for, is_model_safe

    assert not is_model_safe("web_fetch\n")
    assert not is_model_safe("a" * 64 + "\n")
    alias = alias_for("web_fetch\n")
    assert alias != "web_fetch\n" and is_model_safe(alias) and len(alias) <= 64


def test_a_name_the_request_did_not_alias_is_not_rewritten():
    """Only this request's aliases map back: a made-up name is left for the policy to refuse."""
    aliases = ToolNameAliases([LIVE, "web_fetch"])
    assert aliases.to_full("web_fetch") == "web_fetch"
    assert aliases.to_full(alias_for("connector-github_GITHUB_SOMETHING_ELSE_" + "Z" * 40)) != LIVE


# -- the boundary on a model ------------------------------------------------------------


def test_the_boundary_offers_aliases_shows_aliased_history_and_returns_full_names():
    model = _Recording(messages=iter([AIMessage(content="", tool_calls=[{"name": alias_for(LIVE), "args": {}, "id": "c2"}])]))
    bound = ToolNameBoundaryModel(model).bind_tools([_tool(LIVE), _tool("web_fetch")], tool_choice=LIVE)
    history = [
        HumanMessage(content="hi"),
        AIMessage(content="", tool_calls=[{"name": LIVE, "args": {}, "id": "c1"}], additional_kwargs={"tool_calls": [{"id": "c1", "type": "function", "function": {"name": LIVE, "arguments": "{}"}}]}),
        ToolMessage(content="[]", tool_call_id="c1", name=LIVE),
    ]
    reply = bound.invoke(history)

    assert model.offered == [alias_for(LIVE), "web_fetch"]
    assert model.shown == [alias_for(LIVE), alias_for(LIVE), alias_for(LIVE)]
    assert all(len(n) <= 64 for n in model.offered + model.shown)
    assert reply.tool_calls[0]["name"] == LIVE
    # The caller's history is not mutated.
    assert history[1].tool_calls[0]["name"] == LIVE and history[2].name == LIVE


def test_streamed_chunks_show_the_full_name():
    from omniharness.runtime.serialization import serialize

    ToolNameAliases([LIVE])  # minted, as the boundary does on bind
    chunk = AIMessageChunk(content="", tool_call_chunks=[{"name": alias_for(LIVE), "args": "", "id": "c1", "index": 0}])
    data, _meta = serialize((chunk, {}), mode="messages")
    assert data["tool_call_chunks"][0]["name"] == LIVE
    assert data["tool_calls"][0]["name"] == LIVE


# -- GUARD: every tool source, through the real loaders ---------------------------


def _connector_names() -> dict[str, list[str]]:
    """Every connector tool the shipped rules name, by toolkit (upstream slug, unprefixed)."""
    by_toolkit: dict[str, list[str]] = {}
    for rule in yaml.safe_load(RULES.read_text())["policy"]["rules"]:
        m = re.match(r"^connector-([a-z]+)_(.+)$", rule["pattern"])
        if m and not set("*?[") & set(rule["pattern"]):
            by_toolkit.setdefault(m.group(1).upper(), []).append(m.group(2))
    return by_toolkit


BUILT_SERVER = "acme-records-built-mcp-server"
BUILT_TOOL = "list_every_customer_record_updated_since_the_previous_sync_window"
MCP_TOOLS = {
    "github": ("get_file_contents", "search_repositories"),
    "session-watcher": ("list_coding_sessions",),
    BUILT_SERVER: (BUILT_TOOL,),
}


@pytest.fixture
def every_source(tmp_path, monkeypatch):
    """Real loaders; only the MCP session (what a server answers) is faked."""
    import langchain_mcp_adapters.tools as adapter_tools
    from mcp.types import Tool

    from omniharness.config.app_config import get_app_config, reset_app_config
    from omniharness.config.extensions_config import reset_extensions_config
    from omniharness.mcp.cache import reset_mcp_tools_cache
    from omniharness.tools import connector_tools

    connectors = _connector_names()

    @asynccontextmanager
    async def create_session(connection, **_):
        text = json.dumps(connection, default=str)
        toolkit = (connection.get("env") or {}).get("COMPOSIO_TOOLKIT")
        session = type("Session", (), {"initialize": lambda self: asyncio.sleep(0)})()
        session.names = connectors[toolkit] if toolkit else next(tools for server, tools in MCP_TOOLS.items() if f"marker-{server}" in text)
        yield session

    async def list_all_tools(session):
        return [Tool(name=name, inputSchema={"type": "object", "properties": {}}) for name in session.names]

    monkeypatch.setattr(adapter_tools, "create_session", create_session)
    monkeypatch.setattr(adapter_tools, "_list_all_tools", list_all_tools)

    servers = {name: {"type": "sse", "url": f"http://marker-{name}.invalid/sse"} for name in MCP_TOOLS}
    extensions = tmp_path / "extensions.json"
    extensions.write_text(json.dumps({"mcpServers": servers, "skills": {}}))
    monkeypatch.setenv("OMNI_HARNESS_CONFIG_PATH", str(EXAMPLE))
    monkeypatch.setenv("OMNI_HARNESS_EXTENSIONS_CONFIG_PATH", str(extensions))
    # A placeholder so the connector loader proceeds; nothing is called.
    monkeypatch.setenv("COMPOSIO_API_KEY", "placeholder-not-a-real-key")

    async def accounts(user_id, toolkits):
        return {tk: f"acct-{tk}" for tk in toolkits}

    monkeypatch.setattr(connector_tools, "_active_accounts_for_user", accounts)
    reset_app_config()
    reset_extensions_config()
    reset_mcp_tools_cache()
    yield get_app_config(), set(connectors)
    reset_mcp_tools_cache()
    reset_app_config()
    reset_extensions_config()


def _offered_by_source(app_config, toolkits) -> dict[str, list]:
    from omniharness.agents.called_agents import call_agent_tool
    from omniharness.agents.middlewares.todo_middleware import TodoMiddleware
    from omniharness.mcp.tools import get_mcp_tools
    from omniharness.tools.builtins import setup_agent, update_agent
    from omniharness.tools.connector_tools import _load_connector_tools_async
    from omniharness.tools.tools import get_available_tools

    builtins = get_available_tools(include_mcp=False, subagent_enabled=True, app_config=app_config)
    config_names = {cfg.name for cfg in app_config.tools}
    mcp = asyncio.run(get_mcp_tools())
    return {
        "builtins": [t for t in builtins if t.name not in config_names],
        "config tools": [t for t in builtins if t.name in config_names],
        "agent tools": [call_agent_tool, setup_agent, update_agent, *TodoMiddleware().tools],
        "MCP": [t for t in mcp if not t.name.startswith(BUILT_SERVER)],
        "built MCP": [t for t in mcp if t.name.startswith(BUILT_SERVER)],
        "connectors": asyncio.run(_load_connector_tools_async("guard-user", toolkits)),
    }


def test_every_tool_name_from_every_source_reaches_the_model_within_the_limit(every_source):
    app_config, toolkits = every_source
    sources = _offered_by_source(app_config, toolkits)
    for source, tools in sources.items():
        assert tools, f"the guard loaded no {source} tools: it is not looking"
    tools = list({t.name: t for ts in sources.values() for t in ts}.values())
    full = [t.name for t in tools]
    too_long = [n for n in full if len(n) > 64]
    # The hazard is present in what the guard checks (Article XII).
    assert LIVE in full and f"{BUILT_SERVER}_{BUILT_TOOL}" in too_long, "the guard does not see the long names"

    model = _Recording(messages=iter([]))
    bound = ToolNameBoundaryModel(model).bind_tools(tools)
    assert sorted(model.offered) != sorted(full)
    bad = [n for n in model.offered if not MODEL_SAFE_TOOL_NAME.match(n)]
    assert bad == [], f"offered to the model over the provider's limit: {bad}"
    assert len(set(model.offered)) == len(full), "two tools reached the model under one name"

    # History naming every tool (a chat from before the boundary) is shown
    # aliased, and a reply calling every offered name comes back full.
    history = [AIMessage(content="", tool_calls=[{"name": n, "args": {}, "id": f"c{i}"} for i, n in enumerate(full)])]
    history += [ToolMessage(content="ok", tool_call_id=f"c{i}", name=n) for i, n in enumerate(full)]
    model.messages = iter([AIMessage(content="", tool_calls=[{"name": n, "args": {}, "id": f"r{i}"} for i, n in enumerate(list(model.offered))])])
    reply = bound.invoke(history)
    bad = [n for n in model.shown if not MODEL_SAFE_TOOL_NAME.match(n)]
    assert bad == [], f"shown to the model over the provider's limit: {bad}"
    assert [c["name"] for c in reply.tool_calls] == full, "a reply did not map back to the full names"


# -- GATE: the boundary is in front of every model ----------------------------------


def test_every_agent_middleware_chain_installs_the_boundary(monkeypatch):
    """Lead (and the client and called agents, which build the lead chain) and subagents.

    Every create_agent site reaches one of these builders:
    tests/policy/test_gate_single_dispatch.py.
    """
    from omniharness.agents.lead_agent.agent import _build_middlewares
    from omniharness.agents.middlewares.tool_error_handling_middleware import build_subagent_runtime_middlewares
    from omniharness.agents.middlewares.tool_name_boundary_middleware import ToolNameBoundaryMiddleware
    from omniharness.config.app_config import get_app_config

    app_config = get_app_config()
    chains = {
        "lead": _build_middlewares({"configurable": {}}, model_name=None, app_config=app_config),
        "subagent": build_subagent_runtime_middlewares(app_config=app_config),
    }
    for name, chain in chains.items():
        assert sum(isinstance(m, ToolNameBoundaryMiddleware) for m in chain) == 1, f"the {name} chain has no tool-name boundary"


#: Files that may call bind_tools on a bare model: the boundary itself, and a
#: provider's own bind_tools definition (called through the boundary).
_BIND_TOOLS_EXEMPT = {"packages/harness/omniharness/models/tool_name_boundary.py", "packages/harness/omniharness/models/openai_codex_provider.py"}


def _bind_tools_sites() -> list[tuple[str, int, str]]:
    sites = []
    for root in ("app", "packages"):
        for path in (BACKEND / root).rglob("*.py"):
            rel = str(path.relative_to(BACKEND))
            if "tests" in Path(rel).parts or rel in _BIND_TOOLS_EXEMPT:
                continue
            source = path.read_text(encoding="utf-8")
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "bind_tools":
                    sites.append((rel, node.lineno, ast.get_source_segment(source, node.func.value) or ""))
    return sites


def test_every_direct_bind_tools_goes_through_the_boundary():
    sites = _bind_tools_sites()
    assert sites, "the gate found no bind_tools call: it is not looking"
    offenders = [f"{rel}:{line}" for rel, line, receiver in sites if not receiver.startswith("ToolNameBoundaryModel(")]
    assert offenders == [], f"a model offered tools without the tool-name boundary: {offenders}"


def test_the_bind_tools_gate_detects_a_bare_model(tmp_path):
    """SABOTAGE that runs every time: a bare bind_tools is flagged."""
    source = "model = create_chat_model(name='m').bind_tools(tools)\n"
    calls = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "bind_tools"]
    assert calls and not (ast.get_source_segment(source, calls[0].func.value) or "").startswith("ToolNameBoundaryModel(")
