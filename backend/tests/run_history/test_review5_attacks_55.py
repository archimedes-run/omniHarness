"""Fifth adversarial review of PR #55 (run store). Fake values only; HOME and
the key dir are temp dirs (conftest + tmp_path). Each test FAILS on 5e2ce2e
while its finding stands."""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime, timedelta

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.run_history.crypto import StoreKey
from app.run_history.store import RunHistory

CFG = {"configurable": {"thread_id": "t-auto", "checkpoint_ns": ""}}

# The ledger as cc9bb00 (an earlier build of this same PR) created it.
_OLD_LEDGER = """
CREATE TABLE automation_threads (
    thread_id TEXT PRIMARY KEY, rule_id TEXT, first_seen TEXT NOT NULL,
    pending_delete INTEGER NOT NULL DEFAULT 0, last_error TEXT
);
"""


def _cp(ts: datetime, messages: list, n: int) -> dict:
    from langgraph.checkpoint.base import empty_checkpoint

    c = empty_checkpoint()
    c["id"] = f"1ef00000-0000-6000-8000-{n:012d}"
    c["ts"] = ts.isoformat()
    c["channel_values"] = {"messages": messages}
    c["channel_versions"] = {"messages": n}
    return c


def _old_store(root) -> None:
    root.mkdir(parents=True)
    with sqlite3.connect(root / "runs.sqlite3") as c:
        c.executescript(_OLD_LEDGER)
        c.execute("INSERT INTO automation_threads (thread_id, rule_id, first_seen, pending_delete) VALUES ('t-x', 'r', '2026-01-01T00:00:00+00:00', 1)")


# -- MEDIUM: the column migration races across the 4 workers' startups ---------


def test_four_workers_migrating_an_existing_ledger_all_open(tmp_path, monkeypatch) -> None:
    """uvicorn --workers 4 runs every lifespan at once. Each RunHistory reads
    PRAGMA table_info(automation_threads), sees no delete_reason, and ALTERs:
    check-then-act with no lock. The loser gets "duplicate column name", its
    RunHistory raises, lifespan sets run_history=None on that worker: its
    routes 503, and if it is the engine's worker, note_thread/record_run are
    None, so its automation threads never enter the ledger (delete-all and
    retention never reach them) and engine turn ids are dropped."""
    root, keys = tmp_path / "db", tmp_path / "keys"
    _old_store(root)
    barrier = threading.Barrier(2, timeout=5)
    real_connect = RunHistory._connect

    class Conn:
        def __init__(self, c):
            self._c = c

        def execute(self, sql, *a):
            cur = self._c.execute(sql, *a)
            if sql.startswith("PRAGMA table_info(automation_threads)"):
                rows = cur.fetchall()
                try:
                    barrier.wait()  # both workers have read the old columns
                except threading.BrokenBarrierError:
                    pass
                return iter(rows)
            return cur

        def __getattr__(self, name):
            return getattr(self._c, name)

        def __enter__(self):
            self._c.__enter__()
            return self

        def __exit__(self, *exc):
            return self._c.__exit__(*exc)

    monkeypatch.setattr(RunHistory, "_connect", lambda self: Conn(real_connect(self)))
    errors: list[BaseException] = []

    def start_worker():
        try:
            RunHistory(root, redact=lambda t: (t, True), key=StoreKey(keys / "run_store.key", forbidden=[]))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    ts = [threading.Thread(target=start_worker) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(15)
    assert not errors, f"a worker's run history failed to open during the migration: {errors!r}"


# -- LOW: the migration downgrades an explicit pending delete to retention ------


@pytest.mark.xfail(strict=True, reason="filed as follow-up #78 (LOW): migration leaves an older explicit pending delete without delete_reason")
def test_an_explicit_pending_delete_from_before_the_migration_stays_explicit(tmp_path) -> None:
    """On cc9bb00, pending_delete=1 was only ever set by "Delete run history"
    (mark_threads_pending) or a failed delete. After the ALTER its
    delete_reason is NULL, so explicit_deletes() misses it and the sweep takes
    the trim path: a thread the person asked to delete, in which they wrote
    within the window, is kept (trimmed) instead of deleted."""
    root = tmp_path / "db"
    _old_store(root)
    h = RunHistory(root, redact=lambda t: (t, True), key=StoreKey(tmp_path / "keys" / "run_store.key", forbidden=[]))
    assert "t-x" in h.explicit_deletes(), "a pre-migration pending delete lost its explicit intent"


# -- MEDIUM: the retention whole-delete has no re-check against other workers ---


async def _seed_engine_only_thread(cp, now: datetime) -> dict:
    """An automation thread 40 days old: only the engine's turns, no person."""
    old = [HumanMessage(id="trigger-turn-a.b", content="mail content"), AIMessage(id="ai-1", content="summary")]
    return await cp.aput(CFG, _cp(now - timedelta(days=40), old, 1), {}, {})


@pytest.mark.xfail(strict=True, reason="filed as follow-up #77 (MEDIUM): retention whole-delete can erase a person's turn committed on another worker")
def test_retention_delete_wipes_a_persons_turn_committed_on_another_worker(gateway) -> None:
    """Hourly sweep on worker A: trim_thread reads the thread, finds no
    person's message, returns False, and _delete_ledgered deletes the thread
    whole. _busy() only asks THIS worker's in-memory RunManager, so the
    person's run on worker B (they opened the digest thread and asked a
    question) is invisible. B's run commits its checkpoints after the trim's
    read and finishes before adelete_thread: delete_thread_everywhere's
    post-delete re-check sees nothing, the thread is REPORTED deleted, and the
    person's question and its answer are gone. (Same class review 3 graded
    MEDIUM for the trim; this is the delete path, which still has it.)"""
    from app.run_history.delete import sweep_threads

    client, _home = gateway
    app = client.app
    cp, history = app.state.checkpointer, app.state.run_history
    now = datetime.now(UTC)
    parent = client.portal.call(_seed_engine_only_thread, cp, now)
    with sqlite3.connect(history.db) as c:
        c.execute("INSERT INTO automation_threads (thread_id, rule_id, first_seen) VALUES (?, ?, ?)", ("t-auto", "rule-gone", (now - timedelta(days=40)).isoformat()))

    real_delete = cp.adelete_thread

    async def worker_b_run_lands_first(thread_id):
        msgs = [
            HumanMessage(id="trigger-turn-a.b", content="mail content"),
            AIMessage(id="ai-1", content="summary"),
            HumanMessage(id="p-1", content="PERSON-QUESTION-JUST-NOW"),
            AIMessage(id="ai-2", content="answer"),
        ]
        await cp.aput(parent, _cp(now, msgs, 2), {}, {})  # worker B's run, completed
        await real_delete(thread_id)

    cp.adelete_thread = worker_b_run_lands_first
    result = client.portal.call(sweep_threads, app)
    cp.adelete_thread = real_delete
    state = client.portal.call(cp.aget_tuple, CFG)
    texts = [m.content for m in state.checkpoint["channel_values"]["messages"]] if state else []
    assert "PERSON-QUESTION-JUST-NOW" in texts or "t-auto" not in result.threads_deleted, f"the person's just-written turn was deleted and reported deleted: {result}"


# -- MEDIUM (HIGH if a 2nd data dir ever runs): one key store, many run DBs ------


def test_a_second_data_dir_sharing_the_key_dir_does_not_destroy_this_history(tmp_path) -> None:
    """The key dir is per-USER (~/.omni-harness-secrets, also what both compose
    files mount), the run DB per DATA DIR (each checkout's
    backend/.omni-harness, or a custom OMNI_HARNESS_HOME). purge() destroys
    every key older than KEY_GRACE whose id is not a row in ITS OWN runs table,
    so any second gateway (another worktree's `make dev`, a second
    OMNI_HARNESS_HOME) shreds this history's keys at its startup purge: every
    stored run here becomes permanently UNREADABLE. The key store has no notion
    of which run DB a key belongs to."""
    keys = tmp_path / "secrets"
    a = RunHistory(tmp_path / "checkout-a" / "run-history", redact=lambda t: (t, True), key=StoreKey(keys / "run_store.key", forbidden=[]))
    run_id = a.record(kind="automation", source_id="r", status="completed", body={"messages": [{"type": "tool", "content": "MAIL-A"}]})
    with sqlite3.connect(keys / "run_store_keys.sqlite3") as c:  # the run is an hour old
        c.execute("UPDATE data_keys SET created = created - 3600")
    b = RunHistory(tmp_path / "checkout-b" / "run-history", redact=lambda t: (t, True), key=StoreKey(keys / "run_store.key", forbidden=[]))
    b.purge()  # open_history() does this at every startup, then hourly
    assert "MAIL-A" in str(a.get(run_id)["body"]), f"another data dir's purge made this run unreadable: {a.get(run_id)['body']}"
