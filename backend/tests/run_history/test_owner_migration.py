"""#133's startup migration on temporary directories: automation threads'
files move from the system user to the owner, safely.

Through a real gateway restart: tests/studio/test_lead_automations_owner.py.
Here, the move itself: what moves, what never moves, idempotency, collisions,
a partial failure, and the dry run. Every path is under pytest's tmp_path.
"""

from __future__ import annotations

import json
import os

import pytest

from app.run_history.owner_migration import CONFLICT, FAILED, MOVED, SKIPPED, WOULD_MOVE, move_threads_to_owner, write_report
from omniharness.config.paths import Paths

OWNER = "owner-1"
SYSTEM = "default"
A, B, C = "aaaaaaaa-0000-0000-0000-000000000001", "bbbbbbbb-0000-0000-0000-000000000002", "cccccccc-0000-0000-0000-000000000003"


@pytest.fixture
def paths(tmp_path) -> Paths:
    return Paths(base_dir=tmp_path)


def _seed(paths: Paths, tid: str, user: str = SYSTEM, text: str = "report") -> None:
    out = paths.sandbox_outputs_dir(tid, user_id=user)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.md").write_text(text)


def _read(paths: Paths, tid: str, user: str) -> str | None:
    f = paths.sandbox_outputs_dir(tid, user_id=user) / "report.md"
    return f.read_text() if f.exists() else None


def _all_system(_tid: str) -> bool:
    return True


def _run(paths, ids, **kw):
    return {e.thread_id: e for e in move_threads_to_owner(paths, ids, owner=OWNER, is_system_thread=kw.pop("is_system", _all_system), **kw)}


def test_an_automation_threads_files_move_to_the_owner(paths) -> None:
    _seed(paths, A, text="alpha")
    report = _run(paths, [A])
    assert report[A].action == MOVED
    assert _read(paths, A, OWNER) == "alpha"
    assert not paths.thread_dir(A, user_id=SYSTEM).exists()


def test_a_rerun_does_nothing(paths) -> None:
    _seed(paths, A, text="alpha")
    _run(paths, [A])
    assert _run(paths, [A]) == {}, "a second run reported a thread again"
    assert _read(paths, A, OWNER) == "alpha"


def test_an_existing_owner_thread_is_never_overwritten_and_both_copies_stay(paths) -> None:
    _seed(paths, A, user=SYSTEM, text="old")
    _seed(paths, A, user=OWNER, text="new")
    report = _run(paths, [A])
    assert report[A].action == CONFLICT
    assert _read(paths, A, OWNER) == "new", "the owner's file was overwritten"
    assert _read(paths, A, SYSTEM) == "old", "the system copy was lost"
    # Still a conflict next time: nothing moved, nothing lost.
    assert _run(paths, [A])[A].action == CONFLICT


def test_an_owner_file_anywhere_in_the_tree_is_a_conflict(paths) -> None:
    _seed(paths, A, text="old")
    deep = paths.sandbox_work_dir(A, user_id=OWNER) / "a" / "b"
    deep.mkdir(parents=True)
    (deep / "keep.txt").write_text("keep")
    assert _run(paths, [A])[A].action == CONFLICT
    assert (deep / "keep.txt").read_text() == "keep"


def test_an_owner_symlink_is_a_conflict_and_is_not_followed(paths, tmp_path) -> None:
    _seed(paths, A, text="old")
    target = tmp_path / "elsewhere"
    target.mkdir()
    paths.ensure_thread_dirs(A, user_id=OWNER)
    os.symlink(target, paths.sandbox_work_dir(A, user_id=OWNER) / "link")
    assert _run(paths, [A])[A].action == CONFLICT
    assert target.is_dir()


def test_an_empty_owner_skeleton_is_replaced(paths) -> None:
    """A run's empty directories (no file anywhere) hold no data: replaced."""
    _seed(paths, A, text="old")
    paths.ensure_thread_dirs(A, user_id=OWNER)
    report = _run(paths, [A])
    assert report[A].action == MOVED and "empty" in report[A].detail
    assert _read(paths, A, OWNER) == "old"


def test_a_thread_whose_record_is_not_the_systems_is_never_moved(paths) -> None:
    _seed(paths, A, text="channel")
    report = _run(paths, [A], is_system=lambda tid: False)
    assert report[A].action == SKIPPED
    assert _read(paths, A, SYSTEM) == "channel"
    assert not paths.thread_dir(A, user_id=OWNER).exists()


def test_only_the_named_threads_move(paths) -> None:
    _seed(paths, A)
    _seed(paths, B)
    _run(paths, [A])
    assert _read(paths, B, SYSTEM) == "report" and not paths.thread_dir(B, user_id=OWNER).exists()


def test_a_failed_move_keeps_its_files_and_the_others_still_move(paths, monkeypatch) -> None:
    for tid in (A, B, C):
        _seed(paths, tid, text=tid)
    real = os.rename

    def flaky(src, dst):
        if B in str(src):
            raise OSError(18, "Invalid cross-device link")
        return real(src, dst)

    monkeypatch.setattr("app.run_history.owner_migration.os.rename", flaky)
    report = _run(paths, [A, B, C])

    assert (report[A].action, report[B].action, report[C].action) == (MOVED, FAILED, MOVED)
    assert _read(paths, B, SYSTEM) == B, "the failed thread lost its files"
    assert not paths.thread_dir(B, user_id=OWNER).exists(), "a partial copy was left at the owner"
    assert _read(paths, A, OWNER) == A and _read(paths, C, OWNER) == C

    monkeypatch.setattr("app.run_history.owner_migration.os.rename", real)
    assert {t: e.action for t, e in _run(paths, [A, B, C]).items()} == {B: MOVED}, "the retry did not finish the failed thread"
    assert _read(paths, B, OWNER) == B


def test_the_dry_run_moves_nothing(paths) -> None:
    _seed(paths, A, text="alpha")
    _seed(paths, B, user=SYSTEM)
    _seed(paths, B, user=OWNER, text="owner's")
    report = _run(paths, [A, B], dry_run=True)
    assert (report[A].action, report[B].action) == (WOULD_MOVE, CONFLICT)
    assert _read(paths, A, SYSTEM) == "alpha" and not paths.thread_dir(A, user_id=OWNER).exists()


def test_invalid_ids_and_a_system_owner_move_nothing(paths) -> None:
    _seed(paths, A)
    assert _run(paths, ["../../etc", "a/b", ""]) == {}
    assert move_threads_to_owner(paths, [A], owner=SYSTEM, is_system_thread=_all_system) == []
    assert move_threads_to_owner(paths, [A], owner="", is_system_thread=_all_system) == []
    assert _read(paths, A, SYSTEM) == "report"


def test_a_symlinked_system_copy_is_skipped(paths, tmp_path) -> None:
    target = tmp_path / "outside"
    target.mkdir()
    link = paths.thread_dir(A, user_id=SYSTEM)
    link.parent.mkdir(parents=True)
    os.symlink(target, link)
    assert _run(paths, [A])[A].action == SKIPPED
    assert link.is_symlink() and not paths.thread_dir(A, user_id=OWNER).exists()


def test_the_report_file_records_what_moved_and_the_dry_run_writes_none(paths) -> None:
    _seed(paths, A)
    dry = move_threads_to_owner(paths, [A], owner=OWNER, is_system_thread=_all_system, dry_run=True)
    write_report(paths.base_dir, OWNER, dry, dry_run=True)
    report_file = paths.base_dir / "migrations" / "automation-threads-to-owner.jsonl"
    assert not report_file.exists()

    done = move_threads_to_owner(paths, [A], owner=OWNER, is_system_thread=_all_system)
    write_report(paths.base_dir, OWNER, done, dry_run=False)
    [line] = report_file.read_text().splitlines()
    entry = json.loads(line)
    assert (entry["thread_id"], entry["action"], entry["owner"]) == (A, MOVED, OWNER)
