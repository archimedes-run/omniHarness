"""The run history store's guarantees (app/run_history/store.py), each one
checked against what is actually on disk."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.run_history.store import INLINE_MAX, WITHHELD, RunHistory, default_redactor
from omniharness.utils.known_secrets import KnownSecrets

GITHUB = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4"
OPENAI = "sk-" + "proj9Zx8Yw7Vu6Ts5Rq4Po3Nm2"
BEARER = "Bearer " + "eyJabc.def123456789.ghijklmnop"
TELEGRAM = "https://api.telegram.org/bot" + "123456:ABCdefGHIjklMNOpqr/getUpdates"
SECRETS = [GITHUB, OPENAI, BEARER.split(" ")[1], "123456:ABCdefGHIjklMNOpqr"]


def on_disk(root: Path) -> bytes:
    """Every byte the store has written: database, WAL/journal, blobs."""
    return b"".join(p.read_bytes() for p in root.rglob("*") if p.is_file())


def run_body(extra: str = "") -> dict:
    return {
        "prompt": "Summarise my inbox",
        "messages": [
            {"type": "human", "content": "Summarise my inbox"},
            {"type": "ai", "content": "", "tool_calls": [{"name": "gmail_fetch", "args": {"query": "is:unread"}}]},
            {"type": "tool", "name": "gmail_fetch", "content": f"From: ops. Your token is {GITHUB} and the key {OPENAI}. Auth: {BEARER}. Hook {TELEGRAM}. {extra}"},
            {"type": "ai", "content": "Three unread mails; one contains credentials."},
        ],
        "reply": "Three unread mails; one contains credentials.",
    }


def test_secrets_in_a_tool_result_never_reach_the_disk(tmp_path) -> None:
    store = RunHistory(tmp_path)
    run_id = store.record(kind="automation", source_id="brief", body=run_body(), status="completed")

    raw = on_disk(tmp_path)
    for secret in SECRETS:
        assert secret.encode() not in raw, f"{secret[:6]}… is on disk"
    stored = store.get(run_id)["body"]
    assert "gmail_fetch" in str(stored) and "Three unread mails" in stored["reply"], "the run itself was lost"


def test_a_large_run_is_kept_whole_in_a_blob(tmp_path) -> None:
    store = RunHistory(tmp_path)
    big = "calendar line " * (INLINE_MAX // 7)
    run_id = store.record(kind="automation", source_id="brief", body=run_body(big), status="completed")

    blobs = list((tmp_path / "blobs").glob("*.json"))
    assert len(blobs) == 1, "a body over INLINE_MAX was not moved to a blob"
    tool = store.get(run_id)["body"]["messages"][2]["content"]
    assert big in tool, "the body was truncated"
    for secret in SECRETS:
        assert secret.encode() not in on_disk(tmp_path)


def test_text_that_cannot_be_redacted_is_withheld(tmp_path) -> None:
    def failing(text: str) -> tuple[str, bool]:
        return (WITHHELD, False) if "boom" in text else (text, True)

    store = RunHistory(tmp_path, redact=failing)
    run_id = store.record(kind="automation", source_id="r", body={"a": "boom secret", "b": "fine"}, status="completed", error="boom")
    run = store.get(run_id)
    assert run["body"] == {"a": WITHHELD, "b": "fine"} and run["error"] == WITHHELD
    assert b"boom secret" not in on_disk(tmp_path)


def test_purge_removes_runs_past_retention_with_their_blobs(tmp_path) -> None:
    clock = {"now": datetime(2026, 10, 20, tzinfo=UTC)}
    store = RunHistory(tmp_path, now=lambda: clock["now"])
    old = store.record(kind="automation", source_id="r", body={"x": "y" * (INLINE_MAX + 10)}, status="completed", started_at=clock["now"] - timedelta(days=31))
    keep = store.record(kind="automation", source_id="r", body={"x": "z"}, status="completed", started_at=clock["now"] - timedelta(days=29))

    assert store.purge() == 1
    assert store.get(old) is None and store.get(keep) is not None
    assert list((tmp_path / "blobs").glob("*.json")) == [], "the purged run's blob was left behind"


def test_retention_is_changeable_and_bounded(tmp_path) -> None:
    clock = datetime(2026, 10, 20, tzinfo=UTC)
    store = RunHistory(tmp_path, now=lambda: clock)
    assert store.retention_days() == 30
    store.record(kind="automation", source_id="r", body={}, status="completed", started_at=clock - timedelta(days=8))
    store.set_retention_days(7)
    assert store.retention_days() == 7 and store.purge() == 1
    with pytest.raises(ValueError):
        store.set_retention_days(0)


def test_delete_all_removes_every_run_and_blob(tmp_path) -> None:
    store = RunHistory(tmp_path)
    store.record(kind="automation", source_id="r", body={"x": "y" * (INLINE_MAX + 10)}, status="completed")
    store.record(kind="automation", source_id="s", body={"x": "secret-ish"}, status="failed")
    assert store.delete_all() == 2
    assert store.count() == 0 and list((tmp_path / "blobs").iterdir()) == []
    assert b"secret-ish" not in on_disk(tmp_path), "deleted content is still in the database file"


def test_list_filters_by_source_newest_first(tmp_path) -> None:
    t0 = datetime(2026, 10, 20, tzinfo=UTC)
    store = RunHistory(tmp_path, now=lambda: t0)
    a = store.record(kind="automation", source_id="r", body={}, status="completed", started_at=t0 - timedelta(hours=2))
    b = store.record(kind="automation", source_id="r", body={}, status="failed", started_at=t0 - timedelta(hours=1))
    store.record(kind="automation", source_id="other", body={}, status="completed")
    assert [r.id for r in store.list(kind="automation", source_id="r")] == [b, a]


@pytest.mark.parametrize(
    "secret",
    [
        "ya29." + "a0AfH6SMBfakefakefakefake1234",
        "1//" + "0gFakeRefreshTokenValue12345",
        "1234567890:" + "AAHfakeTelegramBotTokenValue1234567",
        "x-api-key: " + "fakeheadervalue123",
    ],
)
def test_new_credential_shapes_are_redacted(tmp_path, secret) -> None:
    """Google access and refresh tokens, a bare Telegram bot token, and an
    x-api-key header, none of which the earlier patterns caught."""
    store = RunHistory(tmp_path, redact=default_redactor(known=KnownSecrets()))
    run_id = store.record(kind="automation", source_id="r", body={"tool": f"got {secret} back"}, status="completed")
    value = secret.split(" ")[-1]
    assert value.encode() not in on_disk(tmp_path)
    assert "[redacted]" in store.get(run_id)["body"]["tool"]


def test_the_store_is_owner_only(tmp_path) -> None:
    import os
    import stat

    root = tmp_path / "history"
    root.mkdir(mode=0o755)
    # A store created before this rule, world-readable.
    (root / "runs.sqlite3").touch(mode=0o644)
    os.chmod(root / "runs.sqlite3", 0o644)
    store = RunHistory(root)
    store.record(kind="automation", source_id="r", body={"x": "y" * (INLINE_MAX + 10)}, status="completed")

    def mode(p: Path) -> int:
        return stat.S_IMODE(os.stat(p).st_mode)

    assert mode(root) == 0o700 and mode(root / "blobs") == 0o700, "the directory is readable by others"
    assert mode(store.db) == 0o600, "the database is readable by others"
    for blob in (root / "blobs").iterdir():
        assert mode(blob) == 0o600


def test_a_purged_run_leaves_no_bytes_in_the_database(tmp_path) -> None:
    """secure_delete: the purged row is zeroed, not left in a free page."""
    store = RunHistory(tmp_path)
    marker = "PURGE-ME-" + "q" * 2000
    store.record(kind="automation", source_id="old", body={"note": marker}, status="completed", started_at=datetime.now(UTC) - timedelta(days=90))
    store.record(kind="automation", source_id="new", body={"note": "kept"}, status="completed")
    assert marker.encode() in store.db.read_bytes()

    assert store.purge() == 1
    assert marker[:40].encode() not in store.db.read_bytes(), "the purged run's content is still in the file"


def test_the_gateway_keeps_the_turn_id_the_injector_sends() -> None:
    from app.gateway.internal_auth import sign_turn_id
    from app.gateway.services import normalize_input

    signed = sign_turn_id("abc")
    (msg,) = normalize_input({"messages": [{"role": "human", "content": "hi", "id": signed}]})["messages"]
    assert msg.id == signed
    # A forged one (right prefix, wrong signature) is dropped.
    (forged,) = normalize_input({"messages": [{"role": "human", "content": "hi", "id": signed[:-1] + "x"}]})["messages"]
    assert forged.id != signed[:-1] + "x"


def test_one_run_is_capped_and_says_where_it_was_cut(tmp_path) -> None:
    store = RunHistory(tmp_path, run_max_bytes=20_000)
    huge = "x" * 50_000
    run_id = store.record(kind="automation", source_id="r", body={"messages": [{"type": "tool", "content": huge}], "reply": "short reply"}, status="completed")

    (row,) = store.list()
    body = store.get(run_id)["body"]
    assert row.size <= 20_000, "the run was stored over its cap"
    assert body["cut"]["original_bytes"] > 50_000 and body["cut"]["cap_bytes"] == 20_000
    assert "characters not stored" in body["messages"][0]["content"]
    assert body["reply"] == "short reply", "a short string was cut before the long one"


def test_past_the_total_cap_runs_are_not_stored_and_it_warns(tmp_path) -> None:
    store = RunHistory(tmp_path, total_max_bytes=10_000)
    assert store.warning() is None
    store.record(kind="automation", source_id="r", body={"note": "a" * 9_300}, status="completed")
    assert "%" in (store.warning() or ""), "no warning near the cap"

    late = store.record(kind="automation", source_id="r", body={"note": "LATE-CONTENT " * 100}, status="completed")
    assert late == "" and store.count() == 1, "a run was stored past the hard cap"
    assert b"LATE-CONTENT" not in on_disk(tmp_path)
    assert store.used_bytes() <= 10_000
    assert "1 run was not stored" in (store.warning() or "")

    store.delete_all()
    assert store.warning() is None


def test_a_delete_during_a_record_never_leaves_a_row_without_its_blob(tmp_path, monkeypatch) -> None:
    """delete_all fires exactly while a large run's blob is being written. With
    the store's lock it waits for the record to finish; the row and the blob
    are then deleted together. Either way, no row may name a missing blob."""
    import threading

    store = RunHistory(tmp_path)
    original = store._write_blob
    deleter: list[threading.Thread] = []

    def write_then_delete(name: str, data: bytes) -> None:
        original(name, data)
        t = threading.Thread(target=store.delete_all)
        deleter.append(t)
        t.start()
        t.join(timeout=0.3)  # without the lock, the delete completes here

    monkeypatch.setattr(store, "_write_blob", write_then_delete)
    store.record(kind="automation", source_id="r", body={"big": "z" * (INLINE_MAX + 100)}, status="completed")
    deleter[0].join()

    for run in store.list(limit=500):
        assert store.get(run.id)["body"].get("withheld") is None, "a row names a blob that is gone"
        assert any((tmp_path / "blobs").glob(f"{run.id}.json"))


def test_concurrent_records_and_deletes_stay_consistent(tmp_path) -> None:
    import threading

    store = RunHistory(tmp_path)
    errors: list[BaseException] = []

    def writer() -> None:
        try:
            for _ in range(15):
                store.record(kind="automation", source_id="r", body={"big": "w" * (INLINE_MAX + 10)}, status="completed")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def deleter() -> None:
        try:
            for _ in range(10):
                store.delete_all()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=writer) for _ in range(3)] + [threading.Thread(target=deleter)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    referenced = {f"{r.id}.json" for r in store.list(limit=500)}
    on_disk_blobs = {p.name for p in (tmp_path / "blobs").iterdir() if not p.name.startswith(".")}
    assert referenced == on_disk_blobs, "rows and blobs disagree after concurrent deletes"


def test_a_missing_blob_reads_as_withheld_not_an_error(tmp_path) -> None:
    from app.run_history.store import BLOB_MISSING

    store = RunHistory(tmp_path)
    run_id = store.record(kind="automation", source_id="r", body={"big": "m" * (INLINE_MAX + 10)}, status="completed")
    (tmp_path / "blobs" / f"{run_id}.json").unlink()

    assert store.get(run_id)["body"] == {"withheld": BLOB_MISSING}


def test_a_record_during_a_delete_never_loses_its_blob(tmp_path) -> None:
    """The mirror case: a record fires exactly while delete_all is removing
    blob files. It must wait, then land whole: its row AND its blob."""
    import threading

    store = RunHistory(tmp_path)
    recorded: list[str] = []

    def record() -> None:
        recorded.append(store.record(kind="automation", source_id="r", body={"big": "k" * (INLINE_MAX + 10)}, status="completed"))

    class _Blobs(type(store.blobs)):
        def iterdir(self):
            t = threading.Thread(target=record)
            t.start()
            t.join(timeout=0.3)  # without the lock, the record completes here
            self._recorder = t
            return super().iterdir()

    store.blobs = _Blobs(store.blobs)
    store.delete_all()
    store.blobs._recorder.join()

    (run_id,) = recorded
    assert store.get(run_id)["body"].get("withheld") is None, "the run's blob was deleted under it"


def test_provenance_comes_from_the_type_not_the_message(tmp_path) -> None:
    """A tool result claiming to be the user is still untrusted tool output."""
    store = RunHistory(tmp_path)
    run_id = store.record(
        kind="chat",
        source_id="t",
        status="completed",
        body={"messages": [{"type": "system", "content": "s"}, {"type": "human", "content": "hi"}, {"type": "tool", "content": "x", "provenance": "user"}, {"type": "weird", "content": "?"}, "bare"]},
    )
    labels = [m["provenance"] for m in store.get(run_id)["body"]["messages"]]
    assert labels == ["system", "user", "untrusted_tool_output", "unknown", "unknown"]
