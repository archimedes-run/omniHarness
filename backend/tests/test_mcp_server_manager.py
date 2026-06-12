"""Tests for app.gateway.mcp_server_manager.MCPServerManager.

Covers:
- Ownership check at the top of every mutating method
- Cross-user access → PermissionError
- Unapproved server cannot register
- Approved server can register
- test_server with blocked source code → failed phase
- test_server with missing secrets → failed phase
- stop() requires ownership
- Secret values are scrubbed from test_results output (never stored or surfaced)
- approve() is gated on phase=="verified"
- Phase taxonomy: testing vs verified
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
# test_server — scanner blocks bad code
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
# test_server — missing required secrets cause failure
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_server_fails_when_required_secrets_missing() -> None:
    """Scanner returns 'allow' (mocked) so we reach the secrets-check gate."""
    manager, repo, _, engine = await _make_manager()
    row = await repo.create(name="srv", owner_id="user_a", source_code="import os\nkey = os.getenv('API_KEY')")
    allow = AsyncMock(return_value=ScanResult("allow", "ok"))
    with patch("app.gateway.mcp_server_manager.scan_python_code", allow):
        record = await manager.test_server(server_id=row["id"], user_id="user_a")
    assert record.phase == "failed"
    assert "API_KEY" in (record.error or "")
    await engine.dispose()


@pytest.mark.anyio
async def test_server_passes_when_required_secrets_present() -> None:
    """Scanner returns 'allow' (mocked) so we reach the testing phase."""
    manager, repo, vault, engine = await _make_manager()
    row = await repo.create(name="srv", owner_id="user_a", source_code="import os\nkey = os.getenv('API_KEY')")
    await vault.store(server_id=row["id"], owner_id="user_a", key_name="API_KEY", plaintext_value="test-value")
    allow = AsyncMock(return_value=ScanResult("allow", "ok"))
    with patch("app.gateway.mcp_server_manager.scan_python_code", allow):
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
