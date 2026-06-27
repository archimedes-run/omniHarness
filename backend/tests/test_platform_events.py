"""Tests for platform event envelope and writer."""

from __future__ import annotations

import pytest

from omniharness.platform.events import EventSource, PlatformEvent
from omniharness.platform.writer import emit_platform_event
from omniharness.runtime.events.store.memory import MemoryRunEventStore

# ---------------------------------------------------------------------------
# EventSource
# ---------------------------------------------------------------------------


def test_event_source_values():
    assert EventSource.RUN == "run"
    assert EventSource.WORKFLOW == "workflow"
    assert EventSource.CHANNEL == "channel"
    assert len(EventSource) == 8


def test_event_source_is_str():
    assert isinstance(EventSource.WORKFLOW, str)


# ---------------------------------------------------------------------------
# PlatformEvent — construction and defaults
# ---------------------------------------------------------------------------


def test_platform_event_defaults():
    ev = PlatformEvent(thread_id="t1", event_type="workflow.created")
    assert ev.source == EventSource.RUN
    assert ev.category == "lifecycle"
    assert ev.content == ""
    assert ev.metadata == {}
    assert ev.run_id is None
    assert ev.seq is None


def test_platform_event_explicit_source():
    ev = PlatformEvent(
        thread_id="t1",
        event_type="workflow.step.started",
        source=EventSource.WORKFLOW,
    )
    assert ev.source == EventSource.WORKFLOW


# ---------------------------------------------------------------------------
# to_store_kwargs — sentinel for no-run-yet
# ---------------------------------------------------------------------------


def test_to_store_kwargs_no_run_id():
    ev = PlatformEvent(thread_id="plat-workflow-abc", event_type="workflow.created", source=EventSource.WORKFLOW)
    kwargs = ev.to_store_kwargs()
    assert kwargs["run_id"] == "platform"
    assert kwargs["source"] == "workflow"
    assert kwargs["thread_id"] == "plat-workflow-abc"


def test_to_store_kwargs_with_run_id():
    ev = PlatformEvent(thread_id="t1", run_id="run-123", event_type="workflow.step.started", source=EventSource.WORKFLOW)
    kwargs = ev.to_store_kwargs()
    assert kwargs["run_id"] == "run-123"


# ---------------------------------------------------------------------------
# round-trip: from_dict
# ---------------------------------------------------------------------------


def test_from_dict_round_trip():
    ev = PlatformEvent(
        thread_id="t1",
        event_type="workflow.archived",
        source=EventSource.WORKFLOW,
        category="lifecycle",
        content="archived by user",
        metadata={"workflow_id": "wf-1"},
    )
    d = ev.to_store_kwargs()
    d.update({"seq": 7, "created_at": "2026-06-27T00:00:00+00:00", "user_id": None})
    restored = PlatformEvent.from_dict(d)
    assert restored.thread_id == "t1"
    assert restored.run_id is None  # "platform" sentinel → None
    assert restored.source == EventSource.WORKFLOW
    assert restored.event_type == "workflow.archived"
    assert restored.metadata == {"workflow_id": "wf-1"}
    assert restored.seq == 7


def test_from_dict_null_source_defaults_to_run():
    d = {
        "thread_id": "t1",
        "run_id": "run-abc",
        "event_type": "human_message",
        "category": "message",
        "content": "hello",
        "metadata": {},
        "seq": 1,
        "source": None,
    }
    ev = PlatformEvent.from_dict(d)
    assert ev.source == EventSource.RUN


# ---------------------------------------------------------------------------
# emit_platform_event — uses existing store, no parallel store
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emit_uses_existing_store():
    store = MemoryRunEventStore()
    result = await emit_platform_event(
        store,
        thread_id="plat-workflow-wf1",
        event_type="workflow.created",
        source=EventSource.WORKFLOW,
        metadata={"workflow_id": "wf1"},
    )
    assert result.seq == 1
    assert result.source == EventSource.WORKFLOW
    assert result.event_type == "workflow.created"
    assert result.run_id is None  # sentinel stripped on read-back
    # Confirm the store has exactly one event in its internal state
    assert len(store._events.get("plat-workflow-wf1", [])) == 1


@pytest.mark.asyncio
async def test_emit_seq_increments_per_thread():
    store = MemoryRunEventStore()
    r1 = await emit_platform_event(store, thread_id="plat-workflow-wf2", event_type="a", source=EventSource.WORKFLOW)
    r2 = await emit_platform_event(store, thread_id="plat-workflow-wf2", event_type="b", source=EventSource.WORKFLOW)
    assert r2.seq == r1.seq + 1


@pytest.mark.asyncio
async def test_emit_does_not_pollute_other_threads():
    store = MemoryRunEventStore()
    # existing "chat" thread has its own seq counter
    await store.put(thread_id="chat-thread-1", run_id="run-1", event_type="human_message", category="message", content="hi")
    r = await emit_platform_event(store, thread_id="plat-workflow-wf3", event_type="workflow.created", source=EventSource.WORKFLOW)
    # platform thread seq starts from 1 regardless of chat thread
    assert r.seq == 1
    # chat thread still has one event at seq 1
    msgs = await store.list_messages("chat-thread-1")
    assert len(msgs) == 1
    assert msgs[0]["seq"] == 1


@pytest.mark.asyncio
async def test_emit_with_run_id():
    store = MemoryRunEventStore()
    result = await emit_platform_event(
        store,
        thread_id="t-run",
        run_id="run-abc",
        event_type="workflow.step.started",
        source=EventSource.WORKFLOW,
    )
    assert result.run_id == "run-abc"


@pytest.mark.asyncio
async def test_existing_store_events_unaffected():
    """Existing events written without source should round-trip with source=None."""
    store = MemoryRunEventStore()
    raw = await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", content="hello")
    assert raw.get("source") is None
    # list_messages still returns the event
    msgs = await store.list_messages("t1")
    assert len(msgs) == 1
    assert msgs[0]["event_type"] == "human_message"
