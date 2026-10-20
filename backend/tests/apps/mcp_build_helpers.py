"""Shared pieces of the MCP Build HTTP tests (#59): a built server whose
sandbox tests passed, with docker faked behind the production DockerRunner
port, and the calls the UI makes."""

from __future__ import annotations

import functools
import time
from unittest.mock import AsyncMock, patch

import pytest
from mcp_fakes import FakeDockerRunner

DESCRIPTION = "list my open github issues"

CODE_V1 = """from mcp.server.fastmcp import FastMCP

mcp = FastMCP("issues")


@mcp.tool()
def whoami() -> str:
    \"\"\"Says hello.\"\"\"
    return "v1"
"""
CODE_V2 = CODE_V1.replace('"v1"', '"v2, now reading https://evil.example/collect"')

TOOLS = ([{"name": "whoami", "description": "Says hello."}], [{"tool": "whoami", "ok": True, "output_type": "pass"}])


@pytest.fixture
def built(builder_gateway, monkeypatch):
    """A built server whose sandbox tests passed, with docker faked."""

    async def fake_run_agent(*args, **kwargs):
        return None

    monkeypatch.setattr("app.gateway.routers.mcp_studio.run_agent", fake_run_agent)
    app, client = builder_gateway.app, builder_gateway.client
    manager = app.state.mcp_server_manager
    runner = FakeDockerRunner()
    manager._runner = runner
    allow = AsyncMock(return_value=type("R", (), {"decision": "allow", "reason": "ok"})())
    patches = [
        patch("app.gateway.mcp_server_manager.scan_python_code", allow),
        patch.object(manager, "_run_server_sandbox_test", AsyncMock(return_value=TOOLS)),
    ]
    for p in patches:
        p.start()
    resp = client.post("/api/mcp-studio/builds", json={"description": DESCRIPTION})
    assert resp.status_code == 201, resp.text
    sid = resp.json()["server_id"]
    submit(builder_gateway, sid, CODE_V1)
    yield builder_gateway, sid, runner, manager
    for p in patches:
        p.stop()


def on_loop(gw, fn, **kwargs):
    """Run a manager coroutine on the app's own event loop."""
    return gw.client.portal.call(functools.partial(fn, **kwargs))


def submit(gw, sid: str, code: str):
    """What the agent's mcp_build tool does: store the code and test it."""
    manager = gw.app.state.mcp_server_manager
    return on_loop(gw, manager.submit_source_and_test, server_id=sid, user_id=gw.user_id, source_code=code)


def server(gw, sid: str) -> dict:
    resp = gw.client.get(f"/api/mcp-studio/servers/{sid}")
    assert resp.status_code == 200, resp.text
    return resp.json()


def enable(gw, sid: str, sha: str | None = None, tiers: dict | None = None):
    """What the approval screen does: fetch the packet (the code is shown),
    then approve the hash it showed with the token it got."""
    packet = gw.client.get(f"/api/mcp-studio/servers/{sid}/approval")
    assert packet.status_code == 200, packet.text
    body = {"code_sha256": sha or packet.json()["code_sha256"], "view_token": packet.json()["view_token"], "tool_tiers": tiers or {}}
    return gw.client.post(f"/api/mcp-studio/servers/{sid}/enable", json=body)


def wait_for(gw, sid: str, states: set[str], timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        s = server(gw, sid)
        if s["state"] in states:
            return s
        time.sleep(0.02)
    raise AssertionError(f"never reached {states}: {server(gw, sid)}")
