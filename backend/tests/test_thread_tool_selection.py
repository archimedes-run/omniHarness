"""Thread tool-selection persistence tests (Part A2).

Covers the server-side pinned-defaults guarantee (the client is never trusted to
include them) and a DB round-trip proving namespaced ids persist and pinned
defaults are always present on read.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import omniharness.persistence.models  # noqa: F401 — register ALL tables so FKs resolve in create_all
from omniharness.persistence.base import Base
from omniharness.persistence.thread_tool_selection.sql import PINNED_SOURCES, ThreadToolSelectionRepository, _enforce_pinned


def test_enforce_pinned_adds_missing_defaults():
    assert _enforce_pinned([]) == list(PINNED_SOURCES)


def test_enforce_pinned_client_cannot_remove_defaults():
    # Client omits pinned and sends only a connector — pinned still injected.
    result = _enforce_pinned(["connector:GMAIL"])
    for p in PINNED_SOURCES:
        assert p in result
    assert "connector:GMAIL" in result


def test_enforce_pinned_dedupes_and_preserves_order():
    result = _enforce_pinned(["local:filesystem", "connector:GMAIL", "connector:GMAIL", "local:github"])
    assert result == ["local:filesystem", "local:postgres", "connector:GMAIL", "local:github"]


@pytest.mark.asyncio
async def test_repo_roundtrip_persists_namespaced_ids_with_pinned():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    repo = ThreadToolSelectionRepository(sf)

    # New thread with no row → pinned defaults on read.
    assert await repo.get_sources(thread_id="t1") == list(PINNED_SOURCES)

    # Save a selection WITHOUT pinned; they must be enforced + persisted.
    saved = await repo.set_sources(thread_id="t1", user_id="user-A", sources=["connector:GITHUB", "local:github"])
    assert saved[:2] == list(PINNED_SOURCES)
    assert "connector:GITHUB" in saved and "local:github" in saved

    # Reload from a fresh repo instance → identical, namespaced.
    repo2 = ThreadToolSelectionRepository(sf)
    reloaded = await repo2.get_sources(thread_id="t1")
    assert reloaded == saved
    await engine.dispose()
