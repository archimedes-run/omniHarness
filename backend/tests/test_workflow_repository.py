"""Tests for WorkflowRepository (SQLAlchemy-backed).

Uses a temp SQLite DB to test ORM-backed CRUD operations.
"""

import pytest

from omniharness.persistence.workflows import WorkflowRepository


async def _make_repo(tmp_path):
    from omniharness.persistence.engine import get_session_factory, init_engine

    url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    return WorkflowRepository(get_session_factory())


async def _cleanup():
    from omniharness.persistence.engine import close_engine

    await close_engine()


class TestWorkflowRepository:
    @pytest.mark.anyio
    async def test_create_and_get(self, tmp_path):
        repo = await _make_repo(tmp_path)
        row = await repo.create(id="w1", owner_id="alice", title="My Workflow")
        assert row is not None
        assert row["id"] == "w1"
        assert row["owner_id"] == "alice"
        assert row["title"] == "My Workflow"
        assert row["status"] == "draft"

        fetched = await repo.get("w1")
        assert fetched is not None
        assert fetched["id"] == "w1"
        await _cleanup()

    @pytest.mark.anyio
    async def test_get_missing_returns_none(self, tmp_path):
        repo = await _make_repo(tmp_path)
        assert await repo.get("nope") is None
        await _cleanup()

    @pytest.mark.anyio
    async def test_get_with_owner_filter(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.create(id="w1", owner_id="alice", title="Alice's Workflow")
        # Correct owner — found
        row = await repo.get("w1", owner_id="alice")
        assert row is not None
        # Wrong owner — not found
        row = await repo.get("w1", owner_id="bob")
        assert row is None
        await _cleanup()

    @pytest.mark.anyio
    async def test_list_by_owner(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.create(id="w1", owner_id="alice", title="A1")
        await repo.create(id="w2", owner_id="alice", title="A2")
        await repo.create(id="w3", owner_id="bob", title="B1")

        alice_rows = await repo.list_by_owner("alice")
        assert len(alice_rows) == 2
        assert all(r["owner_id"] == "alice" for r in alice_rows)

        bob_rows = await repo.list_by_owner("bob")
        assert len(bob_rows) == 1
        assert bob_rows[0]["id"] == "w3"
        await _cleanup()

    @pytest.mark.anyio
    async def test_list_by_owner_none(self, tmp_path):
        """list_by_owner(None) returns all rows (no owner filter)."""
        repo = await _make_repo(tmp_path)
        await repo.create(id="w1", owner_id="alice", title="A")
        await repo.create(id="w2", owner_id="bob", title="B")

        all_rows = await repo.list_by_owner(None)
        assert len(all_rows) == 2
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_title(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.create(id="w1", owner_id="alice", title="Old Title")
        updated = await repo.update("w1", owner_id="alice", title="New Title")
        assert updated is not None
        assert updated["title"] == "New Title"
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_status(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.create(id="w1", owner_id="alice", title="Workflow")
        updated = await repo.update("w1", owner_id="alice", status="active")
        assert updated is not None
        assert updated["status"] == "active"
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_wrong_owner_returns_none(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.create(id="w1", owner_id="alice", title="Workflow")
        result = await repo.update("w1", owner_id="bob", title="Hacked")
        assert result is None
        # Title should not have changed
        row = await repo.get("w1")
        assert row["title"] == "Workflow"
        await _cleanup()

    @pytest.mark.anyio
    async def test_archive(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.create(id="w1", owner_id="alice", title="Workflow")
        row = await repo.archive("w1", owner_id="alice")
        assert row is not None
        assert row["status"] == "archived"
        await _cleanup()

    @pytest.mark.anyio
    async def test_archive_wrong_owner_returns_none(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.create(id="w1", owner_id="alice", title="Workflow")
        result = await repo.archive("w1", owner_id="bob")
        assert result is None
        # Status should still be draft
        row = await repo.get("w1")
        assert row["status"] == "draft"
        await _cleanup()

    @pytest.mark.anyio
    async def test_archive_missing_returns_none(self, tmp_path):
        repo = await _make_repo(tmp_path)
        result = await repo.archive("nope")
        assert result is None
        await _cleanup()

    @pytest.mark.anyio
    async def test_owner_isolation(self, tmp_path):
        """Alice can't see Bob's workflows via list_by_owner."""
        repo = await _make_repo(tmp_path)
        await repo.create(id="w1", owner_id="alice", title="Alice's")
        await repo.create(id="w2", owner_id="bob", title="Bob's")

        alice_rows = await repo.list_by_owner("alice")
        ids = [r["id"] for r in alice_rows]
        assert "w1" in ids
        assert "w2" not in ids
        await _cleanup()
