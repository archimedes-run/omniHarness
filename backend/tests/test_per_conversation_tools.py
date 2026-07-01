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
        self.group = None


def _fake_app_config():
    return SimpleNamespace(
        tools=[],
        skill_evolution=None,
        models=[SimpleNamespace(name="m")],
        get_model_config=lambda name: SimpleNamespace(supports_vision=False),
        tool_search=SimpleNamespace(enabled=False),
        acp_agents={},
    )


class _FakeExtConfig:
    """Enabled servers: two pinned + one extra local + one connector-* (stale)."""

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
