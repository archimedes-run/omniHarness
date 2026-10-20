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
    assert "live" in disc._sticky

    # Now it goes quiet past the window. Membership must not be re-decided.
    disc.config.window = timedelta(seconds=1)
    refs = disc.sweep()
    assert "live" in disc._sticky, "sticky membership was re-tested against the window (FR-005c)"
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
    assert "ancient" not in disc._sticky


def test_release_drops_stickiness(tmp_session_dir, make_record, ago) -> None:
    root = tmp_session_dir([make_record(at=ago(1), session_id="done")], session_id="done")
    disc = Discovery(ClaudeCodeAdapter(RecordSource(root=root)), DiscoveryConfig(window=WINDOW))
    disc.started_at = datetime.now(UTC) - timedelta(minutes=5)
    disc.sweep()
    assert "done" in disc._sticky
    disc.release("done")
    assert "done" not in disc._sticky


# --- the retention reset (FR-005c) ------------------------------------------


def test_retention_reset_clears_sticky_membership(tmp_session_dir, make_record, ago) -> None:
    """FR-005c's "retention reset", which previously existed only as a phrase.

    Sticky membership exempts a live session from the recency window so it cannot
    age out mid-run. Without an end to that exemption, a session seen active once
    is exempt for the life of the process and the set never shrinks.
    """
    root = tmp_session_dir([make_record(at=ago(1), session_id="live")], session_id="live")
    disc = Discovery(
        ClaudeCodeAdapter(RecordSource(root=root)),
        DiscoveryConfig(window=timedelta(minutes=30), retention_reset=timedelta(days=1)),
    )
    start = datetime.now(UTC) - timedelta(minutes=5)
    disc.started_at = start
    disc.last_reset_at = start
    disc.sweep()
    assert "live" in disc._sticky

    dropped = disc.reset_retention(datetime.now(UTC))
    assert "live" in dropped
    assert "live" not in disc._sticky


def test_retention_reset_fires_automatically_after_the_interval(tmp_session_dir, make_record, ago) -> None:
    root = tmp_session_dir([make_record(at=ago(1), session_id="s")], session_id="s")
    disc = Discovery(
        ClaudeCodeAdapter(RecordSource(root=root)),
        DiscoveryConfig(window=timedelta(hours=24), retention_reset=timedelta(days=1)),
    )
    disc.started_at = datetime.now(UTC) - timedelta(minutes=5)
    disc.last_reset_at = datetime.now(UTC) - timedelta(days=2)  # overdue
    disc.sweep()
    assert disc.last_reset_at is not None
    assert datetime.now(UTC) - disc.last_reset_at < timedelta(minutes=1), "reset did not fire"


def test_sticky_set_does_not_grow_without_bound(tmp_session_dir, make_record, ago) -> None:
    """The leak the reset exists to prevent, asserted directly."""
    root = tmp_session_dir([make_record(at=ago(1), session_id="a")], session_id="a")
    disc = Discovery(
        ClaudeCodeAdapter(RecordSource(root=root)),
        DiscoveryConfig(window=timedelta(hours=24), retention_reset=timedelta(days=1)),
    )
    disc.started_at = datetime.now(UTC) - timedelta(minutes=5)
    disc.last_reset_at = datetime.now(UTC) - timedelta(days=2)
    disc.sweep()
    assert len(disc.sticky_ids) <= 1


# --- Gate 3, extended: an append costs the appended bytes (Phase 2.5) ---------
#
# The bound above is on STARTUP. Steady state had no bound, and it re-read
# every file in the window from byte 0 on every sweep: an 85 MB transcript,
# appended to constantly, held a core at 100% and timed the gateway out at 10 s.


def _line(sid: str, text: str, *, kind: str = "assistant", at: datetime | None = None) -> str:
    at = at or datetime.now(UTC)
    return json.dumps({"type": kind, "sessionId": sid, "timestamp": at.isoformat(), "cwd": "/Users/dev/projects/live", "message": {"role": kind, "content": [{"type": "text", "text": text}]}}) + "\n"


@pytest.fixture
def live(tmp_path):
    root = tmp_path / "projects" / "-Users-dev-projects-live"
    root.mkdir(parents=True)
    src = RecordSource(root=tmp_path / "projects")
    return root, src, ClaudeCodeAdapter(src)


def _texts(refs, sid: str) -> list[str]:
    [ref] = [r for r in refs if r.session_id == sid]
    return [r.text for r in ref.records]


def test_an_append_reads_only_the_appended_bytes(live) -> None:
    root, src, adapter = live
    f = root / "s1.jsonl"
    f.write_text("".join(_line("s1", f"turn {i}") for i in range(200)))
    adapter.discover(WINDOW)
    assert src.stats.bytes_read == f.stat().st_size  # the first read is the whole file

    appended = _line("s1", "the new turn")
    with f.open("a") as fh:
        fh.write(appended)
    before = src.stats.bytes_read
    refs = adapter.discover(WINDOW)

    assert src.stats.bytes_read - before == len(appended.encode()), "an append re-read more than the appended bytes"
    assert _texts(refs, "s1")[-1] == "the new turn"


def test_an_unchanged_file_is_not_opened(live) -> None:
    root, src, adapter = live
    (root / "s1.jsonl").write_text(_line("s1", "hello"))
    adapter.discover(WINDOW)
    opened = src.stats.records_opened

    adapter.discover(WINDOW)

    assert src.stats.records_opened == opened, "a sweep with nothing new still opened the file"


def test_a_partial_last_line_waits_for_its_newline(live) -> None:
    root, src, adapter = live
    f = root / "s1.jsonl"
    f.write_text(_line("s1", "complete"))
    adapter.discover(WINDOW)
    whole = _line("s1", "arrives in two writes")
    with f.open("a") as fh:
        fh.write(whole[:30])

    assert _texts(adapter.discover(WINDOW), "s1") == ["complete"], "half a line was parsed"
    assert src.stats.skips == {}, "half a line was counted as damage"

    with f.open("a") as fh:
        fh.write(whole[30:])
    assert _texts(adapter.discover(WINDOW), "s1") == ["complete", "arrives in two writes"]


def test_a_shrunk_or_replaced_file_is_read_again_from_the_start(live) -> None:
    root, src, adapter = live
    f = root / "s1.jsonl"
    f.write_text(_line("s1", "a") + _line("s1", "b") + _line("s1", "c"))
    adapter.discover(WINDOW)

    f.write_text(_line("s1", "rewritten"))  # shorter than our offset: truncated or rewritten
    assert _texts(adapter.discover(WINDOW), "s1") == ["rewritten"]

    replacement = root / "s1.jsonl.tmp"
    replacement.write_text(_line("s1", "replaced") + _line("s1", "and longer than before, so size alone would not tell"))
    replacement.replace(f)  # new inode, larger size
    assert _texts(adapter.discover(WINDOW), "s1") == ["replaced", "and longer than before, so size alone would not tell"]


def test_a_new_file_is_picked_up(live) -> None:
    root, src, adapter = live
    (root / "s1.jsonl").write_text(_line("s1", "first session"))
    adapter.discover(WINDOW)

    (root / "s2.jsonl").write_text(_line("s2", "second session"))
    refs = adapter.discover(WINDOW)

    assert {r.session_id for r in refs} == {"s1", "s2"}


def test_steady_state_matches_a_fresh_read(live) -> None:
    """The incremental result is the same as reading from scratch, including
    STARTED on only the first record of a session spread over two files."""
    from session_watcher.models import EventKind

    root, src, adapter = live
    f = root / "a.jsonl"
    f.write_text(_line("s1", "one"))
    adapter.discover(WINDOW)
    with f.open("a") as fh:
        fh.write(_line("s1", "two") + _line("s1", "three?"))
    (root / "b.jsonl").write_text(_line("s1", "sidechain"))
    incremental = adapter.discover(WINDOW)
    fresh = ClaudeCodeAdapter(RecordSource(root=src.root)).discover(WINDOW)

    assert [(r.text, r.kind) for r in incremental[0].records] == [(r.text, r.kind) for r in fresh[0].records]
    assert [r.kind for r in incremental[0].records].count(EventKind.STARTED) <= 1
