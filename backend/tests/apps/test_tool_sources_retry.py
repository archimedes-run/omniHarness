"""MCP Suite, Connected: Retry loads the MCP servers again, through the gateway
`create_app()` builds (Feature 006).

A server that was down when first loaded stays unreachable on a plain read
(the load is cached), and reads live only after Retry, once it is up. A server
still down after Retry stays unreachable, with its error: Retry never reports a
fix it did not observe.
"""

from __future__ import annotations

import json
import socket
import threading
import time

import pytest


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def late_server(gateway, tmp_path):
    from omniharness.config.extensions_config import reset_extensions_config
    from omniharness.mcp import cache

    port, dead = _free_port(), _free_port()
    (gateway.tmp / "extensions.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "late": {"enabled": True, "type": "sse", "url": f"http://127.0.0.1:{port}/sse"},
                    "still-dead": {"enabled": True, "type": "sse", "url": f"http://127.0.0.1:{dead}/sse"},
                },
                "skills": {},
            }
        )
    )
    reset_extensions_config()
    cache.reset_mcp_tools_cache()
    servers = []

    def start():
        import uvicorn
        from session_watcher.server import WatcherService, build_app

        server = uvicorn.Server(uvicorn.Config(build_app(WatcherService(root=tmp_path)), host="127.0.0.1", port=port, log_level="warning"))
        threading.Thread(target=server.run, daemon=True).start()
        while not server.started:
            time.sleep(0.02)
        servers.append(server)

    yield start
    for server in servers:
        server.should_exit = True
    cache.reset_mcp_tools_cache()


def _states(body: dict) -> dict:
    return {s["id"]: s for s in body["sources"]}


def test_retry_reloads_and_reports_what_it_observed(gateway, late_server) -> None:
    client = gateway.client
    first = _states(client.get("/api/tool-sources").json())
    assert first["local:late"]["state"] == "unreachable"
    assert first["local:late"]["error"]

    late_server()
    # A plain read does not reload: the cached load still says unreachable.
    assert _states(client.get("/api/tool-sources").json())["local:late"]["state"] == "unreachable"

    resp = client.post("/api/tool-sources/retry")
    assert resp.status_code == 200, resp.text
    after = _states(resp.json())
    assert after["local:late"]["state"] == "live"
    assert after["local:late"]["tool_count"] == 2
    # Still down: still unreachable, with the reason, and counted as failing.
    assert after["local:still-dead"]["state"] == "unreachable"
    assert after["local:still-dead"]["error"]
    assert resp.json()["failing"] == 1
