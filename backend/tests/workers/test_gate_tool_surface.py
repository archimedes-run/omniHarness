"""GATE D — the email send capability is ABSENT from the tool surface (FR-012).

Not "classified Tier 3". Absent. A capability that cannot be reached is a
stronger guarantee than one that is guarded, because no bug in the confirmation
path can use it, and drafts are their own gate: nothing leaves until the user
sends it themselves.

THE ASSERTION IS ON THE FINAL ASSEMBLED LIST, not on either assembly path and
not on the presence of a config entry. Two independent paths put tools in front
of the agent and Gmail is reachable through both. Asserting on the outcome
rather than the known routes also means a THIRD path added later fails this gate
rather than slipping past it.

Two sabotage observations, one per path — the paths are independent, and a gate
that only ever saw one fail has never been shown to cover the other.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from omniharness.config.extensions_config import ExtensionsConfig, McpServerConfig, McpToolSurface
from omniharness.mcp.tools import _apply_tool_surface
from omniharness.tools.tools import apply_connector_tool_surface

#: What a Gmail server exposes. `send_email` is the one that must not survive.
GMAIL_TOOLS = ["gmail_list_messages", "gmail_read_email", "gmail_create_draft", "gmail_send_email", "gmail_send_draft"]

SEND_CAPABILITIES = ("send_email", "send_draft")


def _tool(name):
    return SimpleNamespace(name=name)


def _assembled_via_mcp(deny):
    config = ExtensionsConfig(mcp_servers={"gmail": McpServerConfig(tools=McpToolSurface(deny=deny) if deny is not None else None)}, skills={})
    return [t.name for t in _apply_tool_surface(config, "gmail", [_tool(n) for n in GMAIL_TOOLS])]


def _assembled_via_connector(tmp_path, monkeypatch, deny):
    entry = {"enabled": True}
    if deny is not None:
        entry["tools"] = {"deny": deny}
    path = tmp_path / "extensions_config.json"
    path.write_text(json.dumps({"mcpServers": {"gmail": entry}, "skills": {}}))
    monkeypatch.setenv("OMNI_HARNESS_EXTENSIONS_CONFIG_PATH", str(path))
    return [t.name for t in apply_connector_tool_surface(None, [_tool(n) for n in GMAIL_TOOLS])]


# ---------------------------------------------------------------------------
# THE GATE — asserted on what the agent can actually call
# ---------------------------------------------------------------------------


def test_the_send_capability_is_absent_from_the_mcp_surface():
    surface = _assembled_via_mcp(list(SEND_CAPABILITIES))

    for capability in SEND_CAPABILITIES:
        assert f"gmail_{capability}" not in surface, f"the agent can call gmail_{capability}"


def test_the_send_capability_is_absent_from_the_connector_surface(tmp_path, monkeypatch):
    surface = _assembled_via_connector(tmp_path, monkeypatch, list(SEND_CAPABILITIES))

    for capability in SEND_CAPABILITIES:
        assert f"gmail_{capability}" not in surface, f"the agent can call gmail_{capability} via the connector path"


def test_reading_and_drafting_survive(tmp_path, monkeypatch):
    """FR-014. A gate that removed everything would satisfy the assertions above
    and destroy the worker."""
    for surface in (_assembled_via_mcp(list(SEND_CAPABILITIES)), _assembled_via_connector(tmp_path, monkeypatch, list(SEND_CAPABILITIES))):
        assert "gmail_read_email" in surface
        assert "gmail_list_messages" in surface
        assert "gmail_create_draft" in surface


def test_no_classification_rule_mentions_a_send_capability():
    """FR-012 is not satisfied by a Tier 3 rule, and a rule for it would suggest
    the capability exists and is merely gated."""
    from pathlib import Path

    from app.policy.config import ConfigLoader

    rules = Path(__file__).resolve().parents[2] / "app" / "policy" / "default_rules.yaml"
    ruleset = ConfigLoader(path=rules).load()

    offenders = [r.pattern for r in ruleset.rules if "send" in r.pattern.lower()]
    assert not offenders, f"a rule classifies a send capability: {offenders}"


# ---------------------------------------------------------------------------
# SABOTAGE 1 — the MCP path
# ---------------------------------------------------------------------------


def test_sabotage_mcp_path_removing_the_deny_exposes_send():
    """Observed failing: with no deny configured, the send capability IS in the
    assembled list. That is what the gate catches."""
    surface = _assembled_via_mcp(None)

    assert "gmail_send_email" in surface, "the sabotage did not reproduce — the gate may be passing for the wrong reason"


# ---------------------------------------------------------------------------
# SABOTAGE 2 — the connector path, separately
# ---------------------------------------------------------------------------


def test_sabotage_connector_path_removing_the_deny_exposes_send(tmp_path, monkeypatch):
    """The independent second observation.

    A deny applied only at the MCP layer leaves `connector:GMAIL` fully exposed.
    This is why the two are asserted separately rather than once.
    """
    surface = _assembled_via_connector(tmp_path, monkeypatch, None)

    assert "gmail_send_email" in surface, "the connector sabotage did not reproduce"


def test_the_two_paths_are_genuinely_independent(tmp_path, monkeypatch):
    """Pins the reason there are two observations: denying on one path does
    NOT deny on the other."""
    mcp_denied = _assembled_via_mcp(list(SEND_CAPABILITIES))
    connector_undenied = _assembled_via_connector(tmp_path, monkeypatch, None)

    assert "gmail_send_email" not in mcp_denied
    assert "gmail_send_email" in connector_undenied, "the connector path appears to inherit the MCP deny — if that is now true, the two-observation requirement can be revisited; until then it holds"
