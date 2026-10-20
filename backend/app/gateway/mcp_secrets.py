"""McpSecretsVault — Fernet-encrypted per-user, per-server secret storage.

Security invariants
-------------------
* Secrets are NEVER returned to callers. Only ``list_key_names()`` is public;
  it returns env-var names, never ciphertext or plaintext.
* ``owner_id`` is ALWAYS the verified requesting user passed by the caller —
  never the ``owner_id`` read back from a DB row, which would create an
  injection attack surface if a different server_id were supplied.
* ``make_vault_key()`` raises ``RuntimeError`` loudly if no key is configured
  in non-dev mode. An ephemeral key (dev only) is a warning, not silent.
* Plaintext values are encrypted in-memory and immediately discarded; they are
  never written to logs, model context, or persistent state.
"""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from cryptography.fernet import Fernet
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omniharness.persistence.mcp_secrets.model import McpSecretRow
from omniharness.skills.code_scanner import extract_env_keys

if TYPE_CHECKING:
    from omniharness.config.mcp_builder_config import McpBuilderConfig

logger = logging.getLogger(__name__)


DEFAULT_KEY_FILE = "/run/secrets/mcp_vault_key"


class VaultKeyError(RuntimeError):
    pass


def vault_key_path(config: McpBuilderConfig) -> Path:
    return Path(config.vault_key_file or os.environ.get("OMNI_HARNESS_MCP_VAULT_KEY_FILE") or DEFAULT_KEY_FILE)


def _forbidden_roots() -> list[Path]:
    roots = [Path(__file__).resolve().parents[3]]  # the repository
    home = os.environ.get("OMNI_HARNESS_HOME")
    if home:
        roots.append(Path(home).resolve())
    return roots


def make_vault_key(config: McpBuilderConfig) -> bytes:
    """The Fernet key, from a 0600 file outside every mount generated code or
    agent sandboxes see (#59). Refuses to start, saying why, when:

    * ``config.yaml`` still has ``mcp_builder.vault_key``;
    * the key file is missing, or readable by anyone but its owner;
    * the key file sits under the repository or OMNI_HARNESS_HOME.

    There is no ephemeral or in-repo fallback any more.
    """
    if config.vault_key:
        raise VaultKeyError("mcp_builder.vault_key is set in config.yaml: the vault key may not live there any more. Run `make vault-key-migrate`, which moves it to a 0600 file and rotates it.")
    path = vault_key_path(config)
    if not path.exists():
        raise VaultKeyError(f"no vault key file at {path}: create one with `make vault-key` (or set mcp_builder.vault_key_file).")
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        raise VaultKeyError(f"the vault key file {path} is mode {mode:o}; it must be readable by its owner only (0600 or 0400).")
    resolved = path.resolve()
    for root in _forbidden_roots():
        if resolved == root or root in resolved.parents:
            raise VaultKeyError(f"the vault key file {path} is under {root}; keep it outside the project and OMNI_HARNESS_HOME.")
    key = path.read_bytes().strip()
    Fernet(key)  # a malformed key fails here, loudly
    return key


class McpSecretsVault:
    """Fernet-backed vault for MCP server environment secrets.

    The vault is the *only* component that holds the Fernet key at runtime.
    No other module should call ``Fernet`` directly for MCP secrets.
    """

    def __init__(self, key_bytes: bytes, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._fernet = Fernet(key_bytes)
        self._sf = session_factory

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def store(self, *, server_id: str, owner_id: str, key_name: str, plaintext_value: str) -> str | None:
        """Encrypt and upsert a single secret.

        ``owner_id`` MUST be the verified requesting user — never derived from
        the server row itself. Plaintext is discarded after encryption.

        Returns the key_hint (last 5 chars) so the caller can include it in the
        response without a second DB read.
        """
        ciphertext: bytes = self._fernet.encrypt(plaintext_value.encode())
        key_hint: str | None = plaintext_value[-5:] if len(plaintext_value) >= 5 else None

        async with self._sf() as session:
            result = await session.execute(
                select(McpSecretRow).where(
                    McpSecretRow.server_id == server_id,
                    McpSecretRow.owner_id == owner_id,
                    McpSecretRow.key_name == key_name,
                )
            )
            existing = result.scalar_one_or_none()
            if existing is not None:
                existing.ciphertext = ciphertext
                existing.key_hint = key_hint
            else:
                session.add(
                    McpSecretRow(
                        id=uuid.uuid4().hex,
                        server_id=server_id,
                        owner_id=owner_id,
                        key_name=key_name,
                        ciphertext=ciphertext,
                        key_hint=key_hint,
                    )
                )
            await session.commit()
        return key_hint

    async def delete(self, *, server_id: str, owner_id: str, key_name: str) -> bool:
        """Remove a specific secret. Returns True if a row was deleted."""
        stmt = delete(McpSecretRow).where(
            McpSecretRow.server_id == server_id,
            McpSecretRow.owner_id == owner_id,
            McpSecretRow.key_name == key_name,
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            await session.commit()
        return result.rowcount > 0

    async def delete_all_for_server(self, *, server_id: str, owner_id: str) -> int:
        """Remove all secrets for a server. Returns the number of rows deleted."""
        stmt = delete(McpSecretRow).where(
            McpSecretRow.server_id == server_id,
            McpSecretRow.owner_id == owner_id,
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            await session.commit()
        return result.rowcount

    # ------------------------------------------------------------------
    # Read operations — key names only; values never returned
    # ------------------------------------------------------------------

    async def list_key_info(self, *, server_id: str, owner_id: str) -> list[dict]:
        """Return key names and their non-sensitive hints.

        Returns a list of ``{"key_name": str, "key_hint": str | None}`` dicts.
        The ``key_hint`` is the last 5 chars of the plaintext, stored at write
        time. Values (ciphertext or plaintext) are NEVER included.
        """
        stmt = (
            select(McpSecretRow.key_name, McpSecretRow.key_hint)
            .where(
                McpSecretRow.server_id == server_id,
                McpSecretRow.owner_id == owner_id,
            )
            .order_by(McpSecretRow.key_name)
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [{"key_name": row[0], "key_hint": row[1]} for row in result.fetchall()]

    async def reveal(self, *, server_id: str, owner_id: str, key_name: str) -> str | None:
        """Decrypt one stored secret for its owner; ``None`` when it is not stored.

        The only public decrypt path. The router gates it on server ownership,
        a re-entered password and an audit log line (key name only). The
        caller MUST NOT log or forward the value to agent/model context.
        """
        stmt = select(McpSecretRow).where(
            McpSecretRow.server_id == server_id,
            McpSecretRow.owner_id == owner_id,
            McpSecretRow.key_name == key_name,
        )
        async with self._sf() as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
        return None if row is None else self._fernet.decrypt(row.ciphertext).decode()

    # ------------------------------------------------------------------
    # Internal decrypt — only called by MCPServerManager for sandbox injection
    # ------------------------------------------------------------------

    async def _decrypt_for_sandbox(self, *, server_id: str, owner_id: str) -> dict[str, str]:
        """Decrypt all secrets for sandbox injection.

        This method is intentionally underscore-prefixed and not exported from
        the module's public surface. Only ``MCPServerManager`` calls it, and
        only immediately before sandbox launch (Phase 4+).

        Returns a mapping of key_name → plaintext. The caller MUST NOT log,
        serialize, or forward this dict to agent/model context.
        """
        stmt = select(McpSecretRow).where(
            McpSecretRow.server_id == server_id,
            McpSecretRow.owner_id == owner_id,
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            rows = result.scalars().all()

        return {row.key_name: self._fernet.decrypt(row.ciphertext).decode() for row in rows}

    # ------------------------------------------------------------------
    # Static helpers (no DB, no Fernet)
    # ------------------------------------------------------------------

    @staticmethod
    def scan_for_required_keys(source_code: str) -> list[str]:
        """Return env-var names referenced via os.getenv() in source_code.

        Delegates to :func:`omniharness.skills.code_scanner.extract_env_keys`.
        This is a static method so the manager can call it without touching
        Fernet or the DB.
        """
        return extract_env_keys(source_code)
