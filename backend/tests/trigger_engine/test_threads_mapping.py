"""T020-T022 — the durable rule-id -> thread-id map (FR-011a/b/c)."""

from __future__ import annotations

import itertools

from app.trigger_engine.threads import RuleThreadMap


def _mapper(tmp_path, counter=None):
    c = counter or itertools.count(1)
    return RuleThreadMap(path=tmp_path / "threads.json", create_thread=lambda rid: f"thread-{next(c)}")


def test_first_firing_creates_a_thread(tmp_path) -> None:
    m = _mapper(tmp_path)
    assert m.thread_for("r1") == "thread-1"


def test_same_rule_reuses_its_thread(tmp_path) -> None:
    """FR-011a — a morning briefing should remember yesterday's."""
    m = _mapper(tmp_path)
    assert m.thread_for("r1") == m.thread_for("r1") == "thread-1"


def test_rules_do_not_share_a_thread(tmp_path) -> None:
    m = _mapper(tmp_path)
    assert m.thread_for("r1") != m.thread_for("r2")


def test_mapping_survives_a_restart(tmp_path) -> None:
    """FR-011b, SC-015b — THE assertion.

    Without persistence this presents as a stable thread in the spec and
    behaves as a fresh one in practice; the failure is invisible until someone
    reads the conversation and finds it has no past.
    """
    first = _mapper(tmp_path).thread_for("r1")
    # A brand-new mapper — as after a process restart — with a counter that
    # would hand out a different id if it were consulted.
    again = _mapper(tmp_path, itertools.count(100)).thread_for("r1")
    assert again == first, "the thread was orphaned by the restart"


def test_forgotten_mapping_is_treated_as_a_first_firing(tmp_path) -> None:
    """A thread deleted out from under us must not fail the rule forever."""
    m = _mapper(tmp_path)
    original = m.thread_for("r1")
    m.forget("r1")
    assert m.thread_for("r1") != original


def test_a_renamed_rule_gets_its_own_thread(tmp_path) -> None:
    """The id is identity; inheriting across a rename would merge histories."""
    m = _mapper(tmp_path)
    old = m.thread_for("morning-briefing")
    new = m.thread_for("morning-briefing-v2")
    assert new != old
    assert set(m.known_rules()) == {"morning-briefing", "morning-briefing-v2"}


def test_corrupt_store_does_not_take_the_engine_down(tmp_path) -> None:
    p = tmp_path / "threads.json"
    p.write_text("{ not json")
    m = RuleThreadMap(path=p, create_thread=lambda rid: "fresh")
    assert m.thread_for("r1") == "fresh"
