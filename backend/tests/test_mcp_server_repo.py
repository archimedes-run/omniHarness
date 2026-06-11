"""SQLite-backed integration tests for McpServerRepository owner isolation.

These tests prove the SQL WHERE clause actually filters by owner_id.
The router tests in test_mcp_studio_router.py prove the router calls
the repo without overriding user_id. Together they form the full proof
of cross-user isolation: router → AUTO → contextvar → SQL filter.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from omniharness.persistence.mcp_server import McpServerRepository
from omniharness.persistence.mcp_server.model import McpServerRow


async def _make_repo(tmp_path):
    from omniharness.persistence.engine import get_session_factory, init_engine

    url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    return McpServerRepository(get_session_factory())


async def _cleanup():
    from omniharness.persistence.engine import close_engine

    await close_engine()


async def _insert(repo: McpServerRepository, *, id: str, owner_id: str, name: str = "S") -> None:
    """Insert a row directly — McpServerRepository is read-only in Phase 1."""
    from omniharness.persistence.engine import get_session_factory

    sf = get_session_factory()
    now = datetime.now(UTC)
    async with sf() as session:
        session.add(
            McpServerRow(
                id=id,
                owner_id=owner_id,
                name=name,
                status="deployed",
                detected_secrets=[],
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()


class TestMcpServerRepoOwnerIsolation:
    @pytest.mark.anyio
    async def test_list_only_returns_caller_servers(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await _insert(repo, id="a1", owner_id="user-a", name="A Server")
        await _insert(repo, id="b1", owner_id="user-b", name="B Server")

        a_results = await repo.list_servers(user_id="user-a")
        b_results = await repo.list_servers(user_id="user-b")

        assert [r["id"] for r in a_results] == ["a1"]
        assert [r["id"] for r in b_results] == ["b1"]
        await _cleanup()

    @pytest.mark.anyio
    async def test_list_cross_user_returns_empty(self, tmp_path):
        # User A has a server; user B's list must be empty.
        repo = await _make_repo(tmp_path)
        await _insert(repo, id="a1", owner_id="user-a")

        result = await repo.list_servers(user_id="user-b")
        assert result == [], "user-b must not see user-a's servers"
        await _cleanup()

    @pytest.mark.anyio
    async def test_get_cross_user_returns_none(self, tmp_path):
        # User A owns srv-a; user B must get None, not the row.
        repo = await _make_repo(tmp_path)
        await _insert(repo, id="srv-a", owner_id="user-a")

        result = await repo.get("srv-a", user_id="user-b")
        assert result is None, "user-b must not read user-a's server"
        await _cleanup()

    @pytest.mark.anyio
    async def test_get_owner_returns_row(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await _insert(repo, id="srv-a", owner_id="user-a", name="Mine")

        result = await repo.get("srv-a", user_id="user-a")
        assert result is not None
        assert result["id"] == "srv-a"
        assert result["name"] == "Mine"
        await _cleanup()

    @pytest.mark.anyio
    async def test_get_nonexistent_returns_none(self, tmp_path):
        repo = await _make_repo(tmp_path)

        result = await repo.get("does-not-exist", user_id="user-a")
        assert result is None
        await _cleanup()

    @pytest.mark.anyio
    async def test_list_search_scoped_to_owner(self, tmp_path):
        # Search must not escape the owner boundary: user A has "GitHub",
        # user B searching "GitHub" must get nothing.
        repo = await _make_repo(tmp_path)
        await _insert(repo, id="a1", owner_id="user-a", name="GitHub Integration")

        result = await repo.list_servers(search="GitHub", user_id="user-b")
        assert result == [], "search must not cross owner boundary"
        await _cleanup()

    @pytest.mark.anyio
    async def test_detected_secrets_field_returned_correctly(self, tmp_path):
        # Secrets are env-var *names* only — verify the field round-trips.
        from omniharness.persistence.engine import get_session_factory

        repo = await _make_repo(tmp_path)
        sf = get_session_factory()
        now = datetime.now(UTC)
        async with sf() as session:
            session.add(
                McpServerRow(
                    id="s1",
                    owner_id="user-a",
                    name="Secret Server",
                    status="deployed",
                    detected_secrets=["OPENAI_API_KEY", "STRIPE_SECRET_KEY"],
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.commit()

        result = await repo.get("s1", user_id="user-a")
        assert result is not None
        assert result["detected_secrets"] == ["OPENAI_API_KEY", "STRIPE_SECRET_KEY"]
        await _cleanup()
