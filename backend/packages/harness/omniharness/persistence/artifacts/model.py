"""ORM models for the Artifact store (Spec 012, Slice 1, FR-001, FR-002, FR-036).

Metadata only. Content lives content-addressed on disk
(app.gateway.artifacts_store.blobs), under a path built from the owner id and
the hex hash alone. Times are epoch seconds (float), as in the Apps tables.

A version row is written once and never updated: every change is a new row
(FR-002). Only `artifacts` carries mutable fields (title, pin, archive, the
latest version number and the latest text kept for search).
"""

from __future__ import annotations

from sqlalchemy import Boolean, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from omniharness.persistence.base import Base


class ArtifactRow(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    origin_thread_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    origin_turn_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    imported_from: Mapped[str | None] = mapped_column(String(600), nullable=True)
    promoted_app_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latest_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    archived_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: The latest version's text for text kinds (search, FR-034); never served.
    search_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (Index("ix_artifacts_owner_updated", "owner_id", "updated_at"), Index("ix_artifacts_owner_thread", "owner_id", "origin_thread_id"))


class ArtifactVersionRow(Base):
    __tablename__ = "artifact_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    artifact_id: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    n: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    media_type: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # user | content
    lineage: Mapped[str] = mapped_column(String(16), nullable=False)
    lineage_source: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # tool | owner_edit | restore | import | duplicate
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    base_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(String(400), nullable=True)
    thread_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    turn_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # blob (in the store) | chat (an imported file over the cap, left in its chat)
    stored: Mapped[str] = mapped_column(String(8), nullable=False, default="blob")
    #: For stored == "chat": the path under the thread's outputs (relative).
    chat_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("artifact_id", "n", name="uq_artifact_versions_artifact_n"),
        Index("ix_artifact_versions_owner_hash", "owner_id", "content_hash"),
        Index("ix_artifact_versions_owner_thread", "owner_id", "thread_id"),
    )


class ArtifactImportRow(Base):
    """What the lazy importer recorded (FR-037), idempotent by
    (owner, thread, path, content hash). Kept when the artifact is deleted
    (artifact_id set to null), so a deleted import is not made again."""

    __tablename__ = "artifact_imports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    thread_id: Mapped[str] = mapped_column(String(128), nullable=False)
    path: Mapped[str] = mapped_column(String(500), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (UniqueConstraint("owner_id", "thread_id", "path", "content_hash", name="uq_artifact_imports_key"), Index("ix_artifact_imports_owner_thread_path", "owner_id", "thread_id", "path"))
