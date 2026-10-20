"""The run history store's guarantees (app/run_history/store.py), each one
checked against what is actually on disk."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.run_history.store import INLINE_MAX, WITHHELD, RunHistory

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
