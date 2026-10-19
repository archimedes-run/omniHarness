"""T090a-d — every tool source's state is visible (FR-040, FR-041, SC-024)."""

from __future__ import annotations

import json
import socket
import threading
import time
from types import SimpleNamespace

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.tool_sources import describe_tool_sources

TOOLKITS = [{"slug": "GMAIL", "name": "Gmail"}, {"slug": "SLACK", "name": "Slack"}]


def _load(loaded: bool, tools: int = 0, error: str | None = None):
    return SimpleNamespace(loaded=loaded, tool_count=tools, error=error)


def _by_id(view) -> dict:
    return {s.id: s for s in view.sources}


def test_the_four_local_states_are_distinct() -> None:
    view = describe_tool_sources(
        servers={"github": SimpleNamespace(enabled=True), "postgres": SimpleNamespace(enabled=True), "filesystem": SimpleNamespace(enabled=False)},
        last_loads={"github": _load(True, 26), "postgres": _load(False, error="ConnectError: connection refused")},
        connector_toolkits=[],
        authorised=None,
        selected=None,
    )
    s = _by_id(view)
    assert s["local:session-watcher"].state == "not-configured"  # expected, absent
    assert s["local:filesystem"].state == "disabled"
    assert s["local:postgres"].state == "unreachable" and "connection refused" in s["local:postgres"].error
    assert s["local:github"].state == "live" and s["local:github"].tool_count == 26
    assert view.failing == 1


def test_an_authorised_connector_not_selected_here_is_not_called_unauthorised() -> None:
    """SC-024. Gmail was ACTIVE while the assistant asked for OAuth, because
    the conversation had not selected it."""
    view = describe_tool_sources(servers={}, last_loads={}, connector_toolkits=TOOLKITS, authorised={"GMAIL"}, selected={"local:filesystem"}, thread_id="t1")
    s = _by_id(view)
    assert s["connector:GMAIL"].state == "authorised-not-selected"
    assert s["connector:SLACK"].state == "not-authorised"

    selected = describe_tool_sources(servers={}, last_loads={}, connector_toolkits=TOOLKITS, authorised={"GMAIL"}, selected={"connector:GMAIL"}, thread_id="t1")
    assert _by_id(selected)["connector:GMAIL"].state == "authorised-selected"


def test_without_composio_connectors_are_unavailable_not_unauthorised() -> None:
    view = describe_tool_sources(servers={}, last_loads={}, connector_toolkits=TOOLKITS, authorised=None, selected=None)
    assert view.connectors_available is False
    assert not [s for s in view.sources if s.kind == "connector"]


# --- the route, over a REAL load (T090d) --------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live_and_dead(tmp_path, monkeypatch):
    """One real MCP server (Feature 001's watcher), one at a dead port, one
    disabled — configured the way production reads them."""
    import uvicorn
    from session_watcher.server import WatcherService, build_app

    from omniharness.config.extensions_config import reset_extensions_config
    from omniharness.mcp import cache

    port, dead = _free_port(), _free_port()
    server = uvicorn.Server(uvicorn.Config(build_app(WatcherService(root=tmp_path)), host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.02)

    ext = tmp_path / "extensions_config.json"
    ext.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "session-watcher": {"enabled": True, "type": "sse", "url": f"http://127.0.0.1:{port}/sse"},
                    "dead-server": {"enabled": True, "type": "sse", "url": f"http://127.0.0.1:{dead}/sse"},
                    "switched-off": {"enabled": False, "type": "sse", "url": f"http://127.0.0.1:{dead}/sse"},
                },
                "skills": {},
            }
        )
    )
    monkeypatch.setenv("OMNI_HARNESS_EXTENSIONS_CONFIG_PATH", str(ext))
    reset_extensions_config()
    cache.reset_mcp_tools_cache()
    yield
    server.should_exit = True
    cache.reset_mcp_tools_cache()
    reset_extensions_config()


def test_a_dead_port_reads_unreachable_not_absent(live_and_dead) -> None:
    from app.gateway.routers import tool_sources

    app = make_authed_test_app()
    app.include_router(tool_sources.router)
    app.state.composio_client = None

    with TestClient(app) as client:
        body = client.get("/api/tool-sources").json()

    s = {x["id"]: x for x in body["sources"]}
    assert s["local:session-watcher"]["state"] == "live" and s["local:session-watcher"]["tool_count"] == 2  # positive control
    assert s["local:dead-server"]["state"] == "unreachable", s["local:dead-server"]
    assert s["local:dead-server"]["error"], "unreachable without saying why"
    assert s["local:switched-off"]["state"] == "disabled"
    assert body["failing"] == 1


def test_the_gateway_serves_the_route() -> None:
    from app.gateway.app import create_app

    assert "/api/tool-sources" in {getattr(r, "path", None) for r in create_app().routes}
