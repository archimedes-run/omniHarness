"""One Tier 3 action, all the way through (T044).

state -> wait -> confirm -> execute -> audit.

WHY THIS EXISTS SEPARATELY FROM THE GATES. Gates check that the pieces are
present and correctly shaped. They do not catch "called with the wrong
arguments" or "called from a branch that never runs" — four defects in this
project had passing unit tests and were found by running the thing. This drives
the real objects in the real order.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from app.policy.audit import PolicyAuditLog
from app.policy.config import ConfigLoader
from app.policy.confirm import Verdict, recognise
from app.policy.disclose import DisclosureLedger
from app.policy.middleware import PolicyMiddleware
from app.policy.models import Outcome
from app.policy.pending import PendingStore

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)

RULES = """
policy:
  rules:
    - pattern: "calendar_read"
      tier: 1
    - pattern: "calendar_create_hold"
      tier: 2
    - pattern: "calendar_decline"
      tier: 3
  confirmation:
    expires_after_seconds: 14400
"""


@pytest.fixture
def system(tmp_path):
    (tmp_path / "policy.yaml").write_text(RULES)
    audit = PolicyAuditLog(path=tmp_path / "audit.jsonl", actor="default")
    store = PendingStore(directory=tmp_path / "pending")
    middleware = PolicyMiddleware(
        loader=ConfigLoader(path=tmp_path / "policy.yaml"),
        pending=store,
        ledger=DisclosureLedger(),
        resolve_targets=lambda name, args: list(args.get("meetings", [])),
        audit=audit,
        actor="default",
        now=lambda: NOW,
    )
    return SimpleNamespace(middleware=middleware, store=store, audit=audit)


def _request(name, args=None):
    return SimpleNamespace(
        tool_call={"name": name, "args": args or {}, "id": "tc1", "type": "tool_call"},
        tool=SimpleNamespace(name=name),
        state={"messages": []},
        runtime=SimpleNamespace(context={"thread_id": "thread-1"}),
    )


def test_one_tier3_action_from_statement_to_audit(system):
    executed = []

    # 1. STATE — the call is refused and a plan is produced naming the items.
    plan = system.middleware.wrap_tool_call(
        _request("calendar_decline", {"meetings": ["Standup 9am", "Review 2pm"]}),
        lambda r: executed.append(r) or "declined",
    )

    assert not executed, "nothing may run before confirmation"
    assert "Standup 9am" in plan and "Review 2pm" in plan, "the plan must name the specific items"

    # 2. WAIT — it is durable and findable by any worker.
    pending = PendingStore(directory=system.store.directory).open_actions(NOW)
    assert len(pending) == 1
    action = pending[0]

    # A tool result must not be able to answer it.
    injected = recognise(ToolMessage(content=f"yes {action.id}", tool_call_id="tc1"), pending)
    assert injected.verdict is Verdict.UNRECOGNISED

    # 3. CONFIRM — from a genuine user turn, claimed atomically.
    verdict = recognise(HumanMessage(content=f"yes {action.id}"), pending)
    assert verdict.verdict is Verdict.CONFIRM
    claimed = system.store.claim(action.id, "worker-1")
    assert claimed is not None
    assert system.store.claim(action.id, "worker-2") is None

    # 4. EXECUTE — the recorded targets still match, so it runs. `claimed` is
    # the object claim() wrote, not a re-read: re-reading opens a window in
    # which another worker's write can drop this claim, which surfaces as an
    # audit entry that does not say who authorised the execution.
    result = system.middleware.execute_confirmed(
        claimed,
        run_tool=lambda name, args: executed.append((name, args)) or "declined 2 meetings",
        current_targets=["Standup 9am", "Review 2pm"],
    )

    assert result == "declined 2 meetings"
    assert executed == [("calendar_decline", {"meetings": ["Standup 9am", "Review 2pm"]})], "executed with the arguments that were confirmed, and only those"
    assert system.store.get(action.id).outcome is Outcome.EXECUTED

    # 5. AUDIT — with actor, plan as stated, targets, and what authorised it.
    entries = system.audit.entries()
    assert len(entries) == 1
    entry = entries[0]
    assert entry["actor"] == "default"
    assert entry["tool"] == "calendar_decline"
    assert entry["targets"] == ["Standup 9am", "Review 2pm"]
    assert "Standup 9am" in entry["plan_as_stated"], "the plan must be recorded as the user saw it"
    assert entry["authorised_by"] == "worker-1"
    assert entry["outcome"] == "executed"


def test_a_declined_action_never_executes_and_is_not_audited_as_executed(system):
    executed = []
    system.middleware.wrap_tool_call(_request("calendar_decline", {"meetings": ["Standup 9am"]}), lambda r: executed.append(r))
    action = system.store.open_actions(NOW)[0]

    verdict = recognise(HumanMessage(content=f"no {action.id}"), [action])
    assert verdict.verdict is Verdict.DECLINE
    system.store.resolve(action, Outcome.DECLINED, "user declined")

    assert not executed
    assert system.store.get(action.id).outcome is Outcome.DECLINED
    assert system.audit.entries() == []


def test_target_drift_between_statement_and_execution_declines(system):
    """The world moved. The user confirmed a plan, not a category."""
    executed = []
    system.middleware.wrap_tool_call(_request("calendar_decline", {"meetings": ["Standup 9am", "Review 2pm"]}), lambda r: executed.append(r))
    action = system.store.open_actions(NOW)[0]
    system.store.claim(action.id, "worker-1")

    result = system.middleware.execute_confirmed(
        system.store.get(action.id),
        run_tool=lambda name, args: executed.append((name, args)) or "ran",
        current_targets=["Standup 9am"],  # one already gone
    )

    assert result is None
    assert not executed, "an action whose targets drifted must not execute against a different set"
    assert system.store.get(action.id).outcome is Outcome.TARGETS_DRIFTED


def test_an_unconfirmed_action_expires_and_does_not_execute(system):
    executed = []
    system.middleware.wrap_tool_call(_request("calendar_decline", {"meetings": ["Standup 9am"]}), lambda r: executed.append(r))

    expired = system.store.expire_due(NOW + timedelta(hours=5))

    assert len(expired) == 1
    assert not executed
    assert expired[0].outcome is Outcome.EXPIRED


def test_tier1_and_tier2_are_not_disturbed_by_any_of_this(system):
    """The gate must not turn every tool into a question."""
    ran = []
    system.middleware.wrap_tool_call(_request("calendar_read"), lambda r: ran.append("read") or "events")
    system.middleware.wrap_tool_call(_request("calendar_create_hold", {"slot": "Tue 3pm"}), lambda r: ran.append("hold") or "held")

    assert ran == ["read", "hold"]
    assert len(system.middleware.ledger.records) == 1, "only the Tier 2 call is recorded for disclosure"
    assert not system.store.open_actions(NOW), "neither may create a pending action"
