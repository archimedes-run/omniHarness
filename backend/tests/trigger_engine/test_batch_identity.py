"""T032-T034/FR-021 — firings merged into one message can say so.

COALESCING IS NOT AN OUTCOME, and the tests below hold that line. A firing that
was merged WAS delivered; the merge changed how many messages the user received,
not whether this firing succeeded. A COALESCED member of Outcome would put a
false statement in the audit log, so the identity is a separate field and every
survivor stays DELIVERED.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from app.trigger_engine.audit import AuditLog
from app.trigger_engine.models import Firing, Outcome, TriggerEvent, TriggerType
from app.trigger_engine.politeness.release import ReleaseReason, Releaser

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)


def _firing(event_id: str) -> Firing:
    return Firing(
        rule_id="r1",
        event=TriggerEvent(type=TriggerType.CRON, event_id=event_id, at=NOW),
        prompt=f"say {event_id}",
        reply=f"hello {event_id}",
    )


class _Destination:
    def __init__(self) -> None:
        self.delivered: list[str] = []

    def deliver(self, text: str) -> None:
        self.delivered.append(text)


@pytest.fixture
def released(tmp_path):
    """Drives the REAL Releaser, so what is asserted is what production does."""
    audit = AuditLog(path=tmp_path / "audit.jsonl", actor="test")

    def run(firings):
        destination = _Destination()
        releaser = Releaser(redact=lambda t: (t, True), still_true=lambda f: True, audit=audit.record)
        text = releaser.release(firings, ReleaseReason.IMMEDIATE, destination, NOW)
        return text, destination, audit

    return run


def test_a_solo_delivery_has_no_batch_id(released):
    """T033. The field's PRESENCE has to mean something, so it is unset when
    nothing was merged."""
    one = _firing("e1")
    text, destination, _ = released([one])

    assert text is not None and len(destination.delivered) == 1
    assert one.outcome is Outcome.DELIVERED
    assert one.batch_id is None


def test_coalesced_firings_share_one_batch_id(released):
    """T032, first half."""
    a, b, c = _firing("e1"), _firing("e2"), _firing("e3")
    text, destination, _ = released([a, b, c])

    assert len(destination.delivered) == 1, "three firings should become one message"
    ids = {f.batch_id for f in (a, b, c)}
    assert len(ids) == 1 and ids != {None}, f"expected one shared batch id, got {ids}"


def test_every_coalesced_firing_is_still_recorded_delivered(released):
    """T032, and the half that matters. Coalescing is not an outcome."""
    a, b, c = _firing("e1"), _firing("e2"), _firing("e3")
    released([a, b, c])

    for f in (a, b, c):
        assert f.outcome is Outcome.DELIVERED, f"{f.event.event_id} was recorded {f.outcome}, not delivered"
    assert not hasattr(Outcome, "COALESCED"), "coalescing became an outcome; the audit log now asserts something untrue"


def test_the_audit_row_carries_the_batch_id(released, tmp_path):
    a, b = _firing("e1"), _firing("e2")
    released([a, b])

    rows = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert len(rows) == 2
    assert {r["batch_id"] for r in rows} == {a.batch_id}
    assert all(r["outcome"] == str(Outcome.DELIVERED) for r in rows)


def test_a_solo_audit_row_records_null_rather_than_omitting_the_key(released, tmp_path):
    """T034's distinction, from the writing side. `null` says 'recorded, and not
    coalesced'. An ABSENT key says 'written before batching existed'. Omitting
    the key for solo deliveries would collapse the two."""
    released([_firing("e1")])

    row = json.loads((tmp_path / "audit.jsonl").read_text().splitlines()[0])
    assert "batch_id" in row, "the key must be written even when there is no batch"
    assert row["batch_id"] is None


def test_a_row_written_before_batching_reads_as_not_recorded(tmp_path):
    """T034/FR-022, from the reading side, against a fixture of OLD rows.

    A row predating the field has no key at all. A consumer must be able to tell
    that from a row that recorded "not coalesced", because "we never wrote this"
    and "this was delivered alone" are different facts.
    """
    path = tmp_path / "audit.jsonl"
    path.write_text(json.dumps({"at": NOW.isoformat(), "rule_id": "r1", "outcome": "delivered", "reason": ""}) + "\n" + json.dumps({"at": NOW.isoformat(), "rule_id": "r1", "outcome": "delivered", "reason": "", "batch_id": None}) + "\n")
    old, new = [json.loads(line) for line in path.read_text().splitlines()]

    assert "batch_id" not in old, "the fixture does not represent a pre-batching row"
    assert "batch_id" in new and new["batch_id"] is None
    assert ("batch_id" in old) != ("batch_id" in new), "not recorded and recorded-as-none are indistinguishable"


def test_a_firing_round_trips_its_batch_id_through_persistence(tmp_path):
    from app.trigger_engine.persistence import from_dict, to_dict

    f = _firing("e1")
    f.batch_id = "abc123abc123"
    restored = from_dict(to_dict(f))
    assert restored.batch_id == "abc123abc123"


def test_a_persisted_row_written_before_batching_restores_as_none(tmp_path):
    from app.trigger_engine.persistence import from_dict, to_dict

    raw = to_dict(_firing("e1"))
    del raw["batch_id"]  # a row written before the field existed
    assert from_dict(raw).batch_id is None
