"""Fixtures for the session-watcher tests.

Every fixture builds session records in a tmp_path. Nothing here ever touches the
real ~/.claude — FR-019 requires zero writes to observed files, and the surest way
to honour that is for the tests to have no reason to look there.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def _record(
    *,
    kind: str = "assistant",
    session_id: str = "sess-0001",
    at: datetime | None = None,
    cwd: str = "/Users/dev/projects/darcy-repo",
    git_branch: str = "main",
    text: str = "Ran the test suite.",
    stop_reason: str | None = None,
    **extra: object,
) -> dict:
    """One session record in the observed shape (see research.md R2)."""
    at = at or datetime.now(UTC)
    rec = {
        "type": kind,
        "sessionId": session_id,
        "session_id": session_id,
        "timestamp": at.isoformat(),
        "cwd": cwd,
        "gitBranch": git_branch,
        "uuid": f"{session_id}-{at.timestamp()}",
        "isSidechain": False,
        "version": "2.0.0",
    }
    if kind in {"assistant", "user"}:
        rec["message"] = {"role": kind, "content": [{"type": "text", "text": text}]}
        # stop_reason lives INSIDE the message envelope, which is where the
        # adapter reads it from. Putting it at the record's top level looks
        # right and is silently ignored.
        if stop_reason is not None:
            rec["message"]["stop_reason"] = stop_reason
    rec.update(extra)
    return rec


@pytest.fixture
def make_record() -> Callable[..., dict]:
    return _record


@pytest.fixture
def tmp_session_dir(tmp_path: Path) -> Callable[..., Path]:
    """Build a session-history directory.

    The project directory name reproduces the real leading-hyphen path slug
    (research.md R2 finding 2) by default, because a fixture that quietly uses a
    normal name would let the whole class of bug through.
    """

    def _build(
        records: list[dict],
        *,
        project_slug: str = "-Users-dev-projects-darcy-repo",
        session_id: str = "sess-0001",
        mtime: datetime | None = None,
        trailing_garbage: str = "",
    ) -> Path:
        root = tmp_path / "projects" / project_slug
        root.mkdir(parents=True, exist_ok=True)
        f = root / f"{session_id}.jsonl"
        body = "".join(json.dumps(r) + "\n" for r in records)
        f.write_text(body + trailing_garbage)
        if mtime is not None:
            ts = mtime.timestamp()
            import os

            os.utime(f, (ts, ts))
        return tmp_path / "projects"

    return _build


@pytest.fixture
def ago() -> Callable[[float], datetime]:
    def _ago(minutes: float) -> datetime:
        return datetime.now(UTC) - timedelta(minutes=minutes)

    return _ago
