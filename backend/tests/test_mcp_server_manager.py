"""Tests for app.gateway.mcp_server_manager.MCPServerManager.

Covers:
- Ownership check at the top of every mutating method
- Cross-user access → PermissionError
- Unapproved server cannot register
- Approved server can register
- test_server with blocked source code → failed phase
- test_server with missing secrets → failed phase
- stop() requires ownership
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
