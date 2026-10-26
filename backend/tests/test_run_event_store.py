"""Tests for RunEventStore contract across all backends.

Uses a helper to create the store for each backend type.
Memory tests run directly; DB and JSONL tests create stores inside each test.
"""

import pytest

from omniharness.runtime.events.store.memory import MemoryRunEventStore


@pytest.fixture
def store():
    return MemoryRunEventStore()


# -- Basic write and query --


class TestPutAndSeq:
    @pytest.mark.anyio
    async def test_put_returns_dict_with_seq(self, store):
        record = await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", content="hello")
        assert "seq" in record
        assert record["seq"] == 1
        assert record["thread_id"] == "t1"
        assert record["run_id"] == "r1"
        assert record["event_type"] == "human_message"
        assert record["category"] == "message"
        assert record["content"] == "hello"
        assert "created_at" in record

    @pytest.mark.anyio
    async def test_seq_strictly_increasing_same_thread(self, store):
        r1 = await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        r2 = await store.put(thread_id="t1", run_id="r1", event_type="ai_message", category="message")
        r3 = await store.put(thread_id="t1", run_id="r1", event_type="llm_end", category="trace")
        assert r1["seq"] == 1
        assert r2["seq"] == 2
        assert r3["seq"] == 3

    @pytest.mark.anyio
    async def test_seq_independent_across_threads(self, store):
        r1 = await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        r2 = await store.put(thread_id="t2", run_id="r2", event_type="human_message", category="message")
        assert r1["seq"] == 1
        assert r2["seq"] == 1

    @pytest.mark.anyio
    async def test_put_respects_provided_created_at(self, store):
        ts = "2024-06-01T12:00:00+00:00"
        record = await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", created_at=ts)
        assert record["created_at"] == ts

    @pytest.mark.anyio
    async def test_put_metadata_preserved(self, store):
        meta = {"model": "gpt-4", "tokens": 100}
        record = await store.put(thread_id="t1", run_id="r1", event_type="llm_end", category="trace", metadata=meta)
        assert record["metadata"] == meta


# -- list_messages --


class TestListMessages:
    @pytest.mark.anyio
    async def test_only_returns_message_category(self, store):
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        await store.put(thread_id="t1", run_id="r1", event_type="llm_end", category="trace")
        await store.put(thread_id="t1", run_id="r1", event_type="run_start", category="lifecycle")
        messages = await store.list_messages("t1")
        assert len(messages) == 1
        assert messages[0]["category"] == "message"

    @pytest.mark.anyio
    async def test_ascending_seq_order(self, store):
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", content="first")
        await store.put(thread_id="t1", run_id="r1", event_type="ai_message", category="message", content="second")
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", content="third")
        messages = await store.list_messages("t1")
        seqs = [m["seq"] for m in messages]
        assert seqs == sorted(seqs)

    @pytest.mark.anyio
    async def test_before_seq_pagination(self, store):
        for i in range(10):
            await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", content=str(i))
        messages = await store.list_messages("t1", before_seq=6, limit=3)
        assert len(messages) == 3
        assert [m["seq"] for m in messages] == [3, 4, 5]

    @pytest.mark.anyio
    async def test_after_seq_pagination(self, store):
        for i in range(10):
            await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", content=str(i))
        messages = await store.list_messages("t1", after_seq=7, limit=3)
        assert len(messages) == 3
        assert [m["seq"] for m in messages] == [8, 9, 10]

    @pytest.mark.anyio
    async def test_limit_restricts_count(self, store):
        for _ in range(20):
            await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        messages = await store.list_messages("t1", limit=5)
        assert len(messages) == 5

    @pytest.mark.anyio
    async def test_cross_run_unified_ordering(self, store):
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        await store.put(thread_id="t1", run_id="r1", event_type="ai_message", category="message")
        await store.put(thread_id="t1", run_id="r2", event_type="human_message", category="message")
        await store.put(thread_id="t1", run_id="r2", event_type="ai_message", category="message")
        messages = await store.list_messages("t1")
        assert [m["seq"] for m in messages] == [1, 2, 3, 4]
        assert messages[0]["run_id"] == "r1"
        assert messages[2]["run_id"] == "r2"

    @pytest.mark.anyio
    async def test_default_returns_latest(self, store):
        for _ in range(10):
            await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        messages = await store.list_messages("t1", limit=3)
        assert [m["seq"] for m in messages] == [8, 9, 10]


# -- list_events --


class TestListEvents:
    @pytest.mark.anyio
    async def test_returns_all_categories_for_run(self, store):
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        await store.put(thread_id="t1", run_id="r1", event_type="llm_end", category="trace")
        await store.put(thread_id="t1", run_id="r1", event_type="run_start", category="lifecycle")
        events = await store.list_events("t1", "r1")
        assert len(events) == 3

    @pytest.mark.anyio
    async def test_event_types_filter(self, store):
        await store.put(thread_id="t1", run_id="r1", event_type="llm_start", category="trace")
        await store.put(thread_id="t1", run_id="r1", event_type="llm_end", category="trace")
        await store.put(thread_id="t1", run_id="r1", event_type="tool_start", category="trace")
        events = await store.list_events("t1", "r1", event_types=["llm_end"])
        assert len(events) == 1
        assert events[0]["event_type"] == "llm_end"

    @pytest.mark.anyio
    async def test_only_returns_specified_run(self, store):
        await store.put(thread_id="t1", run_id="r1", event_type="llm_end", category="trace")
        await store.put(thread_id="t1", run_id="r2", event_type="llm_end", category="trace")
        events = await store.list_events("t1", "r1")
        assert len(events) == 1
        assert events[0]["run_id"] == "r1"


# -- list_messages_by_run --


class TestListMessagesByRun:
    @pytest.mark.anyio
    async def test_only_messages_for_specified_run(self, store):
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        await store.put(thread_id="t1", run_id="r1", event_type="llm_end", category="trace")
        await store.put(thread_id="t1", run_id="r2", event_type="human_message", category="message")
        messages = await store.list_messages_by_run("t1", "r1")
        assert len(messages) == 1
        assert messages[0]["run_id"] == "r1"
        assert messages[0]["category"] == "message"


# -- count_messages --


class TestCountMessages:
    @pytest.mark.anyio
    async def test_counts_only_message_category(self, store):
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        await store.put(thread_id="t1", run_id="r1", event_type="ai_message", category="message")
        await store.put(thread_id="t1", run_id="r1", event_type="llm_end", category="trace")
        assert await store.count_messages("t1") == 2


# -- put_batch --


class TestPutBatch:
    @pytest.mark.anyio
    async def test_batch_assigns_seq(self, store):
        events = [
            {"thread_id": "t1", "run_id": "r1", "event_type": "human_message", "category": "message", "content": "a"},
            {"thread_id": "t1", "run_id": "r1", "event_type": "ai_message", "category": "message", "content": "b"},
            {"thread_id": "t1", "run_id": "r1", "event_type": "llm_end", "category": "trace"},
        ]
        results = await store.put_batch(events)
        assert len(results) == 3
        assert all("seq" in r for r in results)

    @pytest.mark.anyio
    async def test_batch_seq_strictly_increasing(self, store):
        events = [
            {"thread_id": "t1", "run_id": "r1", "event_type": "human_message", "category": "message"},
            {"thread_id": "t1", "run_id": "r1", "event_type": "ai_message", "category": "message"},
        ]
        results = await store.put_batch(events)
        assert results[0]["seq"] == 1
        assert results[1]["seq"] == 2


# -- delete --


class TestDelete:
    @pytest.mark.anyio
    async def test_delete_by_thread(self, store):
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        await store.put(thread_id="t1", run_id="r1", event_type="ai_message", category="message")
        await store.put(thread_id="t1", run_id="r2", event_type="llm_end", category="trace")
        count = await store.delete_by_thread("t1")
        assert count == 3
        assert await store.list_messages("t1") == []
        assert await store.count_messages("t1") == 0

    @pytest.mark.anyio
    async def test_delete_by_run(self, store):
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        await store.put(thread_id="t1", run_id="r2", event_type="human_message", category="message")
        await store.put(thread_id="t1", run_id="r2", event_type="llm_end", category="trace")
        count = await store.delete_by_run("t1", "r2")
        assert count == 2
        messages = await store.list_messages("t1")
        assert len(messages) == 1
        assert messages[0]["run_id"] == "r1"

    @pytest.mark.anyio
    async def test_delete_nonexistent_thread_returns_zero(self, store):
        assert await store.delete_by_thread("nope") == 0

    @pytest.mark.anyio
    async def test_delete_nonexistent_run_returns_zero(self, store):
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        assert await store.delete_by_run("t1", "nope") == 0

    @pytest.mark.anyio
    async def test_delete_nonexistent_thread_for_run_returns_zero(self, store):
        assert await store.delete_by_run("nope", "r1") == 0


# -- Edge cases --


class TestEdgeCases:
    @pytest.mark.anyio
    async def test_empty_thread_list_messages(self, store):
        assert await store.list_messages("empty") == []

    @pytest.mark.anyio
    async def test_empty_run_list_events(self, store):
        assert await store.list_events("empty", "r1") == []

    @pytest.mark.anyio
    async def test_empty_thread_count_messages(self, store):
        assert await store.count_messages("empty") == 0


# -- DB-specific tests --


class TestDbRunEventStore:
    """Tests for DbRunEventStore with temp SQLite."""

    @pytest.mark.anyio
    async def test_basic_crud(self, tmp_path):
        from omniharness.persistence.engine import close_engine, get_session_factory, init_engine
        from omniharness.runtime.events.store.db import DbRunEventStore

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        s = DbRunEventStore(get_session_factory())

        r = await s.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", content="hi")
        assert r["seq"] == 1
        r2 = await s.put(thread_id="t1", run_id="r1", event_type="ai_message", category="message", content="hello")
        assert r2["seq"] == 2

        messages = await s.list_messages("t1")
        assert len(messages) == 2

        count = await s.count_messages("t1")
        assert count == 2

        await close_engine()

    @pytest.mark.anyio
    async def test_trace_content_truncation(self, tmp_path):
        from omniharness.persistence.engine import close_engine, get_session_factory, init_engine
        from omniharness.runtime.events.store.db import DbRunEventStore

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        s = DbRunEventStore(get_session_factory(), max_trace_content=100)

        long = "x" * 200
        r = await s.put(thread_id="t1", run_id="r1", event_type="llm_end", category="trace", content=long)
        assert len(r["content"]) == 100
        assert r["metadata"].get("content_truncated") is True

        # message content NOT truncated
        m = await s.put(thread_id="t1", run_id="r1", event_type="ai_message", category="message", content=long)
        assert len(m["content"]) == 200

        await close_engine()

    @pytest.mark.anyio
    async def test_pagination(self, tmp_path):
        from omniharness.persistence.engine import close_engine, get_session_factory, init_engine
        from omniharness.runtime.events.store.db import DbRunEventStore

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        s = DbRunEventStore(get_session_factory())

        for i in range(10):
            await s.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", content=str(i))

        # before_seq
        msgs = await s.list_messages("t1", before_seq=6, limit=3)
        assert [m["seq"] for m in msgs] == [3, 4, 5]

        # after_seq
        msgs = await s.list_messages("t1", after_seq=7, limit=3)
        assert [m["seq"] for m in msgs] == [8, 9, 10]

        # default (latest)
        msgs = await s.list_messages("t1", limit=3)
        assert [m["seq"] for m in msgs] == [8, 9, 10]

        await close_engine()

    @pytest.mark.anyio
    async def test_delete(self, tmp_path):
        from omniharness.persistence.engine import close_engine, get_session_factory, init_engine
        from omniharness.runtime.events.store.db import DbRunEventStore

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        s = DbRunEventStore(get_session_factory())

        await s.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        await s.put(thread_id="t1", run_id="r2", event_type="ai_message", category="message")
        c = await s.delete_by_run("t1", "r2")
        assert c == 1
        assert await s.count_messages("t1") == 1

        c = await s.delete_by_thread("t1")
        assert c == 1
        assert await s.count_messages("t1") == 0

        await close_engine()

    @pytest.mark.anyio
    async def test_put_batch_seq_continuity(self, tmp_path):
        """Batch write produces continuous seq values with no gaps."""
        from omniharness.persistence.engine import close_engine, get_session_factory, init_engine
        from omniharness.runtime.events.store.db import DbRunEventStore

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        s = DbRunEventStore(get_session_factory())

        events = [{"thread_id": "t1", "run_id": "r1", "event_type": "trace", "category": "trace"} for _ in range(50)]
        results = await s.put_batch(events)
        seqs = [r["seq"] for r in results]
        assert seqs == list(range(1, 51))
        await close_engine()

    @pytest.mark.anyio
    async def test_content_that_is_not_text_or_a_dict_is_stored(self, tmp_path):
        """A chain's outputs can be a list. The driver could not bind it, the
        whole batch was refused, and the journal kept none of its messages."""
        from omniharness.persistence.engine import close_engine, get_session_factory, init_engine
        from omniharness.runtime.events.store.db import DbRunEventStore

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        s = DbRunEventStore(get_session_factory())
        await s.put_batch(
            [
                {"thread_id": "t1", "run_id": "r1", "event_type": "run.end", "category": "outputs", "content": [{"a": 1}, "b"]},
                {"thread_id": "t1", "run_id": "r1", "event_type": "trace", "category": "trace", "content": ["x", 2]},
                {"thread_id": "t1", "run_id": "r1", "event_type": "llm.human.input", "category": "message", "content": {"type": "human", "content": "hi"}},
            ]
        )
        events = await s.list_events("t1", "r1")
        assert [e["content"] for e in events] == [[{"a": 1}, "b"], ["x", 2], {"type": "human", "content": "hi"}]
        await close_engine()

    @pytest.mark.anyio
    async def test_a_batch_commits_while_the_event_loop_is_blocked(self, tmp_path):
        """SQLite locks the whole file for a write. Through aiosqlite a batch
        needs the event loop to reach its COMMIT, so gateway code writing
        synchronously ON the loop (the ledger's plan check before a card)
        waited on the batch's lock with the loop blocked, until "database is
        locked" failed the run. Journal batches are now written while a run
        goes, so they commit from a worker thread, without the loop."""
        import asyncio
        import sqlite3
        import time

        from omniharness.persistence.engine import close_engine, get_session_factory, init_engine
        from omniharness.runtime.events.store.db import DbRunEventStore

        db = tmp_path / "test.db"
        await init_engine("sqlite", url=f"sqlite+aiosqlite:///{db}", sqlite_dir=str(tmp_path))
        s = DbRunEventStore(get_session_factory())
        await s.put_batch([{"thread_id": "t1", "run_id": "r1", "event_type": "warm", "category": "trace", "content": "x"}])
        task = asyncio.create_task(s.put_batch([{"thread_id": "t1", "run_id": "r1", "event_type": "llm.human.input", "category": "message", "content": {"type": "human", "content": "hi"}}]))
        await asyncio.sleep(0)  # the batch starts
        deadline = time.monotonic() + 3
        found = 0
        while time.monotonic() < deadline and not found:  # the loop is blocked here
            time.sleep(0.05)
            with sqlite3.connect(db, timeout=0.1) as conn:
                found = conn.execute("SELECT count(*) FROM run_events WHERE event_type = 'llm.human.input'").fetchone()[0]
        assert found == 1, "the batch could not commit while the event loop was blocked"
        await task
        await close_engine()

    @pytest.mark.anyio
    async def test_batches_of_one_thread_written_at_once_number_their_events_apart(self, tmp_path):
        """The sync connection takes the write lock (BEGIN IMMEDIATE) before
        reading max(seq), so concurrent batches never collide on
        UNIQUE(thread_id, seq); and it runs with the async engine's pragmas."""
        import asyncio

        from omniharness.persistence.engine import close_engine, get_session_factory, init_engine
        from omniharness.runtime.events.store.db import DbRunEventStore

        await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}", sqlite_dir=str(tmp_path))
        s = DbRunEventStore(get_session_factory())
        batches = [[{"thread_id": "t1", "run_id": f"r{n}", "event_type": "trace", "category": "trace", "content": f"{n}-{i}"} for i in range(5)] for n in range(12)]
        results = await asyncio.gather(*(s.put_batch(b) for b in batches))
        seqs = sorted(r["seq"] for batch in results for r in batch)
        assert seqs == list(range(1, 61))
        with s._sqlite_sync_engine().connect() as conn:
            assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
            assert conn.exec_driver_sql("PRAGMA synchronous").scalar() == 1  # NORMAL
        await close_engine()


# -- Factory tests --


class TestMakeRunEventStore:
    """Tests for the make_run_event_store factory function."""

    @pytest.mark.anyio
    async def test_memory_backend_default(self):
        from omniharness.persistence.engine import close_engine
        from omniharness.runtime.events.store import make_run_event_store

        await close_engine()  # no database (a failed test may leave one open)

        store = make_run_event_store(None)
        assert type(store).__name__ == "MemoryRunEventStore"

    @pytest.mark.anyio
    async def test_memory_backend_explicit(self):
        from unittest.mock import MagicMock

        from omniharness.runtime.events.store import make_run_event_store

        config = MagicMock()
        config.backend = "memory"
        store = make_run_event_store(config)
        assert type(store).__name__ == "MemoryRunEventStore"

    @pytest.mark.anyio
    async def test_db_backend_with_engine(self, tmp_path):
        from unittest.mock import MagicMock

        from omniharness.persistence.engine import close_engine, init_engine
        from omniharness.runtime.events.store import make_run_event_store

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))

        config = MagicMock()
        config.backend = "db"
        config.max_trace_content = 10240
        store = make_run_event_store(config)
        assert type(store).__name__ == "DbRunEventStore"
        await close_engine()

    @pytest.mark.anyio
    async def test_db_backend_no_engine_falls_back(self):
        """db backend without engine falls back to memory."""
        from unittest.mock import MagicMock

        from omniharness.persistence.engine import close_engine, init_engine
        from omniharness.runtime.events.store import make_run_event_store

        await init_engine("memory")  # no engine created

        config = MagicMock()
        config.backend = "db"
        store = make_run_event_store(config)
        assert type(store).__name__ == "MemoryRunEventStore"
        await close_engine()

    @pytest.mark.anyio
    async def test_auto_backend_uses_the_database_when_there_is_one(self, tmp_path):
        """The run journal is the chat's display history once a conversation
        is summarized; in memory it was lost on every gateway restart."""
        from unittest.mock import MagicMock

        from omniharness.persistence.engine import close_engine, init_engine
        from omniharness.runtime.events.store import make_run_event_store

        config = MagicMock()
        config.backend = "auto"
        config.max_trace_content = 10240
        await init_engine("memory")
        assert type(make_run_event_store(config)).__name__ == "MemoryRunEventStore"
        await close_engine()
        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        assert type(make_run_event_store(config)).__name__ == "DbRunEventStore"
        await close_engine()

    def test_the_default_backend_is_auto(self):
        from omniharness.config.run_events_config import RunEventsConfig

        assert RunEventsConfig().backend == "auto"

    @pytest.mark.anyio
    async def test_jsonl_backend(self):
        from unittest.mock import MagicMock

        from omniharness.runtime.events.store import make_run_event_store

        config = MagicMock()
        config.backend = "jsonl"
        store = make_run_event_store(config)
        assert type(store).__name__ == "JsonlRunEventStore"

    @pytest.mark.anyio
    async def test_unknown_backend_raises(self):
        from unittest.mock import MagicMock

        from omniharness.runtime.events.store import make_run_event_store

        config = MagicMock()
        config.backend = "redis"
        with pytest.raises(ValueError, match="Unknown"):
            make_run_event_store(config)


# -- JSONL-specific tests --


class TestJsonlRunEventStore:
    @pytest.mark.anyio
    async def test_basic_crud(self, tmp_path):
        from omniharness.runtime.events.store.jsonl import JsonlRunEventStore

        s = JsonlRunEventStore(base_dir=tmp_path / "jsonl")
        r = await s.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", content="hi")
        assert r["seq"] == 1
        messages = await s.list_messages("t1")
        assert len(messages) == 1

    @pytest.mark.anyio
    async def test_file_at_correct_path(self, tmp_path):
        from omniharness.runtime.events.store.jsonl import JsonlRunEventStore

        s = JsonlRunEventStore(base_dir=tmp_path / "jsonl")
        await s.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        assert (tmp_path / "jsonl" / "threads" / "t1" / "runs" / "r1.jsonl").exists()

    @pytest.mark.anyio
    async def test_cross_run_messages(self, tmp_path):
        from omniharness.runtime.events.store.jsonl import JsonlRunEventStore

        s = JsonlRunEventStore(base_dir=tmp_path / "jsonl")
        await s.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        await s.put(thread_id="t1", run_id="r2", event_type="human_message", category="message")
        messages = await s.list_messages("t1")
        assert len(messages) == 2
        assert [m["seq"] for m in messages] == [1, 2]

    @pytest.mark.anyio
    async def test_delete_by_run(self, tmp_path):
        from omniharness.runtime.events.store.jsonl import JsonlRunEventStore

        s = JsonlRunEventStore(base_dir=tmp_path / "jsonl")
        await s.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        await s.put(thread_id="t1", run_id="r2", event_type="human_message", category="message")
        c = await s.delete_by_run("t1", "r2")
        assert c == 1
        assert not (tmp_path / "jsonl" / "threads" / "t1" / "runs" / "r2.jsonl").exists()
        assert await s.count_messages("t1") == 1
