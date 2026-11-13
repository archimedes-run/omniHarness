"""A subagent's checkpoint connection waits for the store's other users.

Switching the store to WAL needs a lock another connection may hold (the
gateway's reader, a sibling subagent switching at the same moment), and
SQLite can answer "database is locked" at once there, without its busy
handler. A confirmed delegation then failed outright and freed its
confirmation slot early (seen in CI as a flaky test_confirm_pool_118).
"""

from __future__ import annotations

import asyncio
import sqlite3

import pytest


@pytest.fixture
def executor(monkeypatch):
    """The real executor module (tests/conftest.py stands a mock in for it)."""
    import importlib
    import sys

    monkeypatch.delitem(sys.modules, "omniharness.subagents.executor", raising=False)
    return importlib.import_module("omniharness.subagents.executor")


async def _prepare(path: str) -> None:
    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    conn = await aiosqlite.connect(path)
    await AsyncSqliteSaver(conn).setup()  # the gateway made the tables
    await conn.execute("PRAGMA journal_mode=DELETE;")  # and the store is not WAL yet
    await conn.close()


class _Awaitable:
    """Stands in for aiosqlite's awaitable-and-async-context-manager result."""

    def __init__(self, coro):
        self._coro = coro

    def __await__(self):
        return self._coro.__await__()

    async def __aenter__(self):
        return await self._coro

    async def __aexit__(self, *exc):
        return False


def _refuse_wal(monkeypatch, error: str, times: int) -> dict:
    import aiosqlite

    real = aiosqlite.Connection.execute
    left = {"n": times}

    def execute(self, sql, *args, **kwargs):
        if "journal_mode=wal" in str(sql).lower().replace(" ", "") and left["n"] > 0:
            left["n"] -= 1

            async def refused():
                raise sqlite3.OperationalError(error)

            return _Awaitable(refused())
        return real(self, sql, *args, **kwargs)

    monkeypatch.setattr(aiosqlite.Connection, "execute", execute)
    return left


def test_a_locked_switch_to_wal_is_waited_out_not_fatal(tmp_path, monkeypatch, executor):
    """The switch answers "locked" twice (another connection holds the lock),
    then succeeds: the subagent's store opens, in WAL."""
    path = str(tmp_path / "checkpoints.db")
    asyncio.run(_prepare(path))
    left = _refuse_wal(monkeypatch, "database is locked", 2)

    async def main() -> str:
        async with executor._sqlite_run_checkpointer(path) as saver:
            async with saver.conn.execute("PRAGMA journal_mode;") as cursor:
                return str((await cursor.fetchone())[0])

    assert asyncio.run(main()).lower() == "wal"
    assert left["n"] == 0


def test_another_error_is_not_retried(tmp_path, monkeypatch, executor):
    path = str(tmp_path / "checkpoints.db")
    asyncio.run(_prepare(path))
    _refuse_wal(monkeypatch, "disk I/O error", 10)

    async def main() -> None:
        async with executor._sqlite_run_checkpointer(path):
            pass

    with pytest.raises(sqlite3.OperationalError, match="disk I/O"):
        asyncio.run(main())
