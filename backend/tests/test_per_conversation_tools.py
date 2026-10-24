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
