"""Tests for the idempotency-key helper (Phase 0 — definition only)."""

from __future__ import annotations

import pytest

from omniharness.platform.idempotency import compute_idempotency_key, stable_hash

# ---------------------------------------------------------------------------
# stable_hash
# ---------------------------------------------------------------------------


def test_stable_hash_deterministic():
    assert stable_hash({"a": 1, "b": 2}) == stable_hash({"a": 1, "b": 2})


def test_stable_hash_key_order_independent():
    assert stable_hash({"a": 1, "b": 2}) == stable_hash({"b": 2, "a": 1})


def test_stable_hash_nested_key_order_independent():
    assert stable_hash({"x": {"a": 1, "b": 2}}) == stable_hash({"x": {"b": 2, "a": 1}})


def test_stable_hash_different_payloads_differ():
    assert stable_hash({"a": 1}) != stable_hash({"a": 2})


def test_stable_hash_returns_64_char_hex():
    h = stable_hash({"foo": "bar"})
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


# ---------------------------------------------------------------------------
# compute_idempotency_key — scheduled form
# ---------------------------------------------------------------------------


def test_scheduled_key_deterministic():
    k1 = compute_idempotency_key("wf-1", scheduled_time="2026-07-01T09:00:00Z")
    k2 = compute_idempotency_key("wf-1", scheduled_time="2026-07-01T09:00:00Z")
    assert k1 == k2


def test_scheduled_key_format():
    k = compute_idempotency_key("wf-abc", scheduled_time="2026-07-01T09:00:00Z")
    assert k.startswith("wf:wf-abc:sched:")


def test_scheduled_key_different_times_differ():
    k1 = compute_idempotency_key("wf-1", scheduled_time="2026-07-01T09:00:00Z")
    k2 = compute_idempotency_key("wf-1", scheduled_time="2026-07-01T10:00:00Z")
    assert k1 != k2


def test_scheduled_key_different_workflows_differ():
    k1 = compute_idempotency_key("wf-1", scheduled_time="2026-07-01T09:00:00Z")
    k2 = compute_idempotency_key("wf-2", scheduled_time="2026-07-01T09:00:00Z")
    assert k1 != k2


# ---------------------------------------------------------------------------
# compute_idempotency_key — trigger form
# ---------------------------------------------------------------------------


def test_trigger_key_deterministic():
    payload = {"event": "push", "repo": "omniHarness", "ref": "main"}
    k1 = compute_idempotency_key("wf-1", trigger_payload=payload)
    k2 = compute_idempotency_key("wf-1", trigger_payload=payload)
    assert k1 == k2


def test_trigger_key_payload_key_order_independent():
    p1 = {"event": "push", "repo": "omniHarness"}
    p2 = {"repo": "omniHarness", "event": "push"}
    assert compute_idempotency_key("wf-1", trigger_payload=p1) == compute_idempotency_key("wf-1", trigger_payload=p2)


def test_trigger_key_format():
    k = compute_idempotency_key("wf-xyz", trigger_payload={"x": 1})
    assert k.startswith("wf:wf-xyz:trig:")


def test_trigger_key_different_payloads_differ():
    k1 = compute_idempotency_key("wf-1", trigger_payload={"event": "push"})
    k2 = compute_idempotency_key("wf-1", trigger_payload={"event": "pr"})
    assert k1 != k2


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


def test_raises_if_neither_provided():
    with pytest.raises(ValueError):
        compute_idempotency_key("wf-1")


def test_raises_if_both_provided():
    with pytest.raises(ValueError):
        compute_idempotency_key("wf-1", scheduled_time="2026-01-01T00:00:00Z", trigger_payload={"x": 1})
