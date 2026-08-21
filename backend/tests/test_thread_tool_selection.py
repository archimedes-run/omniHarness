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
    # Derived from PINNED_SOURCES rather than hardcoded: this test previously
    # spelled the pinned set out inline, so adding one broke it for a reason
    # that had nothing to do with dedup or ordering.
    result = _enforce_pinned(["local:filesystem", "connector:GMAIL", "connector:GMAIL", "local:github"])
    assert result[: len(PINNED_SOURCES)] == list(PINNED_SOURCES)
    assert result[len(PINNED_SOURCES) :] == ["connector:GMAIL", "local:github"]
    assert len(result) == len(set(result)), "duplicates survived"


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
    assert saved[: len(PINNED_SOURCES)] == list(PINNED_SOURCES)
    assert "connector:GITHUB" in saved and "local:github" in saved

    # Reload from a fresh repo instance → identical, namespaced.
    repo2 = ThreadToolSelectionRepository(sf)
    reloaded = await repo2.get_sources(thread_id="t1")
    assert reloaded == saved
    await engine.dispose()


def test_the_two_pinned_lists_cannot_drift() -> None:
    """One canonical list, one derived — asserted so they cannot diverge again.

    They did diverge: session-watcher was added to the runtime filter
    (PINNED_LOCAL_SERVERS) and not to the persistence list (PINNED_SOURCES).
    Nothing broke — the runtime used its own copy and worked — but the tools
    picker reported a `pinned` set that was false, which is worse than a break
    because it teaches the next reader something untrue.
    """
    from omniharness.tools.tools import PINNED_LOCAL_SERVERS

    assert {f"local:{s}" for s in PINNED_LOCAL_SERVERS} == set(PINNED_SOURCES)


def test_pinned_sources_is_the_canonical_definition() -> None:
    """Guard the direction of the dependency, not just the values.

    If someone re-hardcodes PINNED_LOCAL_SERVERS as a literal, the test above
    still passes on the day they do it and fails silently later. This asserts
    the derivation itself.
    """
    import inspect

    from omniharness.tools import tools as tools_mod

    src = inspect.getsource(tools_mod)
    marker = "PINNED_LOCAL_SERVERS: frozenset[str] = frozenset("
    assert marker in src
    tail = src.split(marker, 1)[1][:200]
    assert "PINNED_SOURCES" in tail, "PINNED_LOCAL_SERVERS is no longer derived from PINNED_SOURCES; a hand-maintained second copy is how these drifted before"
