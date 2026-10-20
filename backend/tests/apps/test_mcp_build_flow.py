"""MCP Suite > Build (Feature 006), through the gateway `create_app()` builds.

Describe a tool in words -> an agent builds it -> it is tested in a sandbox ->
the user approves its first run -> it is turned on. Two promises are tested:

* a secret in the description never reaches the model: the build prompt, the
  stored description, the sandbox test output and everything the API returns
  carry the placeholder ``{{secret:NAME}}``, never the value;
* nothing turns a built server on without the user's approval: deploy and
  connect refuse an unapproved server, and approval needs passing tests.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

SECRET = "dv_9f8e7d6c5b4a1234zz"
DESCRIPTION = f"check my Devpost submissions and their judging status, my token is {SECRET}"

SERVER = """import os
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("devpost")


@mcp.tool()
def whoami() -> str:
    \"\"\"Says which token it would use.\"\"\"
    token = os.environ.get("TOKEN", "none")
    return "using " + token + " backwards " + token[::-1]


if __name__ == "__main__":
    mcp.run()
"""


@pytest.fixture
def prompts(monkeypatch):
    """The build agent's input, captured instead of calling a model."""
    seen: list[str] = []

    async def fake_run_agent(bridge, run_mgr, record, *, graph_input, **kwargs):
        seen.append(json.dumps(graph_input, default=str))

    monkeypatch.setattr("app.gateway.routers.mcp_studio.run_agent", fake_run_agent)
    return seen


def _start(client) -> dict:
    resp = client.post("/api/mcp-studio/builds", json={"description": DESCRIPTION})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _server(client, server_id: str) -> dict:
    servers = client.get("/api/mcp-studio/servers").json()["servers"]
    return next(s for s in servers if s["id"] == server_id)


def test_a_secret_in_the_description_never_reaches_the_model(builder_gateway, prompts) -> None:
    client = builder_gateway.client
    started = _start(client)
    assert started["secret_placeholders"] == ["TOKEN"]

    # The prompt the build agent got: the placeholder and how to read it, not the value.
    assert len(prompts) == 1
    assert SECRET not in prompts[0]
    assert "{{secret:TOKEN}}" in prompts[0]
    assert "os.environ['TOKEN']" in prompts[0]

    # Stored for the server, under that name (names only come back).
    info = client.get(f"/api/mcp-studio/servers/{started['server_id']}/secrets/info").json()
    assert [k["key_name"] for k in info["keys"]] == ["TOKEN"]

    # Nothing the API returns carries the value.
    listing = client.get("/api/mcp-studio/servers").text
    assert SECRET not in listing
    server = _server(client, started["server_id"])
    assert "{{secret:TOKEN}}" in server["description"]
    # The run is in progress and there is no code yet: drafting, observed.
    assert server["state"] == "drafting", server
    assert server["state_label"] == "Drafting"


def test_tests_run_in_the_sandbox_with_placeholders_and_enabling_needs_approval(builder_gateway, prompts) -> None:
    client, app = builder_gateway.client, builder_gateway.app
    manager = app.state.mcp_server_manager
    sid = _start(client)["server_id"]

    # Approval before the tests pass is refused, and so is turning it on directly.
    assert client.get(f"/api/mcp-studio/servers/{sid}/approval").status_code == 409  # no code to show yet
    refused = client.post(f"/api/mcp-studio/servers/{sid}/enable", json={"code_sha256": "0" * 64})
    assert refused.status_code == 409 and "Open the code first" in refused.text, refused.text
    assert client.post(f"/api/mcp-studio/servers/{sid}/deploy").status_code == 403

    # The agent submits its code (what its mcp_build tool does): a real sandbox run.
    allow = AsyncMock(return_value=type("R", (), {"decision": "allow", "reason": "ok"})())
    with patch("app.gateway.mcp_server_manager.scan_python_code", allow):
        record = asyncio.run(manager.submit_source_and_test(server_id=sid, user_id=builder_gateway.user_id, source_code=SERVER))
    assert record.phase == "verified", record
    # The sandbox never had the real key: the tool saw the placeholder. (The
    # reversed copy is what output scrubbing cannot catch, so it shows what
    # the sandbox was actually given.)
    outputs = " ".join(str(t) for t in record.test_results)
    assert SECRET not in outputs
    assert SECRET[::-1] not in outputs
    assert "using {{secret:TOKEN}}" in outputs
    assert "}}NEKOT:terces{{" in outputs

    server = _server(client, sid)
    assert server["state"] == "awaiting_approval", server
    assert server["state_label"] == "Waiting for your approval"
    texts = [s["text"] for s in server["steps"]]
    assert "Scaffolded server, 1 tool: whoami" in texts
    assert "Tests passed in sandbox: 1 of 1" in texts
    assert "Uses secret TOKEN: stored, never shown to the model" in texts
    assert texts[-1] == "First real run needs your approval"
    assert server["approved"] is False
    # Still not on: no route turns it on without the approval.
    assert client.post(f"/api/mcp-studio/servers/{sid}/deploy").status_code == 403
    assert client.post(f"/api/mcp-studio/servers/{sid}/connect").status_code == 403
    assert sid not in builder_gateway.extensions.read_text()

    # The user approves the code they saw (by hash): deployed (docker faked) and connected for agents.
    from mcp_fakes import FakeDockerRunner

    manager._runner = FakeDockerRunner()
    if True:
        packet = client.get(f"/api/mcp-studio/servers/{sid}/approval").json()
        resp = client.post(f"/api/mcp-studio/servers/{sid}/enable", json={"code_sha256": server["code_sha256"], "view_token": packet["view_token"]})
        assert resp.status_code == 200, resp.text
        for _ in range(100):
            if _server(client, sid)["state"] == "enabled":
                break
            asyncio.run(asyncio.sleep(0.05))
    server = _server(client, sid)
    assert server["approved"] is True
    assert server["state"] == "enabled", server
    config = json.loads(builder_gateway.extensions.read_text())
    assert server["name"] in config["mcpServers"]
    # Turned on with the real key; still nothing returned carries it.
    assert SECRET not in client.get("/api/mcp-studio/servers").text
