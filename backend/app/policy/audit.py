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
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .models import PendingAction

logger = logging.getLogger(__name__)


#: How much of a refused plan is recorded (PolicyAuditLog.record_refused).
REFUSED_LINES = 20
REFUSED_CHARS = 300


#: Refusal keys already recorded, per audit file: a small index, so a
#: refusal never reads the whole log. Seeded once per file from its tail
#: (_TAIL_BYTES), bounded to _SEEN_LIMIT keys (oldest dropped).
_SEEN: dict[str, OrderedDict[str, None]] = {}
_SEEN_LOCK = threading.Lock()
_SEEN_LIMIT = 2048
_TAIL_BYTES = 256 * 1024


def _first_refusal(path: Path, key: str) -> bool:
    """True the first time `key` is seen for this audit file (and records it)."""
    with _SEEN_LOCK:
        seen = _SEEN.get(str(path))
        if seen is None:
            seen = _SEEN[str(path)] = OrderedDict()
            try:
                with path.open("rb") as handle:
                    handle.seek(0, 2)
                    size = handle.tell()
                    handle.seek(max(size - _TAIL_BYTES, 0))
                    tail = handle.read().decode("utf-8", errors="ignore").splitlines()
            except FileNotFoundError:
                tail = []
            for line in tail:
                if '"refusal_key"' not in line:
                    continue
                try:
                    seen[str(json.loads(line).get("refusal_key"))] = None
                except json.JSONDecodeError:
                    continue
        if key in seen:
            return False
        seen[key] = None
        while len(seen) > _SEEN_LIMIT:
            seen.popitem(last=False)
        return True


def _forget_refusal(path: Path, key: str) -> None:
    with _SEEN_LOCK:
        seen = _SEEN.get(str(path))
        if seen is not None:
            seen.pop(key, None)


def _clip(text: object) -> str:
    text = str(text if text is not None else "")
    return text if len(text) <= REFUSED_CHARS else text[: REFUSED_CHARS - 1] + "…"


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
            # Whose run stated it: the audit list is filtered by it.
            "owner_id": action.owner_id,
            # How it was answered: via, confirming thread, user and message.
            "confirmation": action.confirmation,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
        return entry

    def record_grant_use(
        self,
        *,
        agent: str,
        user_id: str,
        tool: str,
        classes: list[str],
        targets: list[str],
        thread_id: str | None,
        rule_id: str | None,
        origin: str,
        origin_source: str,
        count_in_run: int,
        now: datetime | None = None,
        firing_id: str | None = None,
        write_id: str | None = None,
        source_label: str = "",
    ) -> dict:
        """A Tier 3 call that ran WITHOUT a confirmation because a standing
        grant covered it (Feature 006). The other half of Article VIII: nobody
        was in the loop, so the record is all a reviewer has, and it names the
        grant, the run (thread and rule) and what caused the call."""
        entry = {
            "kind": "grant-use",
            "at": (now or datetime.now()).isoformat(),
            "actor": self.actor,
            "agent": agent,
            "user_id": user_id,
            "tool": tool,
            "classes": list(classes),
            "targets": list(targets),
            "thread_id": thread_id,
            "rule_id": rule_id,
            "origin": origin,
            "origin_source": origin_source,
            "count_in_run": count_in_run,
            # Feature 006 run summary: which firing, the write's Undo id, and
            # what it came from in words (redacted; never the content's body).
            "firing_id": firing_id,
            "write_id": write_id,
            "source_label": source_label,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
        return entry

    def record_refused(
        self,
        *,
        tool: str,
        targets: list[str],
        reason: str,
        owner_id: str | None,
        thread_id: str | None,
        requester: str,
        origin: str,
        origin_source: str,
        turn_key: str = "",
        now: datetime | None = None,
    ) -> dict | None:
        """A plan refused BEFORE it became a card (it could not be applied),
        when it was not the user's own request: content or an automation led
        to it, so nobody may be reading the model's reply. Recorded where
        Tier 3 history is read (GET /api/policy/audit), so the attempt stays
        visible (FR-006); nothing was proposed, so there is nothing to
        confirm.

        Bounded: at most REFUSED_LINES targets of REFUSED_CHARS characters,
        the reason likewise, and ONE entry per thread and turn (`turn_key`):
        a model retrying a bad plan in a loop records it once. Returns None
        when this turn's refusal was already recorded."""
        key = f"{thread_id or ''}|{turn_key}"
        if turn_key and not _first_refusal(self.path, key):
            return None
        reason = _clip(reason)
        entry = {
            "kind": "refused-plan",
            "turn_key": turn_key,
            "refusal_key": key,
            "at": (now or datetime.now()).isoformat(),
            "actor": self.actor,
            "tier": 3,
            "tool": tool,
            "plan_as_stated": f"Refused before it was proposed: {reason}. Nothing was changed.",
            "targets": [_clip(t) for t in list(targets)[:REFUSED_LINES]],
            "authorised_by": None,
            "outcome": "refused",
            "reason": reason,
            "thread_id": thread_id,
            "requester": requester,
            "owner_id": owner_id,
            "origin": origin,
            "origin_source": origin_source,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, sort_keys=True) + "\n")
        except Exception:
            # Not written: the turn's refusal is not recorded yet, so a later
            # one in the same turn may still record it.
            if turn_key:
                _forget_refusal(self.path, key)
            raise
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
