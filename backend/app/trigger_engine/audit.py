"""Audit log (FR-012, FR-012a, Article VIII).

Feature 001 recorded that no audit log was required because every tool was
Tier 1 and no approval was relayed, and that the obligation would arrive with
the first feature that acts without a human in the loop. This is that feature.

Implemented BEFORE the delivery paths rather than after: audit logging is
cross-cutting, so landing it last means retrofitting call sites into paths
already written, and it is the first casualty if the phase is cut short.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .models import Firing

logger = logging.getLogger(__name__)


@dataclass
class AuditLog:
    """Append-only, local, one JSON object per line.

    ``actor`` is required and has no default. Article VIII's audit exists to
    make actions taken without a human in the loop *reviewable*, and a review
    asks two questions: what happened, and on whose behalf. An entry that
    answers only the first is the obligation under-delivering rather than met
    — it records that the assistant acted while omitting the account it acted
    as, which is the fact that determines what the action was permitted to
    reach.

    It is a constructor field rather than a per-firing one because today every
    firing in an engine acts as the same identity: `Rule` has no owner, and the
    injector's internal-auth calls all resolve to one user. When per-rule
    ownership arrives, this moves onto `Firing` and the recorded value becomes
    the rule's owner. Recording it per-log now is accurate, not a placeholder.
    """

    path: Path
    actor: str

    def record(self, firing: Firing, now: datetime) -> None:
        if firing.outcome is None:
            raise ValueError("a firing must be resolved before it is audited (FR-012)")
        entry = {
            "at": now.isoformat(),
            "actor": self.actor,
            "rule_id": firing.rule_id,
            "event_type": str(firing.event.type),
            "event_id": firing.event.event_id,
            "thread_id": firing.thread_id,
            "outcome": str(firing.outcome),
            "reason": firing.reason,
            "delivered_chars": len(firing.reply or ""),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")

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
