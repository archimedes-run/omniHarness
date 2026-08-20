"""T016 — the startup bound, asserted on RECORDS OPENED (SC-004i, SC-004g).

Read the assertion carefully before changing it: it is on
`stats.records_opened`, never on elapsed time. A wall-clock bound passes on fast
hardware even when a full directory scan has been reintroduced, which makes it
worse than no test — it manufactures confidence. Gate 3 (T017) exists to prove
this assertion actually bites.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from session_watcher.adapters.claude_code import ClaudeCodeAdapter
from session_watcher.discovery import Discovery, DiscoveryConfig
from session_watcher.record_source import RecordSource

WINDOW = timedelta(hours=24)
TOTAL_HISTORY = 5000
IN_WINDOW = 5


@pytest.fixture(scope="module")
def big_history(tmp_path_factory) -> Path:
    """A history directory of several thousand records, 5 of them recent."""
    root = tmp_path_factory.mktemp("hist") / "projects" / "-Users-dev-projects-big"
    root.mkdir(parents=True)
    now = datetime.now(UTC)
    for i in range(TOTAL_HISTORY):
        recent = i < IN_WINDOW
        at = now - (timedelta(minutes=5) if recent else timedelta(days=30 + i % 300))
        sid = f"sess-{i:05d}"
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
                    "message": {"role": "assistant", "content": [{"type": "text", "text": "x"}]},
                }
            )
            + "\n"
        )
        ts = at.timestamp()
        import os

        os.utime(f, (ts, ts))
    return root.parent


def test_startup_opens_records_proportional_to_window_not_directory(big_history: Path) -> None:
    src = RecordSource(root=big_history)
    Discovery(ClaudeCodeAdapter(src), DiscoveryConfig(window=WINDOW)).sweep()

    # THE assertion. Proportional to the handful in the window, not the 5000 on disk.
    assert src.stats.records_opened <= 10, f"opened {src.stats.records_opened} records from a {TOTAL_HISTORY}-record directory; startup cost is scaling with the directory rather than the window (FR-005e)"
    # Sanity: it did do the work, rather than passing by finding nothing.
    assert src.stats.records_opened >= IN_WINDOW


def test_only_in_window_sessions_are_listed(big_history: Path) -> None:
    src = RecordSource(root=big_history)
    refs = Discovery(ClaudeCodeAdapter(src), DiscoveryConfig(window=WINDOW)).sweep()
    assert len(refs) == IN_WINDOW


def test_candidates_are_stat_filtered_before_opening(big_history: Path) -> None:
    """mtime selection must happen BEFORE parsing (FR-005d).

    Considering many candidates is fine and expected; OPENING them is not.
    """
    src = RecordSource(root=big_history)
    Discovery(ClaudeCodeAdapter(src), DiscoveryConfig(window=WINDOW)).sweep()
    assert src.stats.candidates_considered >= TOTAL_HISTORY
    assert src.stats.records_opened < src.stats.candidates_considered / 100


def test_sticky_membership_survives_going_quiet(tmp_session_dir, make_record, ago) -> None:
    """FR-005b/c: once seen active WHILE WE WATCH, a session stays listed.

    Stickiness is earned by activity after the watcher started — merely turning up
    in the initial backfill is not "observed active", and treating it as such
    would make the recency window meaningless on the very first sweep.
    """
    root = tmp_session_dir([make_record(at=ago(1), session_id="live")], session_id="live")
    src = RecordSource(root=root)
    disc = Discovery(ClaudeCodeAdapter(src), DiscoveryConfig(window=timedelta(minutes=30)))
    # Watcher started before that record, so the record counts as activity we saw.
    disc.started_at = datetime.now(UTC) - timedelta(minutes=5)

    refs = disc.sweep()
    assert [r.session_id for r in refs] == ["live"]
    assert disc.is_sticky("live")

    # Now it goes quiet past the window. Membership must not be re-decided.
    disc.config.window = timedelta(seconds=1)
    refs = disc.sweep()
    assert disc.is_sticky("live"), "sticky membership was re-tested against the window (FR-005c)"
    assert [r.session_id for r in refs] == ["live"], "a live session aged out mid-run"


def test_backfilled_session_is_not_sticky_and_ages_out(tmp_session_dir, make_record, ago) -> None:
    """The other half of the rule, and the reason the roll-up stays readable.

    A session that last moved weeks ago but whose file was touched recently is
    inside the mtime window (so it is cheap to read) yet outside the activity
    window (so it is not listed). Without this, a roll-up of "what are my
    sessions doing" answers with weeks of finished work.
    """
    root = tmp_session_dir([make_record(at=ago(60 * 24 * 20), session_id="ancient")], session_id="ancient")
    disc = Discovery(ClaudeCodeAdapter(RecordSource(root=root)), DiscoveryConfig(window=timedelta(hours=24)))
    refs = disc.sweep()
    assert refs == [], "a 20-day-old session was listed inside a 24h activity window"
    assert not disc.is_sticky("ancient")


def test_release_drops_stickiness(tmp_session_dir, make_record, ago) -> None:
    root = tmp_session_dir([make_record(at=ago(1), session_id="done")], session_id="done")
    disc = Discovery(ClaudeCodeAdapter(RecordSource(root=root)), DiscoveryConfig(window=WINDOW))
    disc.started_at = datetime.now(UTC) - timedelta(minutes=5)
    disc.sweep()
    assert disc.is_sticky("done")
    disc.release("done")
    assert not disc.is_sticky("done")
