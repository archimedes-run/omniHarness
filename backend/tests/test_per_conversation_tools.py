"""Per-conversation tool assembly tests (Part A).

Exercises get_available_tools' selection filtering, the always-on pinned
defaults, live connector inclusion, and the provider tool-cap structured error.
Heavy dependencies (config MCP cache, connector loader) are patched so the test
focuses purely on the assembly/selection logic.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from omniharness.tools import tools as tools_mod
from omniharness.tools.tools import ToolCapExceededError, get_available_tools


class _FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = ""
        self.group = None
        # Real tools carry metadata (the source tag is written there).
        self.metadata = None


def _fake_app_config():
    return SimpleNamespace(
        tools=[],
        skill_evolution=None,
        models=[SimpleNamespace(name="m")],
        get_model_config=lambda name: SimpleNamespace(supports_vision=False),
        tool_search=SimpleNamespace(enabled=False),
    )


class _FakeExtConfig:
    """Enabled servers: two pinned + one extra local + one connector-* (stale)."""

    #: A real ExtensionsConfig always has this map (the connector tool surface
    #: reads it); without it the surface check raised and, before 006-G, the
    #: unfiltered connector tools were kept anyway (now nothing is: closed).
    mcp_servers: dict = {}

    def get_enabled_mcp_servers(self):
        return {"filesystem": object(), "postgres": object(), "github": object(), "composio-gmail": object()}


# All MCP tools the file cache would return (prefixed <server>_<tool>).
_CACHED = [
    _FakeTool("filesystem_read_file"),
    _FakeTool("postgres_query"),
    _FakeTool("github_list_repos"),
    _FakeTool("composio-gmail_GMAIL_SEND_EMAIL"),  # stale connector entry — must be dropped
]


def _run(selected_sources, *, user_id=None, max_tools=None, connector_tools=None):
    with (
        patch.object(tools_mod, "is_host_bash_allowed", return_value=True),
        patch("omniharness.mcp.cache.get_cached_mcp_tools", return_value=list(_CACHED)),
        patch("omniharness.config.extensions_config.ExtensionsConfig.from_file", return_value=_FakeExtConfig()),
        patch("omniharness.tools.connector_tools.load_connector_tools", return_value=list(connector_tools or [])),
    ):
        return get_available_tools(
            app_config=_fake_app_config(),
            selected_sources=selected_sources,
            user_id=user_id,
            max_tools=max_tools,
        )


def _names(tools):
    return {t.name for t in tools}


def test_pinned_defaults_always_present_even_when_not_selected():
    # Client selected only the local github server; filesystem + postgres pinned.
    names = _names(_run(selected_sources={"local:github"}))
    assert "filesystem_read_file" in names
    assert "postgres_query" in names
    assert "github_list_repos" in names


def test_unselected_local_source_is_excluded():
    # Select nothing extra → only pinned local tools remain (github dropped).
    names = _names(_run(selected_sources=set()))
    assert "filesystem_read_file" in names
    assert "postgres_query" in names
    assert "github_list_repos" not in names


def test_stale_connector_config_entry_is_always_dropped():
    names = _names(_run(selected_sources={"local:github"}))
    assert "composio-gmail_GMAIL_SEND_EMAIL" not in names


def test_connector_tools_loaded_for_selected_toolkit():
    connector = [_FakeTool("connector-gmail_GMAIL_SEND_EMAIL")]
    names = _names(_run(selected_sources={"connector:GMAIL"}, user_id="user-123", connector_tools=connector))
    assert "connector-gmail_GMAIL_SEND_EMAIL" in names


def test_local_github_and_connector_github_do_not_collide():
    # Selecting the local github server must NOT pull connector GITHUB tools.
    connector = [_FakeTool("connector-github_GITHUB_CREATE_ISSUE")]
    names = _names(_run(selected_sources={"local:github"}, user_id="user-123", connector_tools=connector))
    assert "github_list_repos" in names
    assert "connector-github_GITHUB_CREATE_ISSUE" not in names


def test_connector_tools_not_loaded_without_user():
    connector = [_FakeTool("connector-gmail_GMAIL_SEND_EMAIL")]
    # No user_id → connector loader is not consulted.
    names = _names(_run(selected_sources={"connector:GMAIL"}, user_id=None, connector_tools=connector))
    assert "connector-gmail_GMAIL_SEND_EMAIL" not in names


def test_cap_exceeded_raises_structured_error():
    with pytest.raises(ToolCapExceededError) as exc:
        _run(selected_sources={"local:github"}, max_tools=1)
    assert exc.value.cap == 1
    assert exc.value.count > 1


# -- the tool cap with many connector toolkits (a new chat starts with every
# connected app on: app.gateway.tool_selection) ------------------------------


def _toolkit(slug: str, n: int) -> list[_FakeTool]:
    from omniharness.tools.source_tags import tag_source

    made = [_FakeTool(f"connector-{slug.lower()}_{slug}_T{i}") for i in range(n)]
    for t in made:
        tag_source(t, f"connector:{slug}", "user-123")
    return made


_MANY = {"GMAIL": 13, "GOOGLECALENDAR": 14, "GOOGLEDRIVE": 45, "GITHUB": 90}


def _many_connectors() -> list[_FakeTool]:
    return [t for slug, n in _MANY.items() for t in _toolkit(slug, n)]


def test_connectors_past_the_cap_are_deferred_whole_toolkits_and_the_request_fits():
    from omniharness.tools.builtins.tool_search import get_deferred_registry

    sources = {f"connector:{slug}" for slug in _MANY}
    tools = _run(selected_sources=sources, user_id="user-123", max_tools=128, connector_tools=_many_connectors())
    registry = get_deferred_registry()
    offered = [t.name for t in tools if t.name not in registry.deferred_names]
    assert len(offered) <= 128 - tools_mod.CAP_HEADROOM
    assert "tool_search" in offered
    # Whole toolkits, in order: Gmail, Calendar and Drive fit; GitHub is deferred.
    assert sum(n.startswith("connector-github_") for n in registry.deferred_names) == _MANY["GITHUB"]
    assert all(f"connector-gmail_GMAIL_T{i}" in offered for i in range(13))
    # Nothing is lost: every connector tool is still in the list the tool node runs.
    assert {t.name for t in _many_connectors()} <= _names(tools)


def test_without_deferral_the_toolkits_past_the_cap_are_left_out():
    sources = {f"connector:{slug}" for slug in _MANY}
    tools = _run_no_defer(selected_sources=sources, max_tools=128)
    assert len(tools) <= 128 - tools_mod.CAP_HEADROOM
    assert not any(t.name.startswith("connector-github_") for t in tools)
    assert "tool_search" not in _names(tools)


def _run_no_defer(selected_sources, *, max_tools):
    with (
        patch.object(tools_mod, "is_host_bash_allowed", return_value=True),
        patch("omniharness.mcp.cache.get_cached_mcp_tools", return_value=list(_CACHED)),
        patch("omniharness.config.extensions_config.ExtensionsConfig.from_file", return_value=_FakeExtConfig()),
        patch("omniharness.tools.connector_tools.load_connector_tools", return_value=_many_connectors()),
    ):
        return get_available_tools(app_config=_fake_app_config(), selected_sources=selected_sources, user_id="user-123", max_tools=max_tools, defer_overflow=False)


def test_a_subagent_gets_the_cap_and_no_deferral():
    """A delegated subagent has no deferred-tool filter: its list is capped by
    leaving the overflow toolkits out (task_tool.subagent_base_tools)."""
    import importlib

    task_tool = importlib.import_module("omniharness.tools.builtins.task_tool")

    seen = {}

    def fake_get_available_tools(**kwargs):
        seen.update(kwargs)
        return []

    config = SimpleNamespace(models=[SimpleNamespace(name="m", use="langchain_openai:ChatOpenAI", max_tools=None)], get_model_config=lambda name: SimpleNamespace(name="m", use="langchain_openai:ChatOpenAI", max_tools=None))
    with patch("omniharness.tools.get_available_tools", fake_get_available_tools):
        task_tool.subagent_base_tools(model_name="m", tool_groups=None, app_config=config, selected_sources=["connector:GMAIL"], user_id="u")
    assert seen["max_tools"] == 128 and seen["defer_overflow"] is False


def test_only_tools_that_cannot_be_moved_over_the_cap_still_raise():
    with pytest.raises(ToolCapExceededError):
        _run(selected_sources={"local:github"}, user_id="user-123", max_tools=2, connector_tools=_toolkit("GMAIL", 3))


def test_tool_search_never_promotes_a_request_past_the_cap():
    """Each search promotes up to five deferred tools; past the room left
    under the cap, the oldest promoted tools go back to deferred, so the
    request never grows past it however often the agent searches."""
    from langchain_core.tools import StructuredTool

    from omniharness.tools.builtins.tool_search import get_deferred_registry, tool_search
    from omniharness.tools.source_tags import tag_source

    def real(slug: str, n: int) -> list:
        made = []
        for i in range(n):
            t = StructuredTool.from_function(func=lambda q="": q, name=f"connector-{slug.lower()}_{slug}_T{i}", description=f"{slug} tool {i}")
            tag_source(t, f"connector:{slug}", "user-123")
            made.append(t)
        return made

    connectors = [t for slug, n in _MANY.items() for t in real(slug, n)]
    tools = _run(selected_sources={f"connector:{s}" for s in _MANY}, user_id="user-123", max_tools=128, connector_tools=connectors)
    registry = get_deferred_registry()
    assert registry.max_promoted is not None and registry.max_promoted >= 5
    budget = 128 - tools_mod.CAP_HEADROOM
    seen: set[str] = set()
    for _ in range(25):
        result = tool_search.invoke({"query": "+github"})
        assert "connector-github_" in result
        offered = [t.name for t in tools if t.name not in registry.deferred_names]
        assert len(offered) <= budget, f"{len(offered)} offered after a search, over {budget}"
        seen |= {n for n in offered if n.startswith("connector-github_")}
    # The searches did reach new tools (older ones were returned to deferred).
    assert len(seen) > registry.max_promoted


def test_refused_entries_never_take_a_place_in_the_tier_3_window():
    from app.policy.inspect import recent_tier3

    real = [{"at": f"2026-01-01T00:{i:02d}:00", "tool": "x", "outcome": "executed", "plan_as_stated": "p", "targets": []} for i in range(60)]
    refused = [{"kind": "refused-plan", "at": f"2026-01-02T00:{i:02d}:00", "tool": "ledger_apply", "outcome": "refused", "plan_as_stated": "r", "targets": []} for i in range(30)]
    rows = recent_tier3(real + refused)
    assert sum(r.outcome == "executed" for r in rows) == 50
    assert sum(r.outcome == "refused" for r in rows) == 20


def test_a_search_never_returns_a_tool_this_step_is_calling_to_deferred():
    from types import SimpleNamespace

    from langchain_core.messages import AIMessage
    from langchain_core.tools import StructuredTool

    from omniharness.tools.builtins.tool_search import DeferredToolRegistry, set_deferred_registry, tool_search

    registry = DeferredToolRegistry(max_promoted=5)
    for i in range(20):
        registry.register(StructuredTool.from_function(func=lambda q="": q, name=f"gh_T{i:02d}", description="github tool"))
    set_deferred_registry(registry)
    tool_search.invoke({"query": "select:" + ",".join(f"gh_T{i:02d}" for i in range(5))})
    assert registry.promoted_names == {f"gh_T{i:02d}" for i in range(5)}
    # This step calls T00 and T01 alongside a new search: they stay promoted.
    state = {"messages": [AIMessage(content="", tool_calls=[{"name": "gh_T00", "args": {}, "id": "a"}, {"name": "gh_T01", "args": {}, "id": "b"}, {"name": "tool_search", "args": {}, "id": "c"}])]}
    tool_search.func(query="+gh_T1", runtime=SimpleNamespace(state=state))
    assert {"gh_T00", "gh_T01"} <= registry.promoted_names
    assert len(registry.promoted_names) <= 5


def test_with_no_room_under_the_cap_deferred_tools_are_not_offered():
    from langchain_core.tools import StructuredTool

    from omniharness.agents.lead_agent.prompt import get_deferred_tools_prompt_section
    from omniharness.tools.builtins.tool_search import DeferredToolRegistry, set_deferred_registry, tool_search

    registry = DeferredToolRegistry(max_promoted=0)
    registry.register(StructuredTool.from_function(func=lambda q="": q, name="gh_T00", description="github tool"))
    set_deferred_registry(registry)
    assert get_deferred_tools_prompt_section() == ""
    assert "No more tools can be loaded" in tool_search.invoke({"query": "select:gh_T00"})
    assert registry.promoted_names == set()


def test_a_restated_ledger_plan_carries_no_stored_titles():
    from datetime import UTC, datetime, timedelta

    from app.policy.confirm import restate
    from app.policy.middleware import PolicyMiddleware
    from app.policy.models import PendingAction, Tier

    change = {"op": "update_task", "project": "Launch", "task": "report", "status": "done", "_pin": {"task_id": "t1", "short_id": "T-3", "title": "SECRET STORED TITLE", "project_id": "p1", "project_name": "STORED PROJECT"}}
    from app.ledger.service import render

    targets = render([change])
    assert "SECRET STORED TITLE" in targets[0]
    action = PendingAction(plan_text="", tool_name="ledger_apply", arguments={"changes": [change]}, targets=targets, tier_at_statement=Tier.TIER_3, expires_at=datetime.now(UTC) + timedelta(hours=1))
    action.plan_text = PolicyMiddleware._plan_text("ledger_apply", targets, action_id=action.id, arguments=action.arguments)
    text = restate(action)
    assert "T-3" in text and "SECRET STORED TITLE" not in text and "STORED PROJECT" not in text


def test_a_refusal_is_recorded_once_per_outer_turn_without_reading_the_log(tmp_path, monkeypatch):
    from app.policy.audit import PolicyAuditLog

    log = PolicyAuditLog(path=tmp_path / "audit.jsonl", actor="default")
    monkeypatch.setattr(PolicyAuditLog, "entries", lambda self: (_ for _ in ()).throw(AssertionError("read the whole log")))
    common = {"tool": "ledger_apply", "targets": ["x"], "reason": "r", "owner_id": "u", "requester": "lead_agent", "origin": "content", "origin_source": "web_fetch"}
    assert log.record_refused(thread_id="t1", turn_key="run:1", **common) is not None
    assert log.record_refused(thread_id="t1", turn_key="run:1", **common) is None
    # No thread: the run tells turns apart.
    assert log.record_refused(thread_id=None, turn_key="run:2", **common) is not None
    assert log.record_refused(thread_id=None, turn_key="run:3", **common) is not None
    # A fresh index (a restart) seeds itself from the log's tail.
    import app.policy.audit as audit

    audit._SEEN.clear()
    assert log.record_refused(thread_id="t1", turn_key="run:1", **common) is None


def test_an_invited_agent_shares_its_inviting_turn():
    from types import SimpleNamespace

    from app.policy.middleware import PolicyMiddleware

    middleware = PolicyMiddleware.__new__(PolicyMiddleware)
    lead = SimpleNamespace(runtime=SimpleNamespace(context={"run_id": "r-1", "thread_id": "t"}), state={"messages": []})
    assert middleware._turn_key(lead) == "run:r-1"
    invited = SimpleNamespace(runtime=SimpleNamespace(context={PolicyMiddleware.TURN_KEY: "run:r-1", "thread_id": "t"}), state={"messages": [SimpleNamespace(type="human", id="sub-1")]})
    assert middleware._turn_key(invited) == "run:r-1"


def test_the_inviting_turn_hands_its_turn_to_the_agent_it_invites(monkeypatch):
    from types import SimpleNamespace

    from app.policy.middleware import PolicyMiddleware
    from omniharness.agents.invitation import invited_agent_context

    middleware = PolicyMiddleware.__new__(PolicyMiddleware)
    monkeypatch.setattr(PolicyMiddleware, "_origin", lambda self, request: ("user", "", ""))
    monkeypatch.setattr(PolicyMiddleware, "_requester", lambda self, request: "lead_agent")
    monkeypatch.setattr(PolicyMiddleware, "_delegation_chain", lambda self, request: ())
    monkeypatch.setattr(PolicyMiddleware, "_private_read", lambda self, request, ruleset=None: SimpleNamespace(private=False))
    lead = SimpleNamespace(runtime=SimpleNamespace(context={"run_id": "r-9", "thread_id": "t"}), state={"messages": []})
    context = invited_agent_context(middleware._inviting_for(lead), "researcher")
    assert context[PolicyMiddleware.TURN_KEY] == "run:r-9"


def test_a_refusal_whose_write_failed_can_still_be_recorded_later_in_the_turn(tmp_path, monkeypatch):
    import pytest

    from app.policy.audit import PolicyAuditLog

    log = PolicyAuditLog(path=tmp_path / "audit.jsonl", actor="default")
    common = {"tool": "ledger_apply", "targets": ["x"], "reason": "r", "owner_id": "u", "requester": "lead_agent", "origin": "content", "origin_source": "web_fetch"}
    # Seed this file's index first (a successful record), so only the write fails.
    assert log.record_refused(thread_id="t8", turn_key="run:8", **common) is not None
    real_open = type(log.path).open

    def failing_open(self, *a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(type(log.path), "open", failing_open)
    with pytest.raises(OSError):
        log.record_refused(thread_id="t9", turn_key="run:9", **common)
    monkeypatch.setattr(type(log.path), "open", real_open)
    assert log.record_refused(thread_id="t9", turn_key="run:9", **common) is not None, "the failed write swallowed the turn's refusal"
