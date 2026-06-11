"""ORM model for encrypted MCP server secret references.

The ciphertext column holds Fernet-encrypted bytes; the harness layer only
sees opaque bytes. Encryption/decryption lives exclusively in the app layer
(app.gateway.mcp_secrets.McpSecretsVault) and is never performed here.

Invariants:
- owner_id mirrors the McpServerRow.owner_id for the associated server.
- key_name stores the env-var *name* only; no plaintext secret value ever
  appears in this table outside the ciphertext column.
- The (server_id, owner_id, key_name) triple is unique per secret entry.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from omniharness.persistence.base import Base


class McpSecretRow(Base):
    __tablename__ = "mcp_secrets"
    __table_args__ = (UniqueConstraint("server_id", "owner_id", "key_name", name="uq_mcp_secret"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    server_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    key_name: Mapped[str] = mapped_column(String(256), nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=lambda: datetime.now(UTC))
