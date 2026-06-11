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
import uuid
from typing import TYPE_CHECKING

from cryptography.fernet import Fernet
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omniharness.persistence.mcp_secrets.model import McpSecretRow
from omniharness.skills.code_scanner import extract_env_keys

if TYPE_CHECKING:
    from omniharness.config.mcp_builder_config import McpBuilderConfig

logger = logging.getLogger(__name__)


def make_vault_key(config: McpBuilderConfig) -> bytes:
    """Return the Fernet key bytes to use for this process.

    Raises ``RuntimeError`` if ``vault_key`` is absent and ``dev_mode`` is
    False (non-dev mode must have an explicit key — fail loud, not silent).

    If ``vault_key`` is absent but ``dev_mode`` is True, logs a prominent
    warning and generates an ephemeral key. Encrypted secrets stored with an
    ephemeral key are lost on process restart.
    """
    if config.vault_key:
        return config.vault_key.encode()

    if not config.dev_mode:
        raise RuntimeError(
            'mcp_builder.vault_key is required when dev_mode is False. Generate a key with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" and set it in config.yaml under mcp_builder.vault_key.'
        )

    key = Fernet.generate_key()
    logger.warning("MCP secrets vault: using an EPHEMERAL Fernet key (dev_mode=True, vault_key not set). All encrypted secrets will be LOST when the process restarts. Set mcp_builder.vault_key in config.yaml for persistent secrets.")
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

    async def store(self, *, server_id: str, owner_id: str, key_name: str, plaintext_value: str) -> None:
        """Encrypt and upsert a single secret.

        ``owner_id`` MUST be the verified requesting user — never derived from
        the server row itself. Plaintext is discarded after encryption.
        """
        ciphertext: bytes = self._fernet.encrypt(plaintext_value.encode())

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
            else:
                session.add(
                    McpSecretRow(
                        id=uuid.uuid4().hex,
                        server_id=server_id,
                        owner_id=owner_id,
                        key_name=key_name,
                        ciphertext=ciphertext,
                    )
                )
            await session.commit()

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

    async def list_key_names(self, *, server_id: str, owner_id: str) -> list[str]:
        """Return the env-var names stored for this server + owner.

        Values (ciphertext or plaintext) are NEVER included in the return value.
        """
        stmt = (
            select(McpSecretRow.key_name)
            .where(
                McpSecretRow.server_id == server_id,
                McpSecretRow.owner_id == owner_id,
            )
            .order_by(McpSecretRow.key_name)
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [row[0] for row in result.fetchall()]

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
