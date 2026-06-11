"""Tests for app.gateway.mcp_secrets.McpSecretsVault.

All tests use an in-memory SQLite database — no gateway process, no Fernet key file.
Secrets are never returned to the caller; list_key_names() returns names only.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from omniharness.persistence.base import Base

# ---------------------------------------------------------------------------
# Setup helper (called inside each async test — no async fixture needed)
# ---------------------------------------------------------------------------


async def _make_vault():
    from app.gateway.mcp_secrets import McpSecretsVault

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    key = Fernet.generate_key()
    return McpSecretsVault(key, sf), engine


# ---------------------------------------------------------------------------
# store / list_key_names
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_store_and_list_key_names() -> None:
    vault, engine = await _make_vault()
    await vault.store(server_id="srv1", owner_id="user_a", key_name="API_KEY", plaintext_value="super-secret")
    names = await vault.list_key_names(server_id="srv1", owner_id="user_a")
    assert names == ["API_KEY"]
    await engine.dispose()


@pytest.mark.anyio
async def test_list_key_names_never_returns_plaintext() -> None:
    vault, engine = await _make_vault()
    await vault.store(server_id="srv1", owner_id="user_a", key_name="SECRET", plaintext_value="hunter2")
    names = await vault.list_key_names(server_id="srv1", owner_id="user_a")
    assert "hunter2" not in str(names)
    assert names == ["SECRET"]
    await engine.dispose()


@pytest.mark.anyio
async def test_store_upserts_on_duplicate_key() -> None:
    vault, engine = await _make_vault()
    await vault.store(server_id="srv1", owner_id="user_a", key_name="TOKEN", plaintext_value="v1")
    await vault.store(server_id="srv1", owner_id="user_a", key_name="TOKEN", plaintext_value="v2")
    names = await vault.list_key_names(server_id="srv1", owner_id="user_a")
    assert names.count("TOKEN") == 1  # upsert, not insert-duplicate
    await engine.dispose()


# ---------------------------------------------------------------------------
# Cross-user isolation
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cross_user_cannot_list_other_users_keys() -> None:
    vault, engine = await _make_vault()
    await vault.store(server_id="srv1", owner_id="user_a", key_name="API_KEY", plaintext_value="secret-a")
    names_b = await vault.list_key_names(server_id="srv1", owner_id="user_b")
    assert names_b == []
    await engine.dispose()


@pytest.mark.anyio
async def test_cross_user_cannot_decrypt_other_users_secrets() -> None:
    vault, engine = await _make_vault()
    await vault.store(server_id="srv1", owner_id="user_a", key_name="KEY", plaintext_value="value_a")
    secrets_b = await vault._decrypt_for_sandbox(server_id="srv1", owner_id="user_b")
    assert secrets_b == {}
    await engine.dispose()


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_delete_removes_key() -> None:
    vault, engine = await _make_vault()
    await vault.store(server_id="srv1", owner_id="user_a", key_name="TO_DELETE", plaintext_value="x")
    deleted = await vault.delete(server_id="srv1", owner_id="user_a", key_name="TO_DELETE")
    assert deleted is True
    names = await vault.list_key_names(server_id="srv1", owner_id="user_a")
    assert "TO_DELETE" not in names
    await engine.dispose()


@pytest.mark.anyio
async def test_delete_nonexistent_returns_false() -> None:
    vault, engine = await _make_vault()
    result = await vault.delete(server_id="no-such", owner_id="user_a", key_name="NOPE")
    assert result is False
    await engine.dispose()


@pytest.mark.anyio
async def test_delete_all_for_server() -> None:
    vault, engine = await _make_vault()
    await vault.store(server_id="srv1", owner_id="user_a", key_name="A", plaintext_value="1")
    await vault.store(server_id="srv1", owner_id="user_a", key_name="B", plaintext_value="2")
    count = await vault.delete_all_for_server(server_id="srv1", owner_id="user_a")
    assert count == 2
    assert await vault.list_key_names(server_id="srv1", owner_id="user_a") == []
    await engine.dispose()


# ---------------------------------------------------------------------------
# scan_for_required_keys (static — no DB, no Fernet)
# ---------------------------------------------------------------------------


def test_scan_for_required_keys() -> None:
    from app.gateway.mcp_secrets import McpSecretsVault

    src = "api_key = os.getenv('STRIPE_KEY')\ntoken = os.getenv(\"GH_TOKEN\")"
    keys = McpSecretsVault.scan_for_required_keys(src)
    assert "STRIPE_KEY" in keys
    assert "GH_TOKEN" in keys


def test_scan_for_required_keys_empty() -> None:
    from app.gateway.mcp_secrets import McpSecretsVault

    assert McpSecretsVault.scan_for_required_keys("x = 1") == []


# ---------------------------------------------------------------------------
# make_vault_key
# ---------------------------------------------------------------------------


def test_make_vault_key_raises_without_key_in_prod_mode() -> None:
    from app.gateway.mcp_secrets import make_vault_key
    from omniharness.config.mcp_builder_config import McpBuilderConfig

    config = McpBuilderConfig(enabled=True, vault_key=None, dev_mode=False)
    with pytest.raises(RuntimeError, match="vault_key is required"):
        make_vault_key(config)


def test_make_vault_key_returns_ephemeral_in_dev_mode() -> None:
    from app.gateway.mcp_secrets import make_vault_key
    from omniharness.config.mcp_builder_config import McpBuilderConfig

    config = McpBuilderConfig(enabled=True, vault_key=None, dev_mode=True)
    key = make_vault_key(config)
    assert isinstance(key, bytes)
    Fernet(key)  # validates key format


def test_make_vault_key_uses_configured_key() -> None:
    from app.gateway.mcp_secrets import make_vault_key
    from omniharness.config.mcp_builder_config import McpBuilderConfig

    raw_key = Fernet.generate_key()
    config = McpBuilderConfig(enabled=True, vault_key=raw_key.decode(), dev_mode=False)
    key = make_vault_key(config)
    assert key == raw_key
