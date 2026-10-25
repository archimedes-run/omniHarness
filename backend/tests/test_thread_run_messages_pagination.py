"""Tests for paginated GET /api/threads/{thread_id}/runs/{run_id}/messages endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.routers import thread_runs

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app(event_store=None):
    """Build a test FastAPI app with stub auth and mocked state."""
    app = make_authed_test_app()
    app.include_router(thread_runs.router)

    if event_store is not None:
        app.state.run_event_store = event_store

    return app


def _make_event_store(rows: list[dict]):
    """Return an AsyncMock event store whose list_messages_by_run() returns rows."""
    store = MagicMock()
    store.list_messages_by_run = AsyncMock(return_value=rows)
    return store


def _make_message(seq: int) -> dict:
    return {"seq": seq, "event_type": "ai_message", "category": "message", "content": f"msg-{seq}"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_returns_paginated_envelope():
    """GET /api/threads/{tid}/runs/{rid}/messages returns {data: [...], has_more: bool}."""
    rows = [_make_message(i) for i in range(1, 4)]
    app = _make_app(event_store=_make_event_store(rows))
    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/runs/run-1/messages")
    assert response.status_code == 200
    body = response.json()
    assert "data" in body
    assert "has_more" in body
    assert body["has_more"] is False
    assert len(body["data"]) == 3


def test_has_more_true_when_extra_row_returned():
    """has_more=True when event store returns limit+1 rows."""
    # Default limit is 50; provide 51 rows
    rows = [_make_message(i) for i in range(1, 52)]  # 51 rows
    app = _make_app(event_store=_make_event_store(rows))
    with TestClient(app) as client:
        response = client.get("/api/threads/thread-2/runs/run-2/messages")
    assert response.status_code == 200
    body = response.json()
    assert body["has_more"] is True
    assert len(body["data"]) == 50  # trimmed to limit


def test_after_seq_forwarded_to_event_store():
    """after_seq query param is forwarded to event_store.list_messages_by_run."""
    rows = [_make_message(10)]
    event_store = _make_event_store(rows)
    app = _make_app(event_store=event_store)
    with TestClient(app) as client:
        response = client.get("/api/threads/thread-3/runs/run-3/messages?after_seq=5")
    assert response.status_code == 200
    event_store.list_messages_by_run.assert_awaited_once_with(
        "thread-3",
        "run-3",
        limit=51,  # default limit(50) + 1
        before_seq=None,
        after_seq=5,
    )


def test_before_seq_forwarded_to_event_store():
    """before_seq query param is forwarded to event_store.list_messages_by_run."""
    rows = [_make_message(3)]
    event_store = _make_event_store(rows)
    app = _make_app(event_store=event_store)
    with TestClient(app) as client:
        response = client.get("/api/threads/thread-4/runs/run-4/messages?before_seq=10")
    assert response.status_code == 200
    event_store.list_messages_by_run.assert_awaited_once_with(
        "thread-4",
        "run-4",
        limit=51,
        before_seq=10,
        after_seq=None,
    )


def test_custom_limit_forwarded_to_event_store():
    """Custom limit is forwarded as limit+1 to the event store."""
    rows = [_make_message(i) for i in range(1, 6)]
    event_store = _make_event_store(rows)
    app = _make_app(event_store=event_store)
    with TestClient(app) as client:
        response = client.get("/api/threads/thread-5/runs/run-5/messages?limit=10")
    assert response.status_code == 200
    event_store.list_messages_by_run.assert_awaited_once_with(
        "thread-5",
        "run-5",
        limit=11,  # 10 + 1
        before_seq=None,
        after_seq=None,
    )


def test_empty_data_when_no_messages():
    """Returns empty data list with has_more=False when no messages exist."""
    app = _make_app(event_store=_make_event_store([]))
    with TestClient(app) as client:
        response = client.get("/api/threads/thread-6/runs/run-6/messages")
    assert response.status_code == 200
    body = response.json()
    assert body["data"] == []
    assert body["has_more"] is False


# ---------------------------------------------------------------------------
# Paging through a REAL store: every row once, the newest included
# ---------------------------------------------------------------------------


def _memory_store_with(rows: int):
    import asyncio

    from omniharness.runtime.events.store.memory import MemoryRunEventStore

    store = MemoryRunEventStore()
    events = [{"thread_id": "t-long", "run_id": "r-long", "event_type": "llm.ai.response", "category": "message", "content": f"msg-{i}", "metadata": {}} for i in range(1, rows + 1)]
    asyncio.run(store.put_batch(events))
    return store


def _page_back(client, url: str, limit: int) -> list[dict]:
    """Every row, as the chat reads them: the newest page, then before_seq."""
    rows: list[dict] = []
    before = None
    while True:
        query = f"limit={limit}" + (f"&before_seq={before}" if before is not None else "")
        body = client.get(f"{url}?{query}").json()
        assert len(body["data"]) <= limit
        rows = body["data"] + rows
        if not body["has_more"]:
            return rows
        before = body["data"][0]["seq"]


def test_a_full_latest_page_keeps_the_newest_row():
    """The store returns the newest limit+1 rows oldest first; the extra one
    is the OLDEST. Trimming the other end lost a run's final answer."""
    app = _make_app(event_store=_memory_store_with(25))
    with TestClient(app) as client:
        body = client.get("/api/threads/t-long/runs/r-long/messages?limit=10").json()
    assert body["has_more"] is True
    assert [r["content"] for r in body["data"]] == [f"msg-{i}" for i in range(16, 26)]


def test_paging_back_returns_every_row_once_in_order():
    app = _make_app(event_store=_memory_store_with(25))
    with TestClient(app) as client:
        rows = _page_back(client, "/api/threads/t-long/runs/r-long/messages", 10)
        forward = client.get("/api/threads/t-long/runs/r-long/messages?limit=10&after_seq=0").json()
    assert [r["content"] for r in rows] == [f"msg-{i}" for i in range(1, 26)]
    # Paging forward keeps the oldest rows of the window (its look-ahead is the newest).
    assert forward["has_more"] is True
    assert [r["content"] for r in forward["data"]] == [f"msg-{i}" for i in range(1, 11)]
