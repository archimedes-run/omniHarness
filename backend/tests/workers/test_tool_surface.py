"""Per-tool deny at BOTH assembly points (T008-T011, FR-012, FR-013).

FR-012 requires the email send capability to be ABSENT from what the agent can
call, not merely classified as high-risk. A capability that cannot be reached is
not one a bug in the permission path can use.

Two independent paths put tools in front of the agent, and Gmail is reachable
through both:

    local:<server>     mcp/tools.py, per server
    connector:<SLUG>   tools/tools.py, live per user — never touches mcp/tools.py

A deny applied at only one leaves the other fully exposed, which is a gate whose
scope boundary is exactly where the bypass lives.
"""

from __future__ import annotations

from types import SimpleNamespace

from omniharness.config.extensions_config import ExtensionsConfig, McpServerConfig, McpToolSurface
from omniharness.mcp.tools import _apply_tool_surface
from omniharness.tools.tools import apply_connector_tool_surface


def _tool(name: str):
    return SimpleNamespace(name=name)


def _config(server: str, **surface):
    return ExtensionsConfig(
        mcp_servers={server: McpServerConfig(tools=McpToolSurface(**surface) if surface else None)},
        skills={},
    )


# ---------------------------------------------------------------------------
# T008 — POSITIVE CONTROL. The tool IS present when nothing denies it.
# ---------------------------------------------------------------------------


def test_positive_control_the_tool_is_present_when_not_denied():
    """Without this, an absence proves nothing — the filter might drop
    everything, or the tool might never have been in the list (Article XII)."""
    tools = [_tool("gmail_read_email"), _tool("gmail_send_email")]

    kept = _apply_tool_surface(_config("gmail"), "gmail", tools)

    assert [t.name for t in kept] == ["gmail_read_email", "gmail_send_email"]


def test_positive_control_for_the_connector_path():
    tools = [_tool("gmail_read_email"), _tool("gmail_send_email")]

    kept = apply_connector_tool_surface(None, tools)

    assert len(kept) == 2, "with no deny configured the connector surface must be untouched"


# ---------------------------------------------------------------------------
# The MCP assembly point
# ---------------------------------------------------------------------------


def test_a_denied_tool_is_absent_from_the_mcp_surface():
    tools = [_tool("gmail_read_email"), _tool("gmail_send_email")]

    kept = _apply_tool_surface(_config("gmail", deny=["send_email"]), "gmail", tools)

    names = [t.name for t in kept]
    assert "gmail_send_email" not in names, "the send capability is still reachable"
    assert "gmail_read_email" in names, "denying one tool must not remove the others"


def test_deny_names_are_unprefixed():
    """The user configures a server; they should not have to know that assembly
    renames tools to <server>_<tool>."""
    tools = [_tool("gmail_send_email")]

    assert not _apply_tool_surface(_config("gmail", deny=["send_email"]), "gmail", tools)
    # the prefixed form must NOT be what works, or the contract is a lie
    assert _apply_tool_surface(_config("gmail", deny=["gmail_send_email"]), "gmail", tools)


def test_allow_is_a_whitelist():
    tools = [_tool("gmail_read_email"), _tool("gmail_send_email"), _tool("gmail_create_draft")]

    kept = _apply_tool_surface(_config("gmail", allow=["read_email", "create_draft"]), "gmail", tools)

    assert sorted(t.name for t in kept) == ["gmail_create_draft", "gmail_read_email"]


def test_a_server_with_no_surface_is_untouched():
    tools = [_tool("filesystem_read"), _tool("filesystem_write")]

    assert len(_apply_tool_surface(_config("filesystem"), "filesystem", tools)) == 2


# ---------------------------------------------------------------------------
# The connector assembly point — the one a single-path deny would miss
# ---------------------------------------------------------------------------


def test_a_denied_tool_is_absent_from_the_connector_surface(tmp_path, monkeypatch):
    """The bypass this spike exists to close."""
    import json

    cfg = tmp_path / "extensions_config.json"
    cfg.write_text(json.dumps({"mcpServers": {"gmail": {"enabled": True, "tools": {"deny": ["send_email"]}}}, "skills": {}}))
    monkeypatch.setenv("OMNI_HARNESS_EXTENSIONS_CONFIG_PATH", str(cfg))

    tools = [_tool("gmail_read_email"), _tool("gmail_send_email")]
    kept = apply_connector_tool_surface(None, tools)

    names = [t.name for t in kept]
    assert "gmail_send_email" not in names, "the connector path still exposes the send capability. A deny applied only at the MCP layer leaves connector:GMAIL fully exposed."
    assert "gmail_read_email" in names


def test_an_unreadable_config_does_not_break_tool_loading(monkeypatch):
    """Failing open on surface filtering is wrong for security but failing HARD
    breaks every tool. The deny is a surface control; classification (FR-009)
    is what fails closed."""
    monkeypatch.setenv("OMNI_HARNESS_EXTENSIONS_CONFIG_PATH", "/nonexistent/path.json")

    kept = apply_connector_tool_surface(None, [_tool("gmail_read_email")])

    assert len(kept) == 1
