"""Tests for app.gateway.mcp_server_manager.MCPServerManager.

Covers:
- Ownership check at the top of every mutating method
- Cross-user access → PermissionError
- Unapproved server cannot register
- Approved server can register
- test_server with blocked source code → failed phase
- test_server with missing secrets → informational, not a blocker (A1 change)
- stop() requires ownership
- Secret values are scrubbed from test_results output (never stored or surfaced)
- approve() is gated on phase=="verified"
- Phase taxonomy: testing vs verified
- egress_hosts forwarded to LLM scan (A2 change)
- _is_auth_error: 401/403 treated as ok=True in test-calls
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from omniharness.persistence.base import Base
from omniharness.skills.code_scanner import ScanResult

# ---------------------------------------------------------------------------
# Setup helper (called inside each async test — no async fixture needed)
# ---------------------------------------------------------------------------


async def _make_manager():
    from app.gateway.mcp_secrets import McpSecretsVault
    from app.gateway.mcp_server_manager import MCPServerManager
    from omniharness.persistence.mcp_server.sql import McpServerRepository

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    repo = McpServerRepository(sf)
    vault = McpSecretsVault(Fernet.generate_key(), sf)
    manager = MCPServerManager(repo, vault)
    return manager, repo, vault, engine


# ---------------------------------------------------------------------------
# Ownership check — every mutating method calls _load_and_verify first
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_status_raises_for_wrong_owner() -> None:
    manager, repo, _, engine = await _make_manager()
    row = await repo.create(name="srv", owner_id="user_a")
    with pytest.raises(PermissionError):
        await manager.get_status(server_id=row["id"], user_id="user_b")
    await engine.dispose()


@pytest.mark.anyio
async def test_test_server_raises_for_wrong_owner() -> None:
    manager, repo, _, engine = await _make_manager()
    row = await repo.create(name="srv", owner_id="user_a")
    with pytest.raises(PermissionError):
        await manager.test_server(server_id=row["id"], user_id="user_b")
    await engine.dispose()


@pytest.mark.anyio
async def test_register_raises_for_wrong_owner() -> None:
    manager, repo, _, engine = await _make_manager()
    row = await repo.create(name="srv", owner_id="user_a")
    await repo.set_approved(row["id"], True, user_id="user_a")
    with pytest.raises(PermissionError):
        await manager.register(server_id=row["id"], user_id="user_b")
    await engine.dispose()


@pytest.mark.anyio
async def test_stop_raises_for_wrong_owner() -> None:
    manager, repo, _, engine = await _make_manager()
    row = await repo.create(name="srv", owner_id="user_a")
    with pytest.raises(PermissionError):
        await manager.stop(server_id=row["id"], user_id="user_b")
    await engine.dispose()


# ---------------------------------------------------------------------------
# Unapproved server cannot register
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_unapproved_server_cannot_register() -> None:
    manager, repo, _, engine = await _make_manager()
    row = await repo.create(name="srv", owner_id="user_a")
    with pytest.raises(PermissionError, match="not been approved"):
        await manager.register(server_id=row["id"], user_id="user_a")
    await engine.dispose()


@pytest.mark.anyio
async def test_approved_server_can_register() -> None:
    manager, repo, _, engine = await _make_manager()
    row = await repo.create(name="srv", owner_id="user_a")
    await repo.set_approved(row["id"], True, user_id="user_a")
    record = await manager.register(server_id=row["id"], user_id="user_a")
    assert record.phase == "ready"
    await engine.dispose()


# ---------------------------------------------------------------------------
# test_server — scanner blocks bad code (static blocker unchanged)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_server_scanner_blocks_subprocess() -> None:
    manager, repo, _, engine = await _make_manager()
    row = await repo.create(name="srv", owner_id="user_a", source_code="import subprocess\nsubprocess.run(['ls'])")
    record = await manager.test_server(server_id=row["id"], user_id="user_a")
    assert record.phase == "failed"
    assert record.error is not None
    assert "subprocess" in record.error.lower()
    await engine.dispose()


# ---------------------------------------------------------------------------
# test_server — missing secrets are informational, not a blocker (A1)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_server_missing_secrets_are_informational_not_blocker() -> None:
    """Missing required secrets no longer fail the test — they are recorded in
    required_key_names for display but the server proceeds to the sandbox stage."""
    manager, repo, _, engine = await _make_manager()
    row = await repo.create(name="srv", owner_id="user_a", source_code="import os\nkey = os.getenv('API_KEY')")
    allow = AsyncMock(return_value=ScanResult("allow", "ok"))
    with patch("app.gateway.mcp_server_manager.scan_python_code", allow):
        with patch.object(manager, "_run_server_sandbox_test", return_value=([], [])):
            record = await manager.test_server(server_id=row["id"], user_id="user_a")
    # No longer "failed" — missing secrets are informational
    assert record.phase == "testing"  # sandbox ran but no tools found
    assert record.error is None
    assert "API_KEY" in record.required_key_names
    await engine.dispose()


@pytest.mark.anyio
async def test_server_verified_with_no_secrets_when_tools_discovered() -> None:
    """A server with no required secrets that discovers tools reaches 'verified'."""
    manager, repo, _, engine = await _make_manager()
    row = await repo.create(name="srv", owner_id="user_a", source_code="from mcp.server.fastmcp import FastMCP\nmcp=FastMCP('t')\n@mcp.tool()\ndef ping()->str:\n    return 'pong'\nif __name__=='__main__':mcp.run()")
    allow = AsyncMock(return_value=ScanResult("allow", "ok"))
    fake_tools = [{"name": "ping", "description": "returns pong"}]
    with patch("app.gateway.mcp_server_manager.scan_python_code", allow):
        with patch.object(manager, "_run_server_sandbox_test", return_value=(fake_tools, [])):
            record = await manager.test_server(server_id=row["id"], user_id="user_a")
    assert record.phase == "verified"
    assert record.tools_discovered == fake_tools
    assert record.error is None
    await engine.dispose()


@pytest.mark.anyio
async def test_server_verified_with_missing_secrets_when_tools_discovered() -> None:
    """Even when a secret is missing, if tools are discovered the server is 'verified'.
    The user will see required_key_names to know they should add keys for live calls."""
    manager, repo, _, engine = await _make_manager()
    src = (
        "import os\nfrom mcp.server.fastmcp import FastMCP\n"
        "API_KEY=os.getenv('API_KEY')\nmcp=FastMCP('t')\n"
        "@mcp.tool()\ndef fetch()->str:\n"
        '    if not API_KEY: return \'{"error":"missing key"}\'\n'
        "    return 'ok'\n"
        "if __name__=='__main__':mcp.run()"
    )
    row = await repo.create(
        name="srv",
        owner_id="user_a",
        source_code=src,
    )
    # No secret stored — key missing
    allow = AsyncMock(return_value=ScanResult("allow", "ok"))
    fake_tools = [{"name": "fetch", "description": "fetches data"}]
    fake_results = [{"tool": "fetch", "ok": True, "output": '{"error":"missing key"}'}]
    with patch("app.gateway.mcp_server_manager.scan_python_code", allow):
        with patch.object(manager, "_run_server_sandbox_test", return_value=(fake_tools, fake_results)):
            record = await manager.test_server(server_id=row["id"], user_id="user_a")
    assert record.phase == "verified"
    assert "API_KEY" in record.required_key_names
    assert record.error is None
    await engine.dispose()


@pytest.mark.anyio
async def test_server_passes_when_required_secrets_present() -> None:
    """When secrets are present the server still reaches testing/verified phase."""
    manager, repo, vault, engine = await _make_manager()
    row = await repo.create(name="srv", owner_id="user_a", source_code="import os\nkey = os.getenv('API_KEY')")
    await vault.store(server_id=row["id"], owner_id="user_a", key_name="API_KEY", plaintext_value="test-value")
    allow = AsyncMock(return_value=ScanResult("allow", "ok"))
    with patch("app.gateway.mcp_server_manager.scan_python_code", allow):
        with patch.object(manager, "_run_server_sandbox_test", return_value=([], [])):
            record = await manager.test_server(server_id=row["id"], user_id="user_a")
    assert record.phase == "testing"
    assert record.error is None
    assert "API_KEY" in record.required_key_names
    await engine.dispose()


# ---------------------------------------------------------------------------
# required_key_names contains names only (not values)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_build_record_contains_key_names_not_values() -> None:
    """Scanner returns 'allow' (mocked) so key names appear in the record."""
    manager, repo, vault, engine = await _make_manager()
    row = await repo.create(name="srv", owner_id="user_a", source_code="import os\nkey = os.getenv('SECRET')")
    await vault.store(server_id=row["id"], owner_id="user_a", key_name="SECRET", plaintext_value="hunter2")
    allow = AsyncMock(return_value=ScanResult("allow", "ok"))
    with patch("app.gateway.mcp_server_manager.scan_python_code", allow):
        with patch.object(manager, "_run_server_sandbox_test", return_value=([], [])):
            record = await manager.test_server(server_id=row["id"], user_id="user_a")
    assert "hunter2" not in str(record)
    assert "SECRET" in record.required_key_names
    await engine.dispose()


# ---------------------------------------------------------------------------
# Secret value must never appear in test_results output (scrub)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_secret_value_scrubbed_from_test_results_output() -> None:
    """Secret values must be stripped from test_results output before storage.

    Simulates a tool that echoes its config/env: _run_server_sandbox_test
    is mocked to return output containing the real vault secret value.
    The manager must scrub it before the record is stored or returned.
    """

    manager, repo, vault, engine = await _make_manager()
    row = await repo.create(
        name="srv",
        owner_id="user_a",
        source_code="import os\nfrom mcp.server.fastmcp import FastMCP\nmcp=FastMCP('t')\n@mcp.tool()\ndef leak()->str:\n    return os.getenv('SECRET','')\nif __name__=='__main__':mcp.run()",
    )
    await vault.store(server_id=row["id"], owner_id="user_a", key_name="SECRET", plaintext_value="super-secret-value-xyz")

    allow = AsyncMock(return_value=ScanResult("allow", "ok"))

    # Simulate a tool output that contains the real secret value — this is what
    # would happen if real secrets were ever injected into the subprocess.
    fake_tools = [{"name": "leak", "description": "leaks env vars"}]
    fake_results = [{"tool": "leak", "ok": True, "output": "super-secret-value-xyz"}]

    with patch("app.gateway.mcp_server_manager.scan_python_code", allow):
        with patch.object(manager, "_run_server_sandbox_test", return_value=(fake_tools, fake_results)):
            record = await manager.test_server(server_id=row["id"], user_id="user_a")

    # The real secret must not appear anywhere in the stored record
    record_str = str(record)
    assert "super-secret-value-xyz" not in record_str, "Real secret value must be scrubbed from test_results before storage"
    # The scrubbed output must contain the REDACTED placeholder
    assert any("[REDACTED]" in str(tr) for tr in record.test_results), "Scrubbed output should contain [REDACTED] marker"
    await engine.dispose()


# ---------------------------------------------------------------------------
# Phase taxonomy: testing vs verified, and approve gate
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_phase_is_verified_when_tools_discovered() -> None:
    """phase=='verified' when sandbox connected and tools are discovered."""

    manager, repo, vault, engine = await _make_manager()
    row = await repo.create(name="srv", owner_id="user_a", source_code="import os\nk=os.getenv('K')")
    await vault.store(server_id=row["id"], owner_id="user_a", key_name="K", plaintext_value="v")
    allow = AsyncMock(return_value=ScanResult("allow", "ok"))

    fake_tools = [{"name": "my_tool", "description": "does something"}]
    fake_results: list[dict] = []

    with patch("app.gateway.mcp_server_manager.scan_python_code", allow):
        with patch.object(manager, "_run_server_sandbox_test", return_value=(fake_tools, fake_results)):
            record = await manager.test_server(server_id=row["id"], user_id="user_a")

    assert record.phase == "verified"
    assert record.tools_discovered == fake_tools
    await engine.dispose()


@pytest.mark.anyio
async def test_phase_is_testing_when_no_tools_discovered() -> None:
    """phase=='testing' (not approvable) when sandbox ran but found no tools."""
    manager, repo, vault, engine = await _make_manager()
    row = await repo.create(name="srv", owner_id="user_a", source_code="import os\nk=os.getenv('K')")
    await vault.store(server_id=row["id"], owner_id="user_a", key_name="K", plaintext_value="v")
    allow = AsyncMock(return_value=ScanResult("allow", "ok"))

    # Sandbox ran but found zero tools
    with patch("app.gateway.mcp_server_manager.scan_python_code", allow):
        with patch.object(manager, "_run_server_sandbox_test", return_value=([], [])):
            record = await manager.test_server(server_id=row["id"], user_id="user_a")

    assert record.phase == "testing"
    await engine.dispose()


@pytest.mark.anyio
async def test_approve_blocked_when_phase_is_not_verified() -> None:
    """approve() must raise PermissionError when phase is not 'verified'."""
    manager, repo, _, engine = await _make_manager()
    row = await repo.create(name="srv", owner_id="user_a")
    # No test run → no in-memory record → phase is "unknown"
    with pytest.raises(PermissionError, match="verified"):
        await manager.approve(server_id=row["id"], user_id="user_a")
    await engine.dispose()


@pytest.mark.anyio
async def test_approve_blocked_when_phase_is_testing() -> None:
    """approve() must raise when phase is 'testing' (sandbox ran but no tools found)."""
    from app.gateway.mcp_server_manager import MCPBuildRecord

    manager, repo, _, engine = await _make_manager()
    row = await repo.create(name="srv", owner_id="user_a")
    # Inject a "testing" record directly
    manager._records[row["id"]] = MCPBuildRecord(server_id=row["id"], phase="testing", owner_id="user_a")
    with pytest.raises(PermissionError, match="verified"):
        await manager.approve(server_id=row["id"], user_id="user_a")
    await engine.dispose()


@pytest.mark.anyio
async def test_approve_succeeds_when_phase_is_verified() -> None:
    """approve() succeeds and transitions to idle when phase is 'verified'."""
    from app.gateway.mcp_server_manager import MCPBuildRecord

    manager, repo, _, engine = await _make_manager()
    row = await repo.create(name="srv", owner_id="user_a")
    manager._records[row["id"]] = MCPBuildRecord(server_id=row["id"], phase="verified", owner_id="user_a")
    result = await manager.approve(server_id=row["id"], user_id="user_a")
    assert result.phase == "idle"

    # Verify the DB flag was set
    server = await repo.get(row["id"], user_id="user_a")
    assert server is not None
    assert server["approved"] is True
    await engine.dispose()


# ---------------------------------------------------------------------------
# egress_hosts forwarded to LLM scan (A2)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_egress_hosts_forwarded_to_llm_scan() -> None:
    """egress_hosts declared on the server are forwarded to scan_python_code."""
    manager, repo, _, engine = await _make_manager()
    row = await repo.create(
        name="srv",
        owner_id="user_a",
        source_code="import httpx\nfrom mcp.server.fastmcp import FastMCP\nmcp=FastMCP('t')\n@mcp.tool()\ndef fetch()->str:\n    return httpx.get('https://api.hunter.io').text\nif __name__=='__main__':mcp.run()",
        egress_hosts=["api.hunter.io"],
    )

    captured: dict = {}

    async def capture_scan(source, *, location="<generated>", egress_hosts=None, app_config=None):
        captured["egress_hosts"] = egress_hosts
        return ScanResult("allow", "ok")

    with patch("app.gateway.mcp_server_manager.scan_python_code", capture_scan):
        with patch.object(manager, "_run_server_sandbox_test", return_value=([], [])):
            await manager.test_server(server_id=row["id"], user_id="user_a")

    assert captured.get("egress_hosts") == ["api.hunter.io"]
    await engine.dispose()


# ---------------------------------------------------------------------------
# _is_auth_error — 401/403 treated as ok=True in test-calls (A1)
# ---------------------------------------------------------------------------


def test_is_auth_error_detects_401() -> None:
    from app.gateway.mcp_server_manager import MCPServerManager

    assert MCPServerManager._is_auth_error("HTTP 401 Unauthorized")


def test_is_auth_error_detects_403() -> None:
    from app.gateway.mcp_server_manager import MCPServerManager

    assert MCPServerManager._is_auth_error("HTTP 403 Forbidden")


def test_is_auth_error_detects_invalid_api_key() -> None:
    from app.gateway.mcp_server_manager import MCPServerManager

    assert MCPServerManager._is_auth_error("Invalid API key provided")


def test_is_auth_error_detects_unauthorized_text() -> None:
    from app.gateway.mcp_server_manager import MCPServerManager

    assert MCPServerManager._is_auth_error("Request failed: unauthorized")


def test_is_auth_error_does_not_match_normal_error() -> None:
    from app.gateway.mcp_server_manager import MCPServerManager

    assert not MCPServerManager._is_auth_error("Connection refused to host")


def test_is_auth_error_does_not_match_timeout() -> None:
    from app.gateway.mcp_server_manager import MCPServerManager

    assert not MCPServerManager._is_auth_error("Operation timed out after 10 seconds")


def test_is_auth_error_does_not_match_generic_exception() -> None:
    from app.gateway.mcp_server_manager import MCPServerManager

    assert not MCPServerManager._is_auth_error("AttributeError: 'NoneType' object has no attribute 'get'")
