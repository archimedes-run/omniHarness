"""Third adversarial review of PR #55 (run store). Fake values only; HOME and
the key dir are temp dirs (conftest + tmp_path).

Two "workers" = two RunHistory objects over the same data dir and key dir,
each with its OWN StoreKey and lock, exactly as 4 uvicorn workers each open
their own (app/run_history/lifespan.open_history). The trigger engine records
on one worker; every worker runs purge() at startup and hourly
(lifespan.purge_forever), without the cross-process firing lock.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.run_history.crypto import StoreKey
from app.run_history.store import UNREADABLE, RunHistory

MARKER = "MAIL-BODY-MARKER-review3"


def _worker(root, key_dir, now=None) -> RunHistory:
    return RunHistory(root, redact=lambda t: (t, True), key=StoreKey(key_dir / "run_store.key", forbidden=[]), now=now)


def _record(h: RunHistory, text: str, *, big: bool = False, **kw) -> str:
    body = {"messages": [{"type": "tool", "content": text + (" pad" * 20_000 if big else "")}]}
    return h.record(kind="automation", source_id="rule", status="completed", body=body, **kw)


# -- HIGH: a purge on another worker destroys the key of a run being recorded --


@pytest.mark.parametrize("big", [False, True])
def test_purge_on_another_worker_during_a_record_loses_that_run(tmp_path, big) -> None:
    """Worker A (engine) records; between its data key being written to the
    key store and its row committing, worker B's hourly purge runs. B sees the
    key but not the (uncommitted) row: `destroy(key_ids() - live)` shreds it."""
    root, keys = tmp_path / "db", tmp_path / "keys"
    engine_worker = _worker(root, keys)
    other_worker = _worker(root, keys)

    real_new = engine_worker.key.new_data_key

    def new_key_then_other_worker_purges(key_id):
        dek = real_new(key_id)
        other_worker.purge()  # hourly / startup purge on worker B, same instant
        return dek

    engine_worker.key.new_data_key = new_key_then_other_worker_purges
    run_id = _record(engine_worker, MARKER, big=big)

    got = engine_worker.get(run_id)
    assert got["body"] != {"withheld": UNREADABLE}, "a run recorded while another worker purged is permanently unreadable"
    assert MARKER in str(got["body"])


def test_purge_that_empties_the_store_rotates_under_a_concurrent_record(tmp_path) -> None:
    """Worker B's purge expires the last old run, sees no live row (A's is not
    committed) and ROTATES the master key: A's fresh run is lost too."""
    root, keys = tmp_path / "db", tmp_path / "keys"
    clock = {"now": datetime(2026, 1, 1, tzinfo=UTC)}
    engine_worker = _worker(root, keys, now=lambda: clock["now"])
    other_worker = _worker(root, keys, now=lambda: clock["now"])
    _record(engine_worker, "old run")  # stamped 2026-01-01
    clock["now"] += timedelta(days=40)

    real_new = engine_worker.key.new_data_key

    def new_key_then_other_worker_purges(key_id):
        dek = real_new(key_id)
        assert other_worker.purge() == 1
        return dek

    engine_worker.key.new_data_key = new_key_then_other_worker_purges
    run_id = _record(engine_worker, MARKER)
    assert engine_worker.get(run_id)["body"] != {"withheld": UNREADABLE}, "rotation by another worker's purge lost a just-recorded run"


# -- MEDIUM: trim (hourly, automatic) races a person's run on another worker ---


def _cp(ts: datetime, messages: list, n: int) -> dict:
    from langgraph.checkpoint.base import empty_checkpoint

    c = empty_checkpoint()
    c["id"] = f"1ef00000-0000-6000-8000-{n:012d}"
    c["ts"] = ts.isoformat()
    c["channel_values"] = {"messages": messages}
    c["channel_versions"] = {"messages": n}
    return c


def _h(mid, text):
    return {"type": "human", "id": mid, "content": text}


@pytest.mark.asyncio
async def test_trim_deletes_a_persons_message_committed_by_another_worker_during_it(tmp_path) -> None:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from app.run_history.delete import trim_thread

    now = datetime(2026, 3, 1, tzinfo=UTC)
    cutoff = now - timedelta(days=30)
    cfg = {"configurable": {"thread_id": "t1", "checkpoint_ns": ""}}
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "cp.sqlite")) as cp:
        old = [_h("trigger-turn-a.b", "mail content"), {"type": "ai", "id": "ai-1", "content": "summary"}]
        await cp.aput(cfg, _cp(now - timedelta(days=40), old, 1), {}, {})
        mine = [*old, _h("p-1", "my note"), {"type": "ai", "id": "ai-2", "content": "ok"}]
        await cp.aput(cfg, _cp(now - timedelta(days=2), mine, 2), {}, {})

        # ADAPTED (third-review fix): the trim no longer deletes the thread
        # (it rewrites checkpoints in place), so the race is injected where it
        # can still land: worker C commits after the trim reads the thread and
        # before its first write. Both the old hook point and this one are
        # covered: adelete_thread must never be called by the trim at all.
        real_aput, real_get = cp.aput, cp.aget_tuple
        state_reads = {"n": 0}

        async def never_delete(thread_id):
            raise AssertionError("trim must not delete the whole thread")

        async def person_commits_between_read_and_write(config):
            state_reads["n"] += 1
            if state_reads["n"] == 1:
                latest = [*mine, _h("p-2", "PERSON-NEWEST-MESSAGE"), {"type": "ai", "id": "ai-3", "content": "noted"}]
                await real_aput(cfg, _cp(now, latest, 3), {}, {})
            return await real_get(config)

        cp.adelete_thread = never_delete
        cp.aget_tuple = person_commits_between_read_and_write
        app = SimpleNamespace(state=SimpleNamespace(checkpointer=cp, run_store=None, run_event_store=None))
        assert await trim_thread(app, "t1", cutoff)
        cp.aget_tuple = real_get
        state = await cp.aget_tuple(cfg)
        texts = [m["content"] for m in state.checkpoint["channel_values"]["messages"]]
        assert "PERSON-NEWEST-MESSAGE" in texts, f"the person's newest message was lost by the trim: {texts}"


@pytest.mark.asyncio
async def test_trim_resets_message_ages_so_retention_is_extended(tmp_path) -> None:
    """After one trim the thread has one checkpoint stamped at its NEWEST
    message, so every kept message looks that new: the next trims keep
    content past the retention."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from app.run_history.delete import trim_thread

    day0 = datetime(2026, 1, 1, tzinfo=UTC)
    cfg = {"configurable": {"thread_id": "t1", "checkpoint_ns": ""}}
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "cp.sqlite")) as cp:
        a = [_h("trigger-turn-a.b", "old mail"), {"type": "ai", "id": "ai-0", "content": "x"}]
        await cp.aput(cfg, _cp(day0, a, 1), {}, {})
        b = [*a, _h("p-1", "day-20 note"), {"type": "ai", "id": "ai-1", "content": "MAIL-QUOTED-DAY-20"}]
        await cp.aput(cfg, _cp(day0 + timedelta(days=20), b, 2), {}, {})
        c = [*b, _h("p-2", "day-29 note")]
        await cp.aput(cfg, _cp(day0 + timedelta(days=29), c, 3), {}, {})
        app = SimpleNamespace(state=SimpleNamespace(checkpointer=cp, run_store=None, run_event_store=None))
        assert await trim_thread(app, "t1", day0 + timedelta(days=1))  # day 31
        assert await trim_thread(app, "t1", day0 + timedelta(days=21))  # day 51
        texts = [m["content"] for m in (await cp.aget_tuple(cfg)).checkpoint["channel_values"]["messages"]]
        assert "MAIL-QUOTED-DAY-20" not in texts, "day-20 content kept on day 51 (retention 30 days)"
