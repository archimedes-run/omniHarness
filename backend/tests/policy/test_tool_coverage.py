"""Every registered tool resolves to an EXPLICIT rule; an unruled one is refused (007).

Through the production composition root: `create_app()` and its lifespan, with
an extensions config naming every MCP server we ship config for. The servers
themselves are not started (no npx, no network, no accounts): the MCP adapter's
session is replaced so `list_tools` answers with the names each server's
published package ACTUALLY exposes (tests/policy/real_tool_names.py). Everything
after that — prefixing by langchain-mcp-adapters, the deny surface, the cache,
the coverage listener, GET /api/tool-sources, the policy gate — is production.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent))
from real_tool_names import ALL_REAL_TOOLS, DENIED, MCP_SERVER_TOOLS  # noqa: E402

os.environ.setdefault("AUTH_JWT_SECRET", "test-secret-key-tool-coverage-min-32-chars")
EXAMPLE = Path(__file__).resolve().parents[3] / "config.example.yaml"
SHIPPED_RULES = Path(__file__).resolve().parents[2] / "app" / "policy" / "default_rules.yaml"

#: How each server is reached in the test's extensions config; the fake MCP
#: session finds the server by this marker in its connection.
SERVERS = {
    "filesystem": {"type": "stdio", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp/files"]},
    "github": {"type": "stdio", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]},
    "postgres": {"type": "stdio", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-postgres", "postgresql://localhost/db"]},
    "gmail": {"type": "stdio", "command": "npx", "args": ["-y", "@gongrzhe/server-gmail-autoauth-mcp"], "tools": {"deny": ["send_email", "send_draft", "send_message"]}},
    "googlecalendar": {"type": "stdio", "command": "npx", "args": ["-y", "@cocal/google-calendar-mcp"]},
    "session-watcher": {"type": "sse", "url": "http://watcher.invalid:18101/sse"},
    "github-issue-connector": {"type": "sse", "url": "http://issues.invalid:18100/sse"},
}
MARKERS = {
    "server-filesystem": "filesystem",
    "server-github": "github",
    "server-postgres": "postgres",
    "server-gmail-autoauth-mcp": "gmail",
    "google-calendar-mcp": "googlecalendar",
    "watcher.invalid": "session-watcher",
    "issues.invalid": "github-issue-connector",
    "user-added.invalid": "my-tools",
}
TOOLS_BY_SERVER = {**MCP_SERVER_TOOLS, "my-tools": ("do_thing",)}


@pytest.fixture
def fake_mcp(monkeypatch):
    """Each server's list_tools answers with its real tool names."""
    import langchain_mcp_adapters.tools as adapter_tools
    from mcp.types import Tool

    @asynccontextmanager
    async def create_session(connection, **_):
        text = json.dumps(connection, default=str)
        server = next(name for marker, name in MARKERS.items() if marker in text)

        class Session:
            async def initialize(self):
                return None

        session = Session()
        session.server = server
        yield session

    async def list_all_tools(session):
        return [Tool(name=name, inputSchema={"type": "object", "properties": {}}) for name in TOOLS_BY_SERVER[session.server]]

    monkeypatch.setattr(adapter_tools, "create_session", create_session)
    monkeypatch.setattr(adapter_tools, "_list_all_tools", list_all_tools)


def _gateway(tmp_path, monkeypatch, servers: dict, rules_text: str | None = None):
    from app.gateway.auth.config import AuthConfig, set_auth_config
    from app.policy import coverage
    from omniharness.config.app_config import reset_app_config
    from omniharness.config.extensions_config import reset_extensions_config
    from omniharness.mcp import load_report
    from omniharness.mcp.cache import reset_mcp_tools_cache

    config = yaml.safe_load(EXAMPLE.read_text())
    config["database"] = {"backend": "sqlite", "sqlite_dir": str(tmp_path / "data")}
    config["policy"] = {"enabled": True, "state_dir": str(tmp_path / "policy")}
    if rules_text is not None:
        rules = tmp_path / "rules.yaml"
        rules.write_text(rules_text)
        config["policy"]["rules_path"] = str(rules)
    config["trigger_engine"] = {"enabled": False}
    config.setdefault("memory", {})["enabled"] = False
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config))
    extensions = tmp_path / "extensions.json"
    extensions.write_text(json.dumps({"mcpServers": servers, "skills": {}}))
    monkeypatch.setenv("OMNI_HARNESS_CONFIG_PATH", str(path))
    monkeypatch.setenv("OMNI_HARNESS_EXTENSIONS_CONFIG_PATH", str(extensions))
    monkeypatch.chdir(tmp_path)
    reset_app_config()
    reset_extensions_config()
    reset_mcp_tools_cache()
    monkeypatch.setattr(load_report, "_LAST", {})
    monkeypatch.setattr(coverage, "_reported", set())
    set_auth_config(AuthConfig(jwt_secret=os.environ["AUTH_JWT_SECRET"]))

    import app.gateway.deps as deps
    from app.gateway.app import create_app

    monkeypatch.setattr(deps, "_cached_local_provider", None)
    monkeypatch.setattr(deps, "_cached_repo", None)
    return create_app()


@pytest.fixture
def cleanup():
    yield
    from omniharness.config.app_config import reset_app_config
    from omniharness.config.extensions_config import reset_extensions_config
    from omniharness.mcp.cache import reset_mcp_tools_cache

    reset_mcp_tools_cache()
    reset_app_config()
    reset_extensions_config()


def _login(client):
    resp = client.post("/api/v1/auth/initialize", json={"email": "owner@example.com", "password": "Str0ng!Pass99"})
    assert resp.status_code in (200, 201), resp.text
    csrf = client.cookies.get("csrf_token")
    if csrf:
        client.headers["X-CSRF-Token"] = csrf


# ---------------------------------------------------------------------------
# The shipped rules name every real tool (fast; the sabotage target)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def shipped():
    from app.policy.config import ConfigLoader

    ruleset = ConfigLoader(path=SHIPPED_RULES).load()
    assert not ruleset.unreadable, ruleset.error
    return ruleset


@pytest.mark.parametrize("tool", [t for t in ALL_REAL_TOOLS if t not in DENIED])
def test_every_real_tool_has_an_explicit_rule(shipped, tool):
    from app.policy.classify import classify

    decision = classify(tool, {}, shipped)
    assert not decision.refused and decision.deciding_rule is not None, f"{tool} has no rule in the shipped rules: it would be refused"


def test_the_calendar_tools_get_their_intended_tiers(shipped):
    """The bug itself: hyphenated Calendar names reach their rules."""
    from app.policy.classify import classify
    from app.policy.models import Tier

    def tier(name, args=None):
        return classify(name, args or {}, shipped).tier

    assert tier("googlecalendar_create-event") is Tier.TIER_2
    assert tier("googlecalendar_search-events") is Tier.TIER_1
    assert tier("googlecalendar_list-events") is Tier.TIER_1
    assert tier("googlecalendar_update-event") is Tier.TIER_3
    assert tier("googlecalendar_delete-event") is Tier.TIER_3
    assert tier("googlecalendar_respond-to-event") is Tier.TIER_3
    # The server's argument is `sendUpdates`. Without the camelCase exception,
    # an invite-sending create would have become Tier 2 once its name matched.
    assert tier("googlecalendar_create-event", {"sendUpdates": "all"}) is Tier.TIER_3
    assert tier("googlecalendar_create-event", {"sendUpdates": "externalOnly"}) is Tier.TIER_3
    assert tier("googlecalendar_create-event", {"sendUpdates": "none"}) is Tier.TIER_2


def test_a_label_is_not_created_silently(shipped):
    """`gmail_get*` made get_or_create_label Tier 1 although it writes."""
    from app.policy.classify import classify
    from app.policy.models import Tier

    assert classify("gmail_get_or_create_label", {}, shipped).tier is Tier.TIER_2


# ---------------------------------------------------------------------------
# Through the production composition root
# ---------------------------------------------------------------------------


def test_every_registered_tool_resolves_to_an_explicit_rule(tmp_path, monkeypatch, fake_mcp, cleanup, caplog):
    """Startup check + MCP load check + tool-sources view, all through create_app()."""
    from app.policy.coverage import has_rule
    from app.policy.registration import shared_loader
    from omniharness.mcp.cache import loaded_mcp_tools
    from omniharness.tools.tools import get_available_tools, registrable_tool_names

    app = _gateway(tmp_path, monkeypatch, SERVERS)
    caplog.set_level(logging.INFO)
    with TestClient(app) as client:
        _login(client)
        # The startup log: the built-ins and config tools, before MCP loads.
        assert any("registered tool(s) resolve to an explicit rule" in r.getMessage() for r in caplog.records), "the startup coverage check did not run"

        # Loads the MCP tools the way production does (lazily, here).
        view = client.get("/api/tool-sources").json()

        mcp = [t.name for t in loaded_mcp_tools() or []]
        assert len(mcp) == sum(len(v) for v in MCP_SERVER_TOOLS.values()) - len(DENIED), "the fake servers did not load"
        assert "gmail_send_email" not in mcp, "the deny surface stopped applying"
        assert "googlecalendar_create-event" in mcp, "the adapter's prefixing changed; the rules are written against <server>_<tool>"

        ruleset = shared_loader(app.state.config.policy).load(notify=False)
        registered = registrable_tool_names(app.state.config)
        unruled = [n for n in registered if not has_rule(n, ruleset)]
        assert unruled == [], f"registered tools with no policy rule (they would be refused): {unruled}"
        assert set(mcp) <= set(registered)

        # Nothing get_available_tools can offer is missing from the list the
        # startup check reads.
        offered = {t.name for t in get_available_tools(subagent_enabled=True, app_config=app.state.config)}
        assert offered <= set(registered), f"offered but not checked at startup: {sorted(offered - set(registered))}"

        live = {s["name"]: s for s in view["sources"] if s["state"] == "live"}
        assert set(live) == set(SERVERS)
        for name, source in live.items():
            assert source["unruled_tools"] == [], f"{name}: {source['unruled_tools']}"
        assert not any("have NO policy rule" in r.getMessage() for r in caplog.records)


def test_an_unruled_tool_is_refused_and_listed(tmp_path, monkeypatch, fake_mcp, cleanup, caplog):
    """A user-added server: its tool is listed in the log and the sources view,
    kept from the model, and refused if called."""
    from langchain_core.messages import ToolMessage

    from omniharness.agents.middlewares.policy_hook import build_policy_middleware
    from omniharness.mcp.cache import loaded_mcp_tools

    servers = {"session-watcher": SERVERS["session-watcher"], "my-tools": {"type": "sse", "url": "http://user-added.invalid/sse"}}
    app = _gateway(tmp_path, monkeypatch, servers)
    caplog.set_level(logging.INFO)
    with TestClient(app) as client:
        _login(client)
        view = client.get("/api/tool-sources").json()

        by_name = {s["name"]: s for s in view["sources"]}
        assert by_name["my-tools"]["unruled_tools"] == ["my-tools_do_thing"]
        assert by_name["session-watcher"]["unruled_tools"] == []
        listed = [r.getMessage() for r in caplog.records if "have NO policy rule" in r.getMessage()]
        assert listed and "my-tools_do_thing" in listed[0], "the unruled tool was not listed in the log"

        gate = build_policy_middleware(app.state.config)
        tools = {t.name: t for t in loaded_mcp_tools()}

        ran = []
        call = SimpleNamespace(tool_call={"name": "my-tools_do_thing", "args": {}, "id": "c1"}, tool=tools["my-tools_do_thing"], runtime=None, state={})
        result = gate.wrap_tool_call(call, lambda request: ran.append(request) or "did it")
        assert ran == [], "an unruled tool RAN"
        assert isinstance(result, ToolMessage) and "no permission policy rule covers it" in result.content

        async def handler(request):
            ran.append(request)
            return "did it"

        result = asyncio.run(gate.awrap_tool_call(call, handler))
        assert ran == [], "an unruled tool RAN on the async path"
        assert isinstance(result, ToolMessage) and "no permission policy rule covers it" in result.content

        # And it is not offered to the model at all.
        seen = []

        class Request(SimpleNamespace):
            def override(self, **changes):
                return Request(**{**self.__dict__, **changes})

        request = Request(messages=[], tools=list(tools.values()), runtime=None, state={})
        gate.wrap_model_call(request, lambda r: seen.append([t.name for t in r.tools]) or SimpleNamespace(result=[]))
        assert seen == [["session-watcher_list_coding_sessions", "session-watcher_get_session_status"]]


def test_an_action_waiting_on_a_rule_that_is_removed_is_not_run(tmp_path):
    """Pending for a tool whose rule is then deleted: superseded, never run."""
    from datetime import UTC, datetime, timedelta

    from app.policy.config import ConfigLoader
    from app.policy.models import Outcome, PendingAction, Tier
    from app.policy.pending import PendingStore
    from app.policy.supersede import supersede_unneeded

    store = PendingStore(directory=tmp_path / "pending")
    now = datetime.now(UTC)
    action = PendingAction(plan_text="x", tool_name="custom_send", arguments={}, targets=["a"], tier_at_statement=Tier.TIER_3, expires_at=now + timedelta(hours=1))
    store.save(action)
    rules = tmp_path / "rules.yaml"
    rules.write_text('policy:\n  rules:\n    - pattern: "ls"\n      tier: 1\n')
    superseded = supersede_unneeded(store, ConfigLoader(path=rules).load(), now)
    assert [a.id for a in superseded] == [action.id]
    assert store.get(action.id).outcome is Outcome.SUPERSEDED
    assert "no policy rule" in store.get(action.id).outcome_reason


def test_the_inspector_says_refused_not_tier_3(shipped):
    """The policy page's tier check must not show a tier for a tool it refuses."""
    from app.policy.inspect import tier_check

    unknown = tier_check("some_tool_nobody_classified", {}, shipped)
    assert unknown.refused and unknown.deciding_rule is None
    assert "no permission policy rule covers it" in unknown.in_plain_words
    assert not tier_check("googlecalendar_search-events", {}, shipped).refused
