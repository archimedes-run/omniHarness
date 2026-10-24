"""Startup migration (#133): automation threads' files move to the owner.

A lead automation used to run as the system user, so the files of its thread
(uploads, outputs, workspace) live under ``users/<system>/threads/<id>/``.
It now runs for the install's owner (``services._scheduled_lead_owner``, as a
006-F agent schedule already did), so its next firing reads and writes
``users/<owner>/threads/<id>/``. This moves each automation thread's directory
across, once, so the automation keeps its files.

WHICH THREADS. Only automation threads, read from server-written records:
the run history's ledger of automation threads, every thread a stored
automation run names, and the engine's rule-to-thread map. And of those, only
threads whose record names the SYSTEM user (the engine creates every
automation thread as the system user). A channel's thread, a person's thread,
or a thread with no record is never touched.

SAFE.
  * Never overwrites: an owner directory that already exists is left alone and
    the system copy stays where it is (reported "conflict"). The one exception
    is an owner directory holding nothing but empty directories (the skeleton a
    run creates): it holds no data, so it is removed (``rmdir`` only, which
    refuses anything non-empty) and the move goes ahead.
  * No data loss: each move is one ``os.rename`` (atomic, same filesystem). A
    failure (another filesystem, permissions) leaves the source intact and is
    reported "failed"; the other threads still move. Nothing is ever copied
    and then deleted.
  * Idempotent: a thread already moved has no system directory, so a rerun
    does nothing. It runs at every startup; a conflict or failure is retried.
  * Logged: each move, conflict and failure is logged by thread id and
    appended to ``migrations/automation-threads-to-owner.jsonl`` under the data
    dir. ``dry_run=True`` reports what would move and moves nothing.
  * Under the engine's cross-process firing lock, so no firing (in any
    worker) writes into a thread while it moves.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

REPORT_FILE = Path("migrations") / "automation-threads-to-owner.jsonl"

MOVED = "moved"
WOULD_MOVE = "would-move"
CONFLICT = "conflict"
FAILED = "failed"
SKIPPED = "skipped"


@dataclass
class ThreadMove:
    thread_id: str
    action: str
    detail: str = ""


def _only_empty_dirs(path: Path) -> bool:
    """True when ``path`` is a real directory holding only (nested) empty
    directories: no file, no symlink, nothing else."""
    if path.is_symlink() or not path.is_dir():
        return False
    for _root, dirs, files in os.walk(path, followlinks=False):
        if files:
            return False
        for d in dirs:
            if os.path.islink(os.path.join(_root, d)):
                return False
    return True


def _remove_empty_tree(path: Path) -> None:
    """Remove a tree of empty directories with ``rmdir`` only: anything that
    is not empty (a file written meanwhile) makes it raise, never deletes."""
    for root, dirs, _files in os.walk(path, topdown=False, followlinks=False):
        for d in dirs:
            os.rmdir(os.path.join(root, d))
    os.rmdir(path)


def move_threads_to_owner(
    paths,
    thread_ids: Iterable[str],
    *,
    owner: str,
    is_system_thread: Callable[[str], bool],
    dry_run: bool = False,
) -> list[ThreadMove]:
    """Move each automation thread's directory from the system user to
    ``owner``. Returns one entry per thread that HAD a system directory
    (moved, would move, conflict, failed or skipped); a thread with none is
    already done and is not listed."""
    from omniharness.runtime.user_context import DEFAULT_USER_ID

    report: list[ThreadMove] = []
    if not owner or owner == DEFAULT_USER_ID:
        return report
    for tid in sorted(set(thread_ids)):
        try:
            src = paths.thread_dir(tid, user_id=DEFAULT_USER_ID)
            dst = paths.thread_dir(tid, user_id=owner)
        except ValueError:
            continue  # not a valid thread id: never a path to act on
        if not os.path.lexists(src):
            continue
        if not is_system_thread(tid):
            report.append(ThreadMove(tid, SKIPPED, "the thread's record does not name the system user"))
            continue
        if src.is_symlink() or not src.is_dir():
            report.append(ThreadMove(tid, SKIPPED, "the system copy is not a directory"))
            continue
        replace_skeleton = False
        if os.path.lexists(dst):
            if not _only_empty_dirs(dst):
                report.append(ThreadMove(tid, CONFLICT, "the owner already has files for this thread; both copies kept"))
                continue
            replace_skeleton = True
        if dry_run:
            report.append(ThreadMove(tid, WOULD_MOVE, "replacing an empty owner directory" if replace_skeleton else ""))
            continue
        try:
            if replace_skeleton:
                _remove_empty_tree(dst)
            dst.parent.mkdir(parents=True, exist_ok=True)
            if os.path.lexists(dst):  # appeared meanwhile: never rename onto it
                raise FileExistsError(str(dst))
            os.rename(src, dst)
        except OSError as exc:
            report.append(ThreadMove(tid, FAILED, type(exc).__name__))
            continue
        report.append(ThreadMove(tid, MOVED, "replaced an empty owner directory" if replace_skeleton else ""))
    return report


def write_report(base_dir: Path, owner: str, report: list[ThreadMove], *, dry_run: bool) -> None:
    """Log every entry (by thread id) and append it to the report file."""
    for entry in report:
        level = logging.INFO if entry.action in (MOVED, WOULD_MOVE) else logging.WARNING
        logger.log(level, "automation thread %s: %s%s", entry.thread_id, entry.action, f" ({entry.detail})" if entry.detail else "")
    if not report or dry_run:
        return
    try:
        path = Path(base_dir) / REPORT_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        at = datetime.now(UTC).isoformat()
        with open(path, "a", encoding="utf-8") as fh:
            for entry in report:
                fh.write(json.dumps({"at": at, "owner": owner, **asdict(entry)}) + "\n")
    except OSError:
        logger.warning("could not write the automation-thread migration report", exc_info=True)


async def automation_thread_ids(app) -> set[str]:
    """Every automation thread the server has a record of: the run history's
    ledger and runs, and the engine's rule-to-thread map."""
    from app.run_history.delete import _rule_map
    from app.run_history.recorder import AUTOMATION

    ids: set[str] = set()
    history = getattr(app.state, "run_history", None)
    if history is not None:
        ids |= set(history.ledger_threads())
        ids |= set(history.thread_ids(kind=AUTOMATION))
    rule_map, _ = _rule_map(app)
    ids |= {t for t in (rule_map.thread_of(r) for r in rule_map.known_rules()) if t}
    return ids


async def migrate_automation_threads_to_owner(app, *, dry_run: bool = False) -> list[ThreadMove] | None:
    """The startup step. None when there is no owner (no accounts: automations
    still run as the system user, nothing moves) or the firing lock could not
    be had (retried at the next startup)."""
    from app.gateway.ownership import SYSTEM_OWNERS, owner_user_id
    from app.run_history.delete import _locked
    from omniharness.config.paths import get_paths

    owner = await owner_user_id()
    if owner is None or owner in SYSTEM_OWNERS:
        return None
    ids = await automation_thread_ids(app)
    paths = get_paths()
    candidates = {t for t in ids if _has_system_dir(paths, t)}
    if not candidates:
        return []
    store = getattr(app.state, "thread_store", None)
    system_threads: set[str] = set()
    if store is not None:
        for tid in candidates:
            row = await store.get(tid, user_id=None)
            if row is not None and str(row.get("user_id")) in SYSTEM_OWNERS:
                system_threads.add(tid)

    def work(_rule_map, _run) -> list[ThreadMove]:
        return move_threads_to_owner(paths, candidates, owner=owner, is_system_thread=system_threads.__contains__, dry_run=dry_run)

    report = await _locked(app, work, refuse=False)
    if report is None:
        logger.warning("automation threads were not moved to the owner: a firing held the lock; retried at the next startup")
        return None
    write_report(paths.base_dir, owner, report, dry_run=dry_run)
    return report


def _has_system_dir(paths, thread_id: str) -> bool:
    from omniharness.runtime.user_context import DEFAULT_USER_ID

    try:
        return os.path.lexists(paths.thread_dir(thread_id, user_id=DEFAULT_USER_ID))
    except ValueError:
        return False
