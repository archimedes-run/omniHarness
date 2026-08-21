"""T031 — audit completeness (FR-012, FR-012a, SC-010a, Article VIII)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.trigger_engine.audit import AuditLog
from app.trigger_engine.models import Firing, Outcome, TriggerEvent, TriggerType

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def _firing(rid="r1"):
    ev = TriggerEvent(type=TriggerType.WATCHER, event_id="s1", at=NOW)
    return Firing(rule_id=rid, event=ev, prompt="p", thread_id="t1", reply="hello")


def test_every_outcome_appears_with_its_reason(tmp_path) -> None:
    """SC-010a — including the ones that delivered nothing.

    A suppressed or expired firing that leaves no trace is indistinguishable
    from one that never happened, which is the whole reason Article VIII asks
    for this log.
    """
    log = AuditLog(path=tmp_path / "audit.jsonl", actor="default")
    cases = [
        (Outcome.DELIVERED, ""),
        (Outcome.SUPPRESSED, "quiet hours"),
        (Outcome.QUEUED, "user mid-exchange"),
        (Outcome.EXPIRED, "condition no longer holds"),
        (Outcome.FAILED, "redaction failed"),
    ]
    for outcome, reason in cases:
        log.record(_firing().resolve(outcome, reason), NOW)

    entries = log.entries()
    assert len(entries) == 5
    assert {e["outcome"] for e in entries} == {str(o) for o, _ in cases}
    for e in entries:
        if e["outcome"] != "delivered":
            assert e["reason"], f"{e['outcome']} recorded without a reason"


def test_a_non_delivered_outcome_requires_a_reason() -> None:
    """FR-012 — enforced at the model, not left to the caller to remember."""
    with pytest.raises(ValueError, match="requires a reason"):
        _firing().resolve(Outcome.SUPPRESSED)


def test_unresolved_firings_cannot_be_audited(tmp_path) -> None:
    log = AuditLog(path=tmp_path / "audit.jsonl", actor="default")
    with pytest.raises(ValueError, match="must be resolved"):
        log.record(_firing(), NOW)


def test_the_log_is_append_only(tmp_path) -> None:
    log = AuditLog(path=tmp_path / "audit.jsonl", actor="default")
    log.record(_firing("a").resolve(Outcome.DELIVERED), NOW)
    log.record(_firing("b").resolve(Outcome.DELIVERED), NOW)
    assert [e["rule_id"] for e in log.entries()] == ["a", "b"]


def test_entries_survive_a_restart(tmp_path) -> None:
    p = tmp_path / "audit.jsonl"
    AuditLog(path=p, actor="default").record(_firing().resolve(Outcome.DELIVERED), NOW)
    assert len(AuditLog(path=p, actor="default").entries()) == 1


def test_every_entry_names_an_actor(tmp_path):
    """Article VIII's audit exists to make human-out-of-the-loop actions
    reviewable, and a review asks on whose behalf the assistant acted.

    An entry recording only what happened is the obligation under-delivering,
    not met: it says the assistant acted while omitting the account it acted
    as, which is what determines what the action was permitted to reach.
    """
    log = AuditLog(path=tmp_path / "audit.jsonl", actor="default")

    for outcome in Outcome:
        log.record(_firing().resolve(outcome, reason="r"), NOW)

    entries = log.entries()
    assert len(entries) == len(list(Outcome))
    assert all(e.get("actor") == "default" for e in entries), "every outcome, not only DELIVERED, must name its actor — a suppressed or expired firing is exactly what a reviewer is trying to account for"


def test_actor_has_no_default(tmp_path):
    """Constructing an audit log without stating an actor must be impossible.

    A default would let a wiring site omit the one fact the log exists to
    capture, and the omission would look identical to a deliberate choice.
    """
    with pytest.raises(TypeError):
        AuditLog(path=tmp_path / "audit.jsonl")
