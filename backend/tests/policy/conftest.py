"""Shared construction for the confirmation-flow tests.

A conftest rather than a helper module because test directories carry no
`__init__.py` here, so a sibling import has no package to be relative to.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.policy.audit import PolicyAuditLog
from app.policy.config import ConfigLoader
from app.policy.confirm_flow import ConfirmationFlow
from app.policy.disclose import DisclosureLedger
from app.policy.middleware import PolicyMiddleware
from app.policy.models import PendingAction, Tier
from app.policy.pending import PendingStore

FLOW_NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)


def _rules(threshold: int) -> str:
    return f"""
policy:
  rules:
    - pattern: "calendar_decline"
      tier: 3
  confirmation:
    expires_after_seconds: 14400
    threshold_targets: {threshold}
"""


@pytest.fixture
def build_flow(tmp_path):
    def build(*, threshold: int = 10, now: datetime = FLOW_NOW):
        (tmp_path / "policy.yaml").write_text(_rules(threshold))
        store = PendingStore(directory=tmp_path / "pending")
        audit = PolicyAuditLog(path=tmp_path / "audit.jsonl", actor="default")
        middleware = PolicyMiddleware(
            loader=ConfigLoader(path=tmp_path / "policy.yaml"),
            pending=store,
            ledger=DisclosureLedger(),
            audit=audit,
            actor="default",
            resolve_targets=lambda name, args: list(args.get("meetings", [])),
            now=lambda: now,
        )
        ran: list[tuple] = []

        def run_tool(name, arguments):
            ran.append((name, arguments))
            return f"declined {len(arguments.get('meetings', []))}"

        return SimpleNamespace(
            store=store,
            audit=audit,
            middleware=middleware,
            flow=ConfirmationFlow(store=store, middleware=middleware, now=lambda: now),
            ran=ran,
            run_tool=run_tool,
            now=now,
        )

    return build


@pytest.fixture
def make_pending():
    def make(system, *, targets, expires_in=timedelta(hours=1)) -> PendingAction:
        return system.store.save(
            PendingAction(
                plan_text=f"I will decline {len(targets)} meetings: " + ", ".join(targets),
                tool_name="calendar_decline",
                arguments={"meetings": list(targets)},
                targets=list(targets),
                tier_at_statement=Tier.TIER_3,
                expires_at=system.now + expires_in,
                thread_id="t1",
            )
        )

    return make
