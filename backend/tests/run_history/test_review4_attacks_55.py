"""Fourth adversarial review of PR #55 (run store). Fake values only; HOME and
the key dir are temp dirs (conftest + tmp_path). Each test FAILS on cc9bb00
while the finding stands."""

from __future__ import annotations

import sqlite3
import threading
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Annotated, TypedDict

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph.message import add_messages

from app.run_history.crypto import StoreKey
from app.run_history.store import UNREADABLE, RunHistory


class S(TypedDict):
    messages: Annotated[list, add_messages]


CFG = {"configurable": {"thread_id": "t-auto", "checkpoint_ns": ""}}


def _cp(ts: datetime, messages: list, n: int) -> dict:
    from langgraph.checkpoint.base import empty_checkpoint

    c = empty_checkpoint()
    c["id"] = f"1ef00000-0000-6000-8000-{n:012d}"
    c["ts"] = ts.isoformat()
    c["channel_values"] = {"messages": messages}
    c["channel_versions"] = {"messages": n}
    return c


async def _seed_person_thread(cp, now: datetime) -> None:
    """An automation thread 40 days old in which the person wrote yesterday."""
    old = [HumanMessage(id="trigger-turn-a.b", content="mail content"), AIMessage(id="ai-1", content="summary")]
    cfg1 = await cp.aput(CFG, _cp(now - timedelta(days=40), old, 1), {}, {})
    mine = [*old, HumanMessage(id="p-1", content="PERSON-WROTE-YESTERDAY"), AIMessage(id="ai-2", content="ok")]
    await cp.aput(cfg1, _cp(now - timedelta(days=1), mine, 2), {}, {})


# -- HIGH: one failed trim turns the person's thread into a whole-thread delete --


def test_a_failed_trim_makes_the_next_sweep_delete_the_persons_thread(gateway) -> None:
    """Retention sweep #1 trims a person's automation thread; the trim's write
    fails ONCE (here "database is locked", which 4 workers sharing the
    checkpoint SQLite produce; the 60 s STEP_TIMEOUT on a large thread does the
    same). _delete_ledgered calls thread_failed -> pending_delete=1. Sweep #2
    then takes the "a delete that failed is finished whole" branch, with no
    trim_before, and delete_thread_everywhere removes what the person wrote."""
    from app.run_history.delete import sweep_threads

    client, _home = gateway
    app = client.app
    cp, history = app.state.checkpointer, app.state.run_history
    now = datetime.now(UTC)
    client.portal.call(_seed_person_thread, cp, now)
    with sqlite3.connect(history.db) as c:
        c.execute(
            "INSERT INTO automation_threads (thread_id, rule_id, first_seen) VALUES (?, ?, ?)",
            ("t-auto", "rule-gone", (now - timedelta(days=40)).isoformat()),
        )

    real_aput, calls = cp.aput, {"n": 0}

    async def locked_once(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise sqlite3.OperationalError("database is locked")
        return await real_aput(*a, **kw)

    cp.aput = locked_once
    first = client.portal.call(sweep_threads, app)
    assert "t-auto" in first.threads_failed  # transient failure, reported
    second = client.portal.call(sweep_threads, app)  # the next hourly sweep
    state = client.portal.call(cp.aget_tuple, CFG)
    texts = [m.content for m in state.checkpoint["channel_values"]["messages"]] if state else []
    assert "PERSON-WROTE-YESTERDAY" in texts, f"the person's thread was deleted whole by the retry: {second}"


# -- MEDIUM: trimmed content survives in SqliteSaver's pending writes ----------


@pytest.mark.xfail(strict=True, reason="filed as follow-up #70 (MEDIUM): trimmed content in SqliteSaver writes + free pages; not fixed in this PR")
@pytest.mark.asyncio
async def test_trim_leaves_old_mail_content_in_the_checkpointers_writes_table(tmp_path) -> None:
    """A real Pregel run on AsyncSqliteSaver (the user's backend) writes every
    node output to the `writes` table too. The trim rewrites checkpoints only,
    so the automation's mail content stays in checkpoints.db past retention,
    and is served back by aget_tuple/alist as pending_writes."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langgraph.graph import END, START, StateGraph

    from app.run_history.delete import trim_thread

    def reply(state: S) -> dict:
        last = state["messages"][-1].content
        return {"messages": [AIMessage(content=f"reply to {last}")]}

    g = StateGraph(S)
    g.add_node("agent", reply)
    g.add_edge(START, "agent")
    g.add_edge("agent", END)
    db = tmp_path / "checkpoints.sqlite"
    async with AsyncSqliteSaver.from_conn_string(str(db)) as cp:
        graph = g.compile(checkpointer=cp)
        await graph.ainvoke({"messages": [HumanMessage(id="trigger-turn-x.y", content="MAIL-BODY-SECRET-OLD")]}, CFG)
        time.sleep(0.05)
        cutoff = datetime.now(UTC)  # everything above is "past retention"
        time.sleep(0.05)
        await graph.ainvoke({"messages": [HumanMessage(content="person note")]}, CFG)
        app = SimpleNamespace(state=SimpleNamespace(checkpointer=cp, run_store=None, run_event_store=None))
        assert await trim_thread(app, "t-auto", cutoff)
        latest = await cp.aget_tuple(CFG)
        assert "MAIL-BODY-SECRET-OLD" not in str(latest.checkpoint["channel_values"])  # the trim did its part
    with sqlite3.connect(db) as c:
        rows = c.execute("SELECT value FROM writes").fetchall()
    leaked = [r for r in rows if b"MAIL-BODY-SECRET-OLD" in bytes(r[0])]
    assert not leaked, f"{len(leaked)} pending write(s) still hold the trimmed mail content"


# -- MEDIUM: the trim cuts between a tool call and its result ------------------


@pytest.mark.asyncio
async def test_trim_never_leaves_a_tool_result_without_its_tool_call(tmp_path) -> None:
    """The cutoff falls inside a tool call (the AI message is older than it, the
    tool's result newer). The AI message is removed, the ToolMessage kept: the
    thread now starts with a tool result no assistant asked for, which OpenAI
    and Anthropic reject (400) and DanglingToolCallMiddleware does not repair,
    so every turn the person sends fails until the next hourly sweep."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from app.run_history.delete import trim_thread

    now = datetime(2026, 3, 1, tzinfo=UTC)
    cutoff = now - timedelta(days=30)
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "cp.sqlite")) as cp:
        a = [HumanMessage(id="trigger-turn-a.b", content="check mail"), AIMessage(id="ai-1", content="", tool_calls=[{"id": "call-1", "name": "gmail_search", "args": {}}])]
        c1 = await cp.aput(CFG, _cp(cutoff - timedelta(seconds=20), a, 1), {}, {})
        b = [*a, ToolMessage(id="tm-1", content="mail list", tool_call_id="call-1")]
        c2 = await cp.aput(c1, _cp(cutoff + timedelta(seconds=20), b, 2), {}, {})
        c = [*b, AIMessage(id="ai-2", content="done"), HumanMessage(id="p-1", content="person note")]
        await cp.aput(c2, _cp(now - timedelta(days=1), c, 3), {}, {})
        app = SimpleNamespace(state=SimpleNamespace(checkpointer=cp, run_store=None, run_event_store=None))
        assert await trim_thread(app, "t-auto", cutoff)
        msgs = (await cp.aget_tuple(CFG)).checkpoint["channel_values"]["messages"]
    asked = {tc["id"] for m in msgs if isinstance(m, AIMessage) for tc in m.tool_calls}
    orphans = [m.tool_call_id for m in msgs if isinstance(m, ToolMessage) and m.tool_call_id not in asked]
    assert not orphans, f"tool result(s) left without their tool call: {orphans}"


# -- MEDIUM: the unlocked startup purge rotates under a record (check-then-act) --


def _worker(root, keys, now=None) -> RunHistory:
    return RunHistory(root, redact=lambda t: (t, True), key=StoreKey(keys / "run_store.key", forbidden=[]), now=now)


def test_startup_purge_rotation_check_then_act_loses_a_concurrent_record(tmp_path) -> None:
    """Worker B (just restarted: open_history purges WITHOUT the firing lock)
    expires the last run and checks has_recent_keys() -> False. Worker A (the
    engine) then writes its data key and blocks on B's open runs transaction.
    B rotates (DELETE FROM data_keys), commits; A's row commits with no key."""
    root, keys = tmp_path / "db", tmp_path / "keys"
    clock = {"now": datetime(2026, 1, 1, tzinfo=UTC)}
    a = _worker(root, keys, now=lambda: clock["now"])
    b = _worker(root, keys, now=lambda: clock["now"])
    a.record(kind="automation", source_id="r", status="completed", body={"messages": []})
    clock["now"] += timedelta(days=40)

    out: dict = {}
    real_recent = b.key.has_recent_keys

    def recent_then_a_records(within):
        verdict = real_recent(within)
        t = threading.Thread(target=lambda: out.setdefault("id", a.record(kind="automation", source_id="r", status="completed", body={"messages": [{"type": "tool", "content": "FRESH-RUN"}]})))
        t.start()
        out["t"] = t
        deadline = time.monotonic() + 5
        while len(a.key.key_ids()) == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        return verdict

    b.key.has_recent_keys = recent_then_a_records
    assert b.purge() == 1
    out["t"].join(15)
    assert a.get(out["id"])["body"] != {"withheld": UNREADABLE}, "a run recorded during another worker's startup purge is unreadable"
