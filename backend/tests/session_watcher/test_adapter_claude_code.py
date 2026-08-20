"""T012 — adapter against the fixture corpus (FR-009, SC-005).

The point of these tests is not that valid records parse; it is that INVALID ones
are survived. A parser that crashes on a truncated final line loses the whole
session, and one that silently absorbs unknown types reports confident nonsense.
"""

from __future__ import annotations

import shutil
from datetime import timedelta
from pathlib import Path

import pytest
from session_watcher.adapters.claude_code import ClaudeCodeAdapter
from session_watcher.models import EventKind
from session_watcher.record_source import RecordSource, SkipReason

FIXTURES = Path(__file__).parent / "fixtures"
WINDOW = timedelta(days=3650)  # fixtures carry fixed dates; window must not exclude them


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    """Copy fixtures under a hyphen-prefixed project dir, as the real ones are."""
    root = tmp_path / "projects" / "-Users-dev-projects-fixture"
    root.mkdir(parents=True)
    for f in FIXTURES.glob("*.jsonl"):
        shutil.copy(f, root / f.name)
    return tmp_path / "projects"


def _discover(root: Path):
    src = RecordSource(root=root)
    return ClaudeCodeAdapter(src).discover(WINDOW), src


def test_valid_session_parses(corpus: Path) -> None:
    refs, _ = _discover(corpus)
    valid = next(r for r in refs if r.session_id == "sess-valid")
    assert valid.project == "darcy-repo@main"
    kinds = [r.kind for r in valid.records if r.kind is not None]
    assert EventKind.STARTED in kinds or EventKind.PROGRESS in kinds
    assert any("41 tests passed" in r.text for r in valid.records)


def test_malformed_and_truncated_survive(corpus: Path) -> None:
    """The drift fixture holds bad JSON, a truncated tail, and unknown types."""
    refs, src = _discover(corpus)
    drift = next(r for r in refs if r.session_id == "sess-drift")
    # Records surrounding the damage still parse — the file is not abandoned.
    texts = " ".join(r.text for r in drift.records)
    assert "Building." in texts
    assert "Done." in texts
    # And the damage was counted, not swallowed.
    assert src.stats.records_skipped > 0


def test_record_without_session_id_is_skipped_not_fatal(corpus: Path) -> None:
    refs, _ = _discover(corpus)
    orphan = next(r for r in refs if r.session_id == "sess-orphan")
    assert any("Recovered." in r.text for r in orphan.records)


def test_unknown_types_are_counted_not_absorbed(corpus: Path) -> None:
    """A never-before-seen type must surface as drift, never be folded into PROGRESS.

    This is the difference between "we ignored 40% of the file" being visible and
    being invisible. Absorption would keep every other test in this file green.
    """
    _, src = _discover(corpus)
    assert "some-future-type-we-have-never-seen" in src.stats.unknown_types
    assert src.stats.drift_signals > 0


def test_known_inert_types_are_not_reported_as_drift(corpus: Path) -> None:
    """Recognised-but-meaningless types must NOT count as drift.

    On a real corpus these dominate — thousands of `mode`/`ai-title`/`last-prompt`
    records. If they log as damage, a genuine format change is invisible in the
    noise, which defeats the purpose of counting at all.
    """
    _, src = _discover(corpus)
    assert src.stats.skips[SkipReason.INERT_TYPE] > 0
    for inert in ("atis-latch", "bridge-session"):
        assert inert not in src.stats.unknown_types


def test_skip_reasons_are_attributed_not_lumped(corpus: Path) -> None:
    _, src = _discover(corpus)
    assert src.stats.skips[SkipReason.MALFORMED] > 0  # the "not json at all" line
    assert src.stats.skips[SkipReason.NO_SESSION_ID] > 0  # the orphan record
    assert sum(src.stats.skips.values()) == src.stats.records_skipped


def test_end_of_turn_marker_is_observed_not_inferred(corpus: Path) -> None:
    """FR-006a's marker: message.stop_reason == end_turn (verified against real records).

    tool_use means the agent paused to call a tool and is still mid-work. Treating
    it as an end of turn would report a killed session as finished.
    """
    refs, _ = _discover(corpus)
    marker = next(r for r in refs if r.session_id == "sess-marker")
    ends = [r for r in marker.records if r.is_end_of_turn]
    assert len(ends) == 1
    assert ends[0].stop_reason == "end_turn"
    assert ends[0].kind is EventKind.COMPLETED

    tool_pauses = [r for r in marker.records if r.stop_reason == "tool_use"]
    assert tool_pauses, "fixture must contain a tool_use record"
    for rec in tool_pauses:
        assert not rec.is_end_of_turn
        assert rec.kind is EventKind.PROGRESS


def test_no_crash_on_empty_directory(tmp_path: Path) -> None:
    refs, _ = _discover(tmp_path / "nothing-here")
    assert refs == []
