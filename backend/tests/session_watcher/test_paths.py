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


# --- T065: Windows path conventions (FR-020) --------------------------------


def test_pure_windows_paths_resolve_without_shelling_out() -> None:
    """Path handling must be correct under Windows conventions.

    Tested via PureWindowsPath rather than skipped-on-not-Windows, so it runs in
    CI on macOS and Linux too. A skipped test is indistinguishable from a passing
    one in a summary line, and this is a two-platform requirement.
    """
    from pathlib import PureWindowsPath

    p = PureWindowsPath(r"C:\Users\dev\.claude\projects\-C--Users-dev-repo\s1.jsonl")
    assert p.name == "s1.jsonl"
    assert p.parent.name.startswith("-")  # the hyphen slug survives
    assert p.suffix == ".jsonl"
    # A Windows project slug encodes the drive; it must not be mangled.
    assert "C--Users-dev-repo" in p.parent.name


def test_windows_style_cwd_yields_a_sensible_project_name() -> None:
    """The adapter derives project from `cwd`; that must work for both separators."""
    from pathlib import PureWindowsPath

    assert PureWindowsPath(r"C:\Users\dev\projects\darcy-repo").name == "darcy-repo"


def test_adapter_project_extraction_handles_a_windows_cwd(tmp_session_dir, make_record) -> None:
    from datetime import timedelta

    from session_watcher.adapters.claude_code import ClaudeCodeAdapter
    from session_watcher.record_source import RecordSource

    root = tmp_session_dir(
        [make_record(cwd=r"C:\Users\dev\projects\darcy-repo", git_branch="main")],
        project_slug="-C--Users-dev-projects-darcy-repo",
    )
    refs = ClaudeCodeAdapter(RecordSource(root=root)).discover(timedelta(days=3650))
    assert refs, "no session discovered under a Windows-style slug"
    # Path(cwd).name on a posix host returns the WHOLE backslash string, which
    # would name the project "C:\\Users\\dev\\projects\\darcy-repo@main". A mangled
    # name is worse than a missing one because it looks deliberate.
    assert refs[0].project == "darcy-repo@main", refs[0].project
    assert "\\" not in refs[0].project
