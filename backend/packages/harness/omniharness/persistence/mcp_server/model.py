"""ORM model for user-owned MCP server records."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from omniharness.persistence.base import Base


class McpServerRow(Base):
    __tablename__ = "mcp_servers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    language: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(String(1024))
    # "not_running" | "starting" | "deployed" | "failed" | "stopped"
    status: Mapped[str] = mapped_column(String(32), default="not_running")
    # List of env-var *names* only — values are never stored here.
    detected_secrets: Mapped[list] = mapped_column(JSON, default=list)
    # Explicit human-review approval gate; defaults False — must be set by a
    # privileged action before the server can be registered for agent use.
    approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # JSON list of hostname strings the server is allowed to reach.
    egress_hosts: Mapped[list] = mapped_column(JSON, default=list)
    # Agent-generated source code stored for security scanning.
    source_code: Mapped[str | None] = mapped_column(Text)
    # Build result persisted so tool discovery survives backend restarts.
    tools_discovered: Mapped[list] = mapped_column(JSON, default=list)
    test_results: Mapped[list] = mapped_column(JSON, default=list)
    last_verified_at: Mapped[str | None] = mapped_column(String(64))
    # Docker deployment: container ID and mapped host port (null when not deployed)
    container_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    container_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
