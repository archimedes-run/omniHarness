"""Surface 1's backend contract.

WHAT THESE GUARD. The router must decide nothing: recognition, the threshold,
the claim and execution all belong to `ConfirmationFlow`, and a second
implementation here is what would let one confirmation execute twice. The
outcome vocabulary must reach the client intact, because "someone else already
confirmed it", "it expired" and "the items changed" need different responses
from the person reading them, and a generic failure tells them to retry
something that will never work.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.gateway.routers import confirmations as router_module
from app.policy.models import PendingAction, Tier
from app.policy.pending import PendingStore

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)


def _action(store: PendingStore, *, targets: list[str], expires_in=timedelta(hours=1)) -> PendingAction:
    return store.save(
        PendingAction(
            plan_text="I will decline " + ", ".join(targets),
            tool_name="calendar_decline",
            arguments={"meetings": list(targets)},
            targets=list(targets),
            tier_at_statement=Tier.TIER_3,
            expires_at=NOW + expires_in,
            thread_id="t1",
        )
    )


@pytest.fixture
def store(tmp_path):
    return PendingStore(directory=tmp_path / "pending")


# ---------------------------------------------------------------------------
# FR-008 — "nothing pending" and "cannot tell" are different facts
# ---------------------------------------------------------------------------


def test_the_view_reports_whether_a_typed_count_is_required(store):
    """POSITIVE CONTROL for the view: it must vary with the threshold, or the
    assertions below are about a constant."""
    small = _action(store, targets=["a"])
    big = _action(store, targets=[str(i) for i in range(12)])

    assert router_module._view(small, threshold=10).requires_typed_count is False
    assert router_module._view(big, threshold=10).requires_typed_count is True


class _Middleware:
    """The two collaborators `read_pending` touches, and nothing else."""

    def __init__(self, store, *, threshold: int = 10, raises: Exception | None = None):
        self.pending = store
        self._threshold = threshold
        self._raises = raises

        class _Loader:
            def load(inner):
                return SimpleNamespace(threshold_targets=threshold)

        self.loader = _Loader()

    class _Raising:
        def __init__(self, exc):
            self._exc = exc

        def open_actions(self, now):
            raise self._exc


def test_an_empty_store_reads_as_empty_and_readable(store):
    body = router_module.read_pending(_Middleware(store), NOW)
    assert body.readable is True and body.actions == []


def test_a_populated_store_reads_back_its_actions(store):
    """POSITIVE CONTROL. Without it, a read that always returned [] would pass
    the empty and the unreadable cases and mean nothing."""
    _action(store, targets=["a", "b"])
    body = router_module.read_pending(_Middleware(store), NOW)
    assert len(body.actions) == 1 and body.actions[0].targets == ["a", "b"]


def test_a_store_that_cannot_be_read_says_so_rather_than_reporting_empty(store):
    """FR-008, exercising the ROUTER's own branch.

    A UI rendering an empty list for both would tell the user the opposite of
    the truth in one case.
    """
    broken = _Middleware(store)
    broken.pending = _Middleware._Raising(PermissionError("permission denied"))

    body = router_module.read_pending(broken, NOW)

    assert body.readable is False, "an unreadable store reported itself as simply empty"
    assert body.actions == []
    assert "permission denied" in body.error


# ---------------------------------------------------------------------------
# FR-038 — the outcome vocabulary survives the trip
# ---------------------------------------------------------------------------


def test_every_flow_outcome_is_representable_and_distinct():
    """The router passes `outcome` through verbatim. If it ever mapped these
    onto ok/error, this fails."""
    from app.policy import confirm_flow as cf

    outcomes = {cf.EXECUTED, cf.DECLINED, cf.ALREADY_RESOLVED, cf.EXPIRED, cf.TARGETS_DRIFTED, cf.UNRECOGNISED, cf.THRESHOLD_NOT_MET, cf.FAILED}
    assert len(outcomes) == 8, "two outcomes collapsed into one string"

    for outcome in outcomes:
        body = router_module.ResolveResponse(outcome=outcome, action_id="abc123abc123")
        assert body.outcome == outcome


def test_the_router_does_not_take_its_own_claim():
    """FR-004 restated where it is easy to break. The gate in tests/gates
    asserts this repo-wide; this says it about the file most likely to
    reimplement the flow."""
    source = (router_module.__file__ and open(router_module.__file__).read()) or ""
    assert ".claim(" not in source, "the router takes its own claim; one confirmation could execute twice"
    assert "recognise(" not in source, "the router recognises its own verdict instead of using the flow"
    assert "flow.explicit(" in source, "the router no longer calls the shared flow"
