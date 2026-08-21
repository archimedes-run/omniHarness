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
    log = AuditLog(path=tmp_path / "audit.jsonl")
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
    log = AuditLog(path=tmp_path / "audit.jsonl")
    with pytest.raises(ValueError, match="must be resolved"):
        log.record(_firing(), NOW)


def test_the_log_is_append_only(tmp_path) -> None:
    log = AuditLog(path=tmp_path / "audit.jsonl")
    log.record(_firing("a").resolve(Outcome.DELIVERED), NOW)
    log.record(_firing("b").resolve(Outcome.DELIVERED), NOW)
    assert [e["rule_id"] for e in log.entries()] == ["a", "b"]


def test_entries_survive_a_restart(tmp_path) -> None:
    p = tmp_path / "audit.jsonl"
    AuditLog(path=p).record(_firing().resolve(Outcome.DELIVERED), NOW)
    assert len(AuditLog(path=p).entries()) == 1
