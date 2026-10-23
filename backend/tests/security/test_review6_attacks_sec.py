"""Review 6 probes (copied from the reviewer's worktree, adapted where noted).

Agent command execution happens only in the container sandbox: MCP Build's
in-gateway test phase (agent-written server.py over stdio as a child of the
gateway) is refused; library launchers are in the spawner sweep; the docs no
longer tell anyone to publish on every interface.
"""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location("_review6_studio", BACKEND / "tests" / "mcp_studio" / "conftest.py")
_studio_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_studio_mod)
studio = _studio_mod.studio

_SOURCE = """
from pathlib import Path
from mcp.server.fastmcp import FastMCP

Path({out!r}).write_text("ran")
mcp = FastMCP("demo")

@mcp.tool()
def ping() -> str:
    return "pong"

if __name__ == "__main__":
    mcp.run()
"""


def test_agent_mcp_source_is_never_run_by_the_gateway() -> None:
    """[adapted] The reviewer asserted "docker" in the method; the fix is
    stronger: the method starts nothing at all and has no stdio launcher."""
    from app.gateway.mcp_server_manager import MCPServerManager

    src = inspect.getsource(MCPServerManager._run_server_sandbox_test)
    for launcher in ("stdio_client", "StdioServerParameters", "sys.executable(", "create_subprocess"):
        assert launcher not in src.replace("``sys.executable``", ""), launcher


def test_the_test_endpoint_refuses_with_the_reason_and_runs_nothing(studio, monkeypatch) -> None:
    import app.gateway.mcp_server_manager as mgr
    from omniharness.skills.code_scanner import ScanResult

    async def _allow(*a, **k):
        return ScanResult("allow", "looks fine")

    monkeypatch.setattr(mgr, "scan_python_code", _allow)  # both scan gates pass
    out = studio.tmp / "ran.txt"
    server_id = studio.make_server(deployed=False)
    studio.run(studio.client.app.state.mcp_server_repo.update_source_code, server_id, _SOURCE.format(out=str(out)), user_id=studio.owner_id)
    resp = studio.client.post(f"/api/mcp-studio/servers/{server_id}/test")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["phase"] == "failed"
    assert any("runs only in a container" in e for e in body["errors"]), body
    assert not out.exists(), "agent-written server code ran beside the gateway"


def test_the_mcp_build_tool_says_it_does_not_run_the_server() -> None:
    from omniharness.tools.builtins.mcp_build_tool import mcp_build_tool

    assert "isolated subprocess" not in mcp_build_tool.description
    assert "does NOT run the server" in mcp_build_tool.description


def test_the_internal_token_cannot_write_a_stdio_mcp_command(studio) -> None:
    """A stdio entry is a command the gateway starts: owner (a person) only."""
    from app.gateway.internal_auth import create_internal_auth_headers

    body = {"mcp_servers": {"x": {"enabled": True, "type": "stdio", "command": "sh", "args": ["-c", "id"]}}}
    resp = studio.client.put("/api/mcp/config", json=body, headers=create_internal_auth_headers())
    assert resp.status_code == 403, resp.text


@pytest.mark.parametrize("key", ["ACP_agents", "Acp", "acp_agents"])
def test_validator_casing(key):
    """[adapted] On a config that is otherwise valid (the reviewer's bare dict
    failed for missing fields, whatever the key), and the refusal names the key."""
    import yaml

    from omniharness.config.app_config import AppConfig

    data = yaml.safe_load((BACKEND.parent / "config.example.yaml").read_text())
    AppConfig.model_validate(data)  # positive control
    with pytest.raises(Exception) as exc:
        AppConfig.model_validate({**data, key: {}})
    assert f"'{key}'" in str(exc.value) and "Delete" in str(exc.value)


def test_setup_doc_does_not_tell_user_to_publish_on_all_interfaces():
    text = (BACKEND.parent / "docs/SETUP.md").read_text()
    assert 'ports: ["YOUR_PORT:2026"]' not in text
    assert "silently ignored" not in text
