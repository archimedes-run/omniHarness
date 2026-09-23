"""FR-012 on the CONNECTOR path: the send capability must not exist.

The deny list was correct and matched nothing. Connector tools arrive as
`connector-gmail_GMAIL_SEND_EMAIL`; the filter stripped only `gmail_`, found no
server, and therefore applied no surface — keeping every tool, including send.

FR-012 chose absence over classification deliberately: "a capability that cannot
be reached is a stronger guarantee than one that is guarded". For this path it
was neither absent nor classified — Tier 3 only by the unmatched default, which
is luck rather than design.
"""

from __future__ import annotations

import json

import pytest
from langchain_core.tools import tool as make_tool

from omniharness.tools.tools import apply_connector_tool_surface

#: THE TEST SUPPLIES ITS OWN DENY LIST. It used to read whatever
#: extensions_config.json the developer happened to have, so it passed on a
#: machine with one and raised UnboundLocalError in CI, which has none — a test
#: inheriting the condition it asserts, one day after Article XIV was extended
#: to forbid exactly that. Now the fixture writes the config and points the
#: loader at it, so the result is the same everywhere.
_CONFIG = {
    "mcp_servers": {
        "gmail": {
            "enabled": True,
            "type": "stdio",
            "command": "npx",
            "args": [],
            "tools": {"deny": ["send_email", "send_draft", "send_message"]},
        }
    }
}


@pytest.fixture(autouse=True)
def extensions_config(tmp_path, monkeypatch):
    path = tmp_path / "extensions_config.json"
    path.write_text(json.dumps(_CONFIG))
    monkeypatch.setenv("OMNI_HARNESS_EXTENSIONS_CONFIG_PATH", str(path))
    return path


def _named(name: str):
    @make_tool
    def stub(x: str) -> str:
        """stub"""
        return x

    stub.name = name
    return stub


SEND_SHAPED = [
    "connector-gmail_GMAIL_SEND_EMAIL",
    "connector-gmail_GMAIL_SEND_DRAFT",
]

KEEP = [
    "connector-gmail_GMAIL_FETCH_EMAILS",
    "connector-gmail_GMAIL_CREATE_EMAIL_DRAFT",
]


def test_the_filter_keeps_what_it_should():
    """POSITIVE CONTROL. A filter that dropped everything would satisfy every
    assertion below while removing the product."""
    kept = {t.name for t in apply_connector_tool_surface(None, [_named(n) for n in KEEP])}
    assert kept == set(KEEP)


@pytest.mark.parametrize("name", SEND_SHAPED)
def test_a_send_capability_is_absent_from_the_connector_surface(name):
    kept = {t.name for t in apply_connector_tool_surface(None, [_named(name), _named(KEEP[0])])}
    assert name not in kept, f"{name} reached the agent; FR-012 requires it absent, not guarded"
    assert KEEP[0] in kept, "the filter removed a permitted tool too"


def test_the_deny_is_not_case_sensitive():
    """The deny list is written `send_email`; the connector names the same
    capability `GMAIL_SEND_EMAIL`. A guarantee that turns on case is not one."""
    kept = {t.name for t in apply_connector_tool_surface(None, [_named("connector-gmail_gmail_send_email")])}
    assert kept == set()
