"""T035 — zero writes to observed files (FR-019, SC-007, Gate 1).

Hash AND size AND mtime, all three. Content hash alone would miss a
write-then-restore; mtime alone would miss a same-timestamp rewrite. The
guarantee is that we never touch what we observe, so the check has to be able to
detect a touch that tried to cover its tracks.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from datetime import timedelta
from pathlib import Path

from session_watcher.adapters.claude_code import ClaudeCodeAdapter
from session_watcher.discovery import Discovery, DiscoveryConfig
from session_watcher.record_source import RecordSource

FIXTURES = Path(__file__).parent / "fixtures"
WINDOW = timedelta(days=3650)


def _snapshot(root: Path) -> dict[Path, tuple[str, int, int]]:
    out = {}
    for p in sorted(root.rglob("*.jsonl")):
        st = p.stat()
        out[p] = (hashlib.sha256(p.read_bytes()).hexdigest(), st.st_size, st.st_mtime_ns)
    return out


def _corpus(tmp_path: Path) -> Path:
    root = tmp_path / "projects" / "-Users-dev-projects-zero"
    root.mkdir(parents=True)
    for f in FIXTURES.glob("*.jsonl"):
        shutil.copy(f, root / f.name)
    return tmp_path / "projects"


def test_full_observation_cycle_writes_nothing(tmp_path: Path) -> None:
    root = _corpus(tmp_path)
    before = _snapshot(root)
    assert before, "corpus must be non-empty or this test proves nothing"

    src = RecordSource(root=root)
    Discovery(ClaudeCodeAdapter(src), DiscoveryConfig(window=WINDOW)).sweep()
    assert src.stats.records_opened > 0, "nothing was read; the test would pass vacuously"

    after = _snapshot(root)
    assert after == before, {str(p): (before.get(p), after.get(p)) for p in set(before) | set(after) if before.get(p) != after.get(p)}


def test_no_new_files_appear_in_the_watched_tree(tmp_path: Path) -> None:
    root = _corpus(tmp_path)
    before = {p for p in root.rglob("*")}
    src = RecordSource(root=root)
    Discovery(ClaudeCodeAdapter(src), DiscoveryConfig(window=WINDOW)).sweep()
    assert {p for p in root.rglob("*")} == before, "the watcher created files in the watched tree"


def test_records_are_opened_read_only(tmp_path: Path, monkeypatch) -> None:
    """Structural guard: any non-read mode is a bug, caught at the seam."""
    root = _corpus(tmp_path)
    real_open = Path.open
    modes: list[str] = []

    def spy(self, mode="r", *a, **k):
        modes.append(mode)
        return real_open(self, mode, *a, **k)

    monkeypatch.setattr(Path, "open", spy)
    src = RecordSource(root=root)
    Discovery(ClaudeCodeAdapter(src), DiscoveryConfig(window=WINDOW)).sweep()
    assert modes, "no file was opened"
    for m in modes:
        assert set(m) <= set("rbt"), f"non-read open mode used on a watched file: {m!r}"


def test_a_read_only_directory_is_still_fully_observable(tmp_path: Path) -> None:
    """If we ever did try to write, this is where it would surface."""
    root = _corpus(tmp_path)
    target = root / "-Users-dev-projects-zero"
    original = target.stat().st_mode
    os.chmod(target, 0o500)  # r-x: readable, not writable
    try:
        src = RecordSource(root=root)
        refs = Discovery(ClaudeCodeAdapter(src), DiscoveryConfig(window=WINDOW)).sweep()
        assert refs, "observation failed against a read-only directory"
    finally:
        os.chmod(target, original)
