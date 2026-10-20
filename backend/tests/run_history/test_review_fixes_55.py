"""Fixes for the PR #55 review beyond the reviewer's own attacks
(test_review_attacks_55.py): the ledger of automation threads, the startup
sweep, the concurrent-human label, the internal token, stale temp blobs, and
the short-secret floor that must not become a redaction storm. Fake values."""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime

import pytest

from app.run_history.store import RunHistory, default_redactor
from omniharness.utils.known_secrets import KNOWN_SECRETS, register_secret

CONTENT = "AUTOMATION-THREAD-CONTENT-FIX-55"


def _content(client, tid) -> bool:
    cp = client.app.state.checkpointer
    tup = client.portal.call(lambda: cp.aget_tuple({"configurable": {"thread_id": tid, "checkpoint_ns": ""}}))
    return tup is not None and CONTENT in json.dumps(tup.checkpoint, default=str)


def _tweak(state):
    def tweak(config):
        config["trigger_engine"] = {"enabled": False, "state_dir": str(state)}

    return tweak


def _thread(client, text=CONTENT) -> str:
    tid = client.post("/api/threads", json={"metadata": {}}).json()["thread_id"]
    assert client.post(f"/api/threads/{tid}/state", json={"values": {"messages": [{"type": "human", "content": text}]}}).status_code == 200
    return tid


def test_a_map_entry_the_engine_did_not_create_is_never_deleted(make_gateway, tmp_path) -> None:
    """A tampered rule map pointing at a person's chat: the chat survives, the
    rule forgets it, and the response names it."""
    state = tmp_path / "triggers"
    with make_gateway(_tweak(state)) as (client, _):
        chat = _thread(client, f"{CONTENT} my own chat")
        state.mkdir(parents=True, exist_ok=True)
        (state / "threads.json").write_text(json.dumps({"inbox": chat}))
        resp = client.delete("/api/run-history/runs", params={"confirm": "delete-all"}).json()
        assert chat in resp["threads_failed"] and resp["threads_deleted"] == 0
        assert _content(client, chat), "a thread the engine never created was deleted"
        assert json.loads((state / "threads.json").read_text()) == {}, "the rule still points at a foreign thread"


def test_the_startup_sweep_finishes_a_failed_delete(make_gateway, tmp_path) -> None:
    state = tmp_path / "triggers"
    with make_gateway(_tweak(state)) as (client, _):
        tid = _thread(client)
        history = client.app.state.run_history
        history.note_thread(tid, "inbox")
        history.thread_failed(tid, "OSError")  # an earlier delete failed
        state.mkdir(parents=True, exist_ok=True)
        (state / "threads.json").write_text(json.dumps({"inbox": tid}))
    with make_gateway(_tweak(state)) as (client, _):
        assert not _content(client, tid), "the pending delete was not retried at startup"
        assert tid not in client.app.state.run_history.ledger_threads()


def test_the_engine_notes_each_thread_it_creates(tmp_path) -> None:
    from types import SimpleNamespace

    from app.gateway.trigger_engine_wiring import build_production_loop
    from omniharness.config.extensions_config import reset_extensions_config

    ext = tmp_path / "ext.json"
    ext.write_text('{"mcpServers": {}, "skills": {}}')
    os.environ["OMNI_HARNESS_EXTENSIONS_CONFIG_PATH"] = str(ext)
    reset_extensions_config()
    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps({"rules": []}))
    cfg = SimpleNamespace(trigger_engine=SimpleNamespace(rules_path=str(rules), state_dir=str(tmp_path / "state"), actor="default", tick_seconds=30.0, remote=None), channels={})
    history = RunHistory(tmp_path / "h", redact=lambda t: (t, True))

    import asyncio

    async def build():
        return build_production_loop(cfg, run_store=None, run_history=history)

    loop = asyncio.run(build())
    loop.threads.create_thread = lambda rule: "t-new"
    assert loop.threads.thread_for("inbox") == "t-new"
    assert "t-new" in history.ledger_threads(), "the engine created a thread the ledger does not know"
    os.environ.pop("OMNI_HARNESS_EXTENSIONS_CONFIG_PATH", None)
    reset_extensions_config()


def test_a_person_writing_during_a_firing_is_labelled_concurrent(tmp_path) -> None:
    from app.run_history.recorder import automation_recorder

    h = RunHistory(tmp_path / "h", redact=lambda t: (t, True))
    automation_recorder(h)({"rule_id": "r", "body": {"prompt": "p", "prompt_template": "p", "messages": [{"type": "human", "content": "p"}, {"type": "human", "content": "me, mid-run"}, {"type": "ai", "content": "ok"}]}})
    (run,) = h.list()
    labels = [m["provenance"] for m in h.get(run.id)["body"]["messages"]]
    assert labels == ["trigger", "user_concurrent", "assistant"]


def test_the_internal_auth_token_is_a_known_secret(gateway) -> None:
    from app.gateway import internal_auth

    out, n = KNOWN_SECRETS.redact(f"x {internal_auth._INTERNAL_AUTH_TOKEN} y")
    assert n >= 1 and internal_auth._INTERNAL_AUTH_TOKEN not in out


def test_a_stale_temp_blob_is_removed_on_open(tmp_path) -> None:
    root = tmp_path / "h"
    RunHistory(root, redact=lambda t: (t, True))
    stale = root / "blobs" / ".abc.tmp"
    stale.write_text("HALF-WRITTEN-CONTENT")
    old = time.time() - 7200
    os.utime(stale, (old, old))
    RunHistory(root, redact=lambda t: (t, True))
    assert not stale.exists()


@pytest.mark.parametrize(
    "text,redacted",
    [("your PIN is 483920.", True), ("order 2483920 shipped", False), ("ref 4839201", False)],
)
def test_a_short_known_secret_matches_only_as_a_whole_word(tmp_path, text, redacted) -> None:
    register_secret("483920", "test")
    h = RunHistory(tmp_path / "h", redact=default_redactor())
    rid = h.record(kind="a", source_id="r", status="completed", body={"t": text})
    assert ("483920" not in h.get(rid)["body"]["t"]) is redacted


def test_runs_are_stored_in_utc(tmp_path) -> None:
    from datetime import timedelta, timezone

    h = RunHistory(tmp_path / "h", redact=lambda t: (t, True))
    rid = h.record(kind="a", source_id="r", status="completed", body={}, started_at=datetime(2026, 1, 1, 2, 0, tzinfo=timezone(timedelta(hours=-10))))
    assert h.get(rid)["started_at"] == datetime(2026, 1, 1, 12, 0, tzinfo=UTC).isoformat()


def test_withheld_keys_stay_distinct(tmp_path) -> None:
    """Redaction failing on every key must not collapse them into one key and
    silently drop values."""
    h = RunHistory(tmp_path / "h", redact=lambda t: ("[Withheld: could not be redacted]", False))
    rid = h.record(kind="a", source_id="r", status="completed", body={"a": 1, "b": 2, "c": 3})
    assert len(h.get(rid)["body"]) == 3


def test_retention_itself_deletes_an_orphaned_automation_thread(make_gateway, tmp_path) -> None:
    """No 'Delete run history' needed: purging a deleted rule's last run also
    deletes its thread. A live rule's thread is kept."""
    from datetime import timedelta

    state = tmp_path / "triggers"
    with make_gateway(_tweak(state)) as (client, _):
        gone, live = _thread(client), _thread(client)
        state.mkdir(parents=True, exist_ok=True)
        (state / "threads.json").write_text(json.dumps({"live-rule": live}))
        old = datetime.now(UTC) - timedelta(days=40)
        h = client.app.state.run_history
        h.record(kind="automation", source_id="deleted-rule", thread_id=gone, body={}, status="completed", started_at=old)
        h.record(kind="automation", source_id="live-rule", thread_id=live, body={}, status="completed", started_at=datetime.now(UTC) - timedelta(days=5))

        assert client.put("/api/run-history/settings", json={"retention_days": 30}).status_code == 200

        assert not _content(client, gone), "retention left the deleted rule's thread content behind"
        assert _content(client, live), "retention deleted a live rule's thread"


def test_a_long_error_is_cut_even_with_room_to_spare(tmp_path) -> None:
    from app.run_history.store import ERROR_MAX

    h = RunHistory(tmp_path / "h", redact=lambda t: (t, True))
    rid = h.record(kind="a", source_id="r", status="failed", body={}, error="E" * 1_000_000)
    assert len(h.get(rid)["error"]) < ERROR_MAX + 100


def test_a_numeric_secret_in_yaml_is_registered(tmp_path) -> None:
    from omniharness.utils import known_secrets

    cfg = tmp_path / "c.yaml"
    cfg.write_text("bank:\n  pin: 48392017\n  session_timeout: 3600\n")
    found = known_secrets.yaml_secrets(cfg)
    assert "48392017" in found and "3600" not in found


def test_purge_compares_times_for_rows_stored_with_an_offset(tmp_path) -> None:
    """A row written by an older version, stamped -10:00, 29 days 23 hours ago:
    inside retention, so not purged (as strings it sorts as older)."""
    import sqlite3
    from datetime import timedelta, timezone

    now = datetime(2026, 10, 20, 0, 30, tzinfo=UTC)
    h = RunHistory(tmp_path / "h", redact=lambda t: (t, True), now=lambda: now)
    started = (now - timedelta(days=29, hours=23)).astimezone(timezone(timedelta(hours=-10))).isoformat()
    with sqlite3.connect(h.db) as c:
        c.execute("INSERT INTO runs (id, kind, source_id, started_at, status, size, body) VALUES ('x', 'a', 'r', ?, 'completed', 2, '{}')", (started,))
    assert h.purge() == 0


@pytest.mark.asyncio
async def test_retention_rotates_a_live_rules_thread_and_the_rule_still_fires(make_gateway, tmp_path) -> None:
    """A live monthly rule's thread holds a 40-day-old firing: after the purge
    its content is gone from the thread, and the rule's next firing runs in a
    fresh thread."""
    import asyncio
    import sqlite3
    from datetime import timedelta
    from types import SimpleNamespace

    from app.gateway.trigger_engine_wiring import build_loop

    state = tmp_path / "triggers"
    with make_gateway(_tweak(state)) as (client, _):
        old_thread = _thread(client)
        state.mkdir(parents=True, exist_ok=True)
        (state / "threads.json").write_text(json.dumps({"monthly": old_thread}))
        h = client.app.state.run_history
        old = datetime.now(UTC) - timedelta(days=40)
        h.record(kind="automation", source_id="monthly", thread_id=old_thread, body={}, status="completed", started_at=old)
        with sqlite3.connect(h.db) as c:
            c.execute("UPDATE automation_threads SET first_seen = ?", (old.isoformat(),))

        assert client.put("/api/run-history/settings", json={"retention_days": 30}).status_code == 200
        assert not _content(client, old_thread), "a live rule's thread still holds content past the retention"

    created: list[str] = []

    class GW:
        def post(self, path, body):
            if path == "/api/threads":
                created.append("t-fresh")
                return {"thread_id": "t-fresh"}
            m = body["input"]["messages"][0]
            return {"messages": [{"type": "human", "content": m["content"], "id": m["id"]}, {"type": "ai", "content": "fired"}]}

        def put(self, path, body):
            return {}

        def get(self, path):
            return {"status": "idle"}

    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps({"quiet_hours": {"enabled": False}, "rules": [{"id": "monthly", "type": "cron", "match": {"schedule": "* * * * *"}, "prompt": "p", "destination": "quiet"}]}))
    cfg = SimpleNamespace(trigger_engine=SimpleNamespace(rules_path=str(rules), state_dir=str(state), actor="default", tick_seconds=30.0))
    gw = GW()
    loop = build_loop(cfg, gateway_post=gw.post, gateway_put=gw.put, gateway_get=gw.get, fetch_sessions=lambda: {"observable": True, "sessions": []}, exchange_state=lambda t: {"status": "idle"}, remote=None)
    await loop.cycle()
    await asyncio.sleep(0)
    assert created == ["t-fresh"] and loop.threads.thread_of("monthly") == "t-fresh", "the rule did not fire into a fresh thread"


def test_a_purged_run_ages_its_live_thread_so_it_rotates(make_gateway, tmp_path) -> None:
    """No hand-set ledger time: a live rule's only run is 40 days old; the purge
    removes it and the thread, which held that content, is rotated out."""
    from datetime import timedelta

    state = tmp_path / "triggers"
    with make_gateway(_tweak(state)) as (client, _):
        tid = _thread(client)
        state.mkdir(parents=True, exist_ok=True)
        (state / "threads.json").write_text(json.dumps({"monthly": tid}))
        client.app.state.run_history.record(kind="automation", source_id="monthly", thread_id=tid, body={}, status="completed", started_at=datetime.now(UTC) - timedelta(days=40))
        assert client.put("/api/run-history/settings", json={"retention_days": 30}).status_code == 200
        assert not _content(client, tid)
        assert json.loads((state / "threads.json").read_text()) == {}
