"""T10: the vault key lives in a 0600 file outside the project, never in
config.yaml; moving an old key rotates it (#59)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
import yaml
from cryptography.fernet import Fernet, InvalidToken

from app.gateway.mcp_secrets import VaultKeyError, make_vault_key
from omniharness.config.mcp_builder_config import McpBuilderConfig

REPO = Path(__file__).resolve().parents[3]


def _keyfile(path: Path, mode: int = 0o600) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(Fernet.generate_key())
    os.chmod(path, mode)
    return path


def test_a_key_in_config_yaml_is_refused(tmp_path) -> None:
    with pytest.raises(VaultKeyError, match="vault-key-migrate"):
        make_vault_key(McpBuilderConfig(enabled=True, vault_key=Fernet.generate_key().decode(), vault_key_file=str(_keyfile(tmp_path / "k"))))


def test_a_key_file_others_can_read_is_refused(tmp_path) -> None:
    with pytest.raises(VaultKeyError, match="644"):
        make_vault_key(McpBuilderConfig(enabled=True, vault_key_file=str(_keyfile(tmp_path / "k", 0o644))))


def test_a_key_file_inside_the_project_is_refused() -> None:
    path = REPO / "backend" / ".pytest-vault-key-test"
    try:
        with pytest.raises(VaultKeyError, match="outside the project"):
            make_vault_key(McpBuilderConfig(enabled=True, vault_key_file=str(_keyfile(path))))
    finally:
        path.unlink(missing_ok=True)


def test_a_missing_key_file_is_refused(tmp_path) -> None:
    with pytest.raises(VaultKeyError, match="make vault-key"):
        make_vault_key(McpBuilderConfig(enabled=True, vault_key_file=str(tmp_path / "nope")))


def test_a_good_key_file_is_used(tmp_path) -> None:
    path = _keyfile(tmp_path / "secrets" / "mcp_vault.key")
    assert make_vault_key(McpBuilderConfig(enabled=True, vault_key_file=str(path))) == path.read_bytes().strip()


def test_the_gateway_refuses_to_start_with_host_bash_on(builder_gateway_factory) -> None:
    with pytest.raises(RuntimeError, match="allow_host_bash"):
        builder_gateway_factory(sandbox={"allow_host_bash": True})


def test_the_gateway_refuses_to_start_with_a_key_in_config(builder_gateway_factory) -> None:
    with pytest.raises(RuntimeError, match="vault_key is set in config.yaml"):
        builder_gateway_factory(mcp_builder_extra={"vault_key": Fernet.generate_key().decode()})


def test_migrate_rotates_every_row_and_removes_the_old_key(tmp_path) -> None:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.gateway.mcp_vault_migrate import migrate
    from omniharness.persistence.base import Base
    from omniharness.persistence.mcp_secrets.model import McpSecretRow

    old = Fernet.generate_key()
    config = tmp_path / "config.yaml"
    config.write_text("mcp_builder:\n  enabled: true\n  # the key below moves out\n  vault_key: " + old.decode() + "\nother: 1\n")
    new_path = tmp_path / "secrets" / "mcp_vault.key"

    async def go():
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as s:
            for i in range(5):
                s.add(McpSecretRow(id=f"r{i}", server_id="s", owner_id="o", key_name=f"K{i}", ciphertext=Fernet(old).encrypt(f"value-{i}".encode()), key_hint=None))
            await s.commit()
        said = await migrate(config_path=config, dev_key_path=tmp_path / "dev_vault.key", session_factory=sf, engine=engine, path=new_path)
        async with sf() as s:
            rows = list((await s.execute(select(McpSecretRow))).scalars())
        await engine.dispose()
        return said, rows

    said, rows = asyncio.run(go())
    new = new_path.read_bytes().strip()
    assert sorted(Fernet(new).decrypt(r.ciphertext).decode() for r in rows) == [f"value-{i}" for i in range(5)]
    for r in rows:
        with pytest.raises(InvalidToken):
            Fernet(old).decrypt(r.ciphertext)
    assert (new_path.stat().st_mode & 0o777) == 0o600 and (new_path.parent.stat().st_mode & 0o777) == 0o700
    cfg = yaml.safe_load(config.read_text())
    assert "vault_key" not in cfg["mcp_builder"] and cfg["other"] == 1
    assert any("VACUUM done" in line for line in said), said
