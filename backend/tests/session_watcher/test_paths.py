"""T013 — hyphen-prefixed path handling (FR-020, research R2 finding 2).

Real project directories are path-slugs like `-Users-rishabh-...`. A leading dash
reads as an option flag to shell tooling, so this works on a developer's machine
right up until something shells out. The module-wide subprocess ban makes that
unrepresentable; this test proves the pathlib path actually works.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from session_watcher.adapters.claude_code import ClaudeCodeAdapter
from session_watcher.record_source import RecordSource

WINDOW = timedelta(days=3650)


def test_discovery_works_under_hyphen_prefixed_directory(tmp_session_dir, make_record) -> None:
    root = tmp_session_dir(
        [make_record(kind="user", text="go"), make_record(kind="assistant", text="going")],
        project_slug="-Users-dev-projects-darcy-repo",
    )
    # The directory really does start with a dash — guard against the fixture
    # quietly normalising it, which would make this test vacuous.
    assert any(p.name.startswith("-") for p in root.iterdir())
    refs = ClaudeCodeAdapter(RecordSource(root=root)).discover(WINDOW)
    assert len(refs) == 1
    assert refs[0].records


def test_multiple_hyphen_projects_stay_distinct(tmp_session_dir, make_record) -> None:
    root = tmp_session_dir(
        [make_record(session_id="a", cwd="/Users/dev/alpha")],
        project_slug="-Users-dev-alpha",
        session_id="a",
    )
    tmp_session_dir(
        [make_record(session_id="b", cwd="/Users/dev/beta")],
        project_slug="-Users-dev-beta",
        session_id="b",
    )
    refs = ClaudeCodeAdapter(RecordSource(root=root)).discover(WINDOW)
    assert {r.session_id for r in refs} == {"a", "b"}


def test_paths_are_pathlib_objects_not_strings() -> None:
    """Guard the seam's type: a str path is one os.system() away from a bug."""
    src = RecordSource(root=Path("/tmp/whatever"))
    assert isinstance(src.root, Path)


def test_stat_failure_on_candidate_is_survived(tmp_session_dir, make_record, monkeypatch) -> None:
    root = tmp_session_dir([make_record(at=datetime.now(UTC))])
    src = RecordSource(root=root)
    real_stat = Path.stat

    def boom(self, *a, **k):
        if self.suffix == ".jsonl":
            raise OSError("vanished")
        return real_stat(self, *a, **k)

    monkeypatch.setattr(Path, "stat", boom)
    assert src.select_candidates(WINDOW) == []
