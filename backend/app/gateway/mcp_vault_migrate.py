"""The MCP vault key file: create it, or move an old key into it and rotate (#59).

    uv run python -m app.gateway.mcp_vault_migrate create   # make vault-key
    uv run python -m app.gateway.mcp_vault_migrate migrate  # make vault-key-migrate

The key lives in a 0600 file in a 0700 directory outside the project
(default ``~/.omni-harness-secrets/mcp_vault.key``), never in config.yaml.

``migrate`` takes the old key (``mcp_builder.vault_key`` in config.yaml, or the
old ``.omni-harness/dev_vault.key``), writes a NEW key, re-encrypts every stored
secret with ``MultiFernet([new, old]).rotate()``, then removes the old key from
config.yaml, deletes ``dev_vault.key`` and runs VACUUM. Rotation is the
control, not deletion: on APFS (copy-on-write, snapshots) a deleted file's
blocks are not erased, so the old key must decrypt nothing that is still
stored. A backup or snapshot of the OLD database is still readable with the
old key; this says so when it runs.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

from cryptography.fernet import Fernet, MultiFernet
from sqlalchemy import select, text

DEFAULT_PATH = Path.home() / ".omni-harness-secrets" / "mcp_vault.key"


def key_path() -> Path:
    return Path(os.environ.get("OMNI_HARNESS_MCP_VAULT_KEY_FILE") or DEFAULT_PATH)


def write_key_file(path: Path, key: bytes) -> None:
    """Write *key* to *path* (0600, directory 0700); never overwrites."""
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(key + b"\n")


def create(path: Path | None = None) -> str:
    path = path or key_path()
    if path.exists():
        return f"{path} already exists; left as it is."
    write_key_file(path, Fernet.generate_key())
    return f"Created {path} (0600)."


async def rotate_rows(session_factory, old_key: bytes, new_key: bytes) -> int:
    """Re-encrypt every stored MCP secret from *old_key* to *new_key*."""
    from omniharness.persistence.mcp_secrets.model import McpSecretRow

    rotator = MultiFernet([Fernet(new_key), Fernet(old_key)])
    n = 0
    async with session_factory() as session:
        for row in (await session.execute(select(McpSecretRow))).scalars():
            row.ciphertext = rotator.rotate(row.ciphertext)
            n += 1
        await session.commit()
    return n


async def vacuum(engine) -> None:
    async with engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.execute(text("VACUUM" if engine.dialect.name == "sqlite" else "VACUUM FULL mcp_secrets"))


def strip_config_key(config_text: str) -> str:
    """config.yaml without its ``mcp_builder.vault_key`` line (comments kept)."""
    return re.sub(r"(?m)^(\s+)vault_key:.*\n", "", config_text)


async def migrate(*, config_path: Path, dev_key_path: Path, session_factory, engine, path: Path | None = None) -> list[str]:
    path = path or key_path()
    said: list[str] = []
    import yaml

    raw = config_path.read_text() if config_path.exists() else ""
    old = ((yaml.safe_load(raw) or {}).get("mcp_builder") or {}).get("vault_key") if raw else None
    old_key = old.encode() if old else (dev_key_path.read_bytes().strip() if dev_key_path.exists() else None)
    if old_key is None:
        return ["No old key found (config.yaml or dev_vault.key): nothing to migrate."]
    if path.exists():
        return [f"{path} already exists: refusing to overwrite it. Move it away to migrate again."]
    new_key = Fernet.generate_key()
    n = await rotate_rows(session_factory, old_key, new_key)
    write_key_file(path, new_key)
    said.append(f"Re-encrypted {n} stored secret(s) with a new key in {path} (0600).")
    if old:
        config_path.write_text(strip_config_key(raw))
        said.append(f"Removed mcp_builder.vault_key from {config_path}.")
    if dev_key_path.exists():
        dev_key_path.unlink()
        said.append(f"Deleted {dev_key_path} (on APFS the blocks are not erased; the rotation is what protects you).")
    await vacuum(engine)
    said.append("VACUUM done. A backup or snapshot of the OLD database is still readable with the old key.")
    return said


async def _main(cmd: str) -> int:
    if cmd == "create":
        print(create())
        return 0
    if cmd != "migrate":
        print("usage: python -m app.gateway.mcp_vault_migrate create|migrate", file=sys.stderr)
        return 2
    from omniharness.config.app_config import AppConfig, get_app_config
    from omniharness.persistence.engine import close_engine, get_engine, get_session_factory, init_engine_from_config

    config = get_app_config()
    await init_engine_from_config(config)
    try:
        for line in await migrate(
            config_path=Path(AppConfig.resolve_config_path()),
            dev_key_path=Path(__file__).resolve().parents[2] / ".omni-harness" / "dev_vault.key",
            session_factory=get_session_factory(),
            engine=get_engine(),
        ):
            print(line)
    finally:
        await close_engine()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(sys.argv[1] if len(sys.argv) > 1 else "")))
