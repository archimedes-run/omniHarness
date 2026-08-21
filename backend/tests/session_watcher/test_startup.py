"""T064 — first-query latency smoke bound (SC-004j).

Deliberately generous, and deliberately NOT the mechanism protecting FR-005e.
A wall-clock bound passes on fast hardware even when a full directory scan has
been reintroduced; `test_discovery_window.py` asserts on records_opened and is
what actually guards that requirement. Do not "consolidate" the two.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from session_watcher.server import WatcherService

TOTAL, IN_WINDOW = 2000, 4


@pytest.fixture(scope="module")
def big_history(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("startup") / "projects" / "-Users-dev-projects-big"
    root.mkdir(parents=True)
    now = datetime.now(UTC)
    for i in range(TOTAL):
        at = now - (timedelta(minutes=2) if i < IN_WINDOW else timedelta(days=40 + i % 200))
        sid = f"s{i:05d}"
        f = root / f"{sid}.jsonl"
        f.write_text(
            json.dumps(
                {
                    "type": "assistant",
                    "sessionId": sid,
                    "timestamp": at.isoformat(),
                    "cwd": "/Users/dev/projects/big",
                    "gitBranch": "main",
                    "uuid": sid,
                    "isSidechain": False,
                    "version": "2.0.0",
                    "message": {"role": "assistant", "stop_reason": "end_turn", "content": [{"type": "text", "text": "done"}]},
                }
            )
            + "\n"
        )
        os.utime(f, (at.timestamp(), at.timestamp()))
    return root.parent


def test_first_query_is_answerable_within_five_seconds(big_history: Path) -> None:
    svc = WatcherService(root=big_history)
    start = time.perf_counter()
    svc.refresh()
    payload = svc.list_sessions()
    elapsed = time.perf_counter() - start
    assert payload["observable"] is True
    assert len(payload["sessions"]) == IN_WINDOW
    assert elapsed < 5.0, f"first query took {elapsed:.2f}s against {TOTAL} records (SC-004j)"


def test_the_real_guard_is_records_opened_not_this_timer(big_history: Path) -> None:
    """Guard against someone deleting the records_opened assertion as redundant."""
    svc = WatcherService(root=big_history)
    svc.refresh()
    assert svc.source.stats.records_opened <= 10, "startup is scaling with the directory; the timing test above would still pass on fast hardware, which is why FR-005e is guarded by this count"
