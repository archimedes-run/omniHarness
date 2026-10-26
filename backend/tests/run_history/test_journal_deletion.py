"""Run journals and run rows are deleted with what they belong to.

Journals now persist in the database (run_events.backend: auto). Every path
that deletes a thread or old runs must remove them too, whoever's user context
is current, including none at all: the retention purge and the startup sweep
run without a request, and the engine's worker has no user. Through
create_app() and its lifespan, the SQLite run and event stores.

The autouse user context (tests/conftest.py) is switched off here
(`no_auto_user`): it would hide a delete that only works with a user set.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

pytestmark = pytest.mark.no_auto_user

PERSON = "JOURNAL-CONTENT-4471"


def _seed(client, thread_id: str, *, run_user: str, created_at: str | None = None) -> str:
    """One run of `thread_id` and its journal, written as `run_user` (as the
    run worker writes them), then the user context is gone again."""
    from omniharness.runtime.user_context import reset_current_user, set_current_user

    app = client.app
    run_id = f"run-{thread_id[:8]}-{run_user}-{(created_at or 'now')[:10]}"

    async def write():
        token = set_current_user(type("U", (), {"id": run_user})())
        try:
            await app.state.run_store.put(run_id, thread_id=thread_id, user_id=run_user, status="success", created_at=created_at)
            await app.state.run_event_store.put_batch(
                [
                    {"thread_id": thread_id, "run_id": run_id, "event_type": "llm.human.input", "category": "message", "content": {"type": "human", "content": PERSON}},
                    {"thread_id": thread_id, "run_id": run_id, "event_type": "run.end", "category": "outputs", "content": ["done"]},
                ]
            )
        finally:
            reset_current_user(token)

    client.portal.call(write)
    return run_id


def _left(client, thread_id: str) -> tuple[int, int]:
    app = client.app

    async def read():
        rows = await app.state.run_store.list_by_thread(thread_id, user_id=None, limit=1000)
        n = 0
        for r in rows:
            n += len(await app.state.run_event_store.list_events(thread_id, r["run_id"], limit=1000, user_id=None))
        msgs = await app.state.run_event_store.list_messages(thread_id, limit=200, user_id=None)
        return len(rows), max(n, len(msgs))

    return client.portal.call(read)


def _thread(client) -> str:
    resp = client.post("/api/threads", json={})
    assert resp.status_code == 200, resp.text
    return resp.json()["thread_id"]


def test_deleting_a_thread_everywhere_with_no_user_context_removes_its_journal_and_runs(make_gateway) -> None:
    """The path the sweep and "Delete run history" take (delete_thread_everywhere),
    from a context with no user, for runs written by two different users."""
    from app.run_history.delete import delete_thread_everywhere

    with make_gateway() as (client, _home):
        tid = _thread(client)
        _seed(client, tid, run_user="system")
        _seed(client, tid, run_user="owner-x")
        assert _left(client, tid)[0] == 2 and _left(client, tid)[1] > 0
        client.portal.call(delete_thread_everywhere, client.app, tid)
        assert _left(client, tid) == (0, 0), "the thread's journal or runs survived its deletion"


def test_trimming_old_runs_with_no_user_context_removes_their_journal(make_gateway) -> None:
    """A thread a person wrote in recently is trimmed, not deleted: its runs
    older than the retention go, with their journal."""
    from test_review3_attacks_55 import _cp, _h

    from app.run_history.delete import trim_thread

    now = datetime.now(UTC)
    cutoff = now - timedelta(days=30)
    with make_gateway() as (client, _home):
        tid = "trim-thread-1"
        cp = client.app.state.checkpointer
        cfg = {"configurable": {"thread_id": tid, "checkpoint_ns": ""}}
        old = [{"type": "ai", "id": "ai-1", "content": "old reply"}]
        client.portal.call(cp.aput, cfg, _cp(now - timedelta(days=40), old, 1), {}, {})
        client.portal.call(cp.aput, cfg, _cp(now - timedelta(days=1), [*old, _h("p-1", "recent")], 2), {}, {})
        _seed(client, tid, run_user="system", created_at=(now - timedelta(days=60)).isoformat())
        assert client.portal.call(trim_thread, client.app, tid, cutoff) is True, "the thread was not trimmed; this test proves nothing"
        assert _left(client, tid) == (0, 0), "trimmed runs left their rows or journal behind"


def test_deleting_a_chat_removes_its_journal_and_runs(make_gateway) -> None:
    with make_gateway() as (client, _home):
        tid = _thread(client)
        _seed(client, tid, run_user="someone-else")  # e.g. written by an automation's user
        assert _left(client, tid)[0] == 1
        resp = client.delete(f"/api/threads/{tid}")
        assert resp.status_code == 200, resp.text
        assert _left(client, tid) == (0, 0), "deleting the chat left its messages in the run journal"
        # And a deleted thread lists no runs (it does not exist any more).
        assert client.get(f"/api/threads/{tid}/runs").status_code == 404
