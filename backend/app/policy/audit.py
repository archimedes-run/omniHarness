"""Tier 3 executions in the audit log (FR-011, SC-011, Article VIII).

Extends Feature 002's live audit log rather than starting a second one. Two
audit trails would have to be reconciled by whoever reads them back, and the
whole point of the log is that a reviewer does not have to reconstruct what
happened.

Article VIII's audit exists to make actions taken without a human in the loop
reviewable. A Tier 3 action HAS a human in the loop — that is the tier's whole
definition — so what the entry must capture is not merely that it happened, but
WHAT WAS AUTHORISED: the plan exactly as the user saw it, the specific items,
and what constituted the authorisation. Recording only the tool name would leave
a reviewer unable to tell an approved action from an overreaching one.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .models import PendingAction

logger = logging.getLogger(__name__)


@dataclass
class PolicyAuditLog:
    """Append-only, one JSON object per line — the same shape and file
    convention as the trigger engine's log, so an operator reads one format."""

    path: Path
    actor: str

    def record_tier3(self, action: PendingAction, actor: str | None = None, now: datetime | None = None) -> dict:
        if action.outcome is None:
            raise ValueError("a Tier 3 action must be resolved before it is audited — an entry for an action still in flight records a decision nobody made")
        entry = {
            "at": (now or datetime.now()).isoformat(),
            "actor": actor or self.actor,
            "tier": int(action.tier_at_statement),
            "tool": action.tool_name,
            # The plan AS STATED, verbatim. Not a summary: a reviewer needs to
            # see what the user actually agreed to, not a paraphrase of it.
            "plan_as_stated": action.plan_text,
            "targets": list(action.targets),
            "authorised_by": action.claimed_by,
            "outcome": str(action.outcome),
            "reason": action.outcome_reason,
            "action_id": action.id,
            "thread_id": action.thread_id,
            "requester": action.requester,
            "delegation_chain": list(action.delegation_chain),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
        return entry

    def entries(self) -> list[dict]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        out = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                logger.debug("skipping unparseable audit line")
        return out
