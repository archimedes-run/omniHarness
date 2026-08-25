"""Durable pending Tier 3 actions (FR-028, FR-029, FR-030, FR-019).

WHY DURABLE AND WORKER-INDEPENDENT. The gateway serves from several worker
processes behind one socket. A plan stated by one worker will usually be
answered through another, so an in-memory record would make a correctly
confirmed action silently never run — the other workers answer "nothing
pending". This is the same conclusion Feature 002 reached for its deferred
firings, applied to the same shape of state.

The policy layer does NOT run in the trigger engine's elected worker. Election
is for background work; a policy decision happens wherever the run lands. Hence
durable storage rather than reusing election.

WHY RESOLVED TARGETS, NOT CRITERIA. The user confirmed a plan, not a category of
action. Re-resolving "meetings on Tuesday" at execution time could act on a set
they never saw. So the specific items are recorded and re-checked, and drift is
a decline with restatement rather than an approximation.

WHY THE CLAIM IS ATOMIC. Several workers can read the same record. Two of them
acting on a calendar cleanup deletes twice — which is silent — and creates holds
twice, which is visible clutter.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .models import Outcome, PendingAction, Tier

logger = logging.getLogger(__name__)


def _to_dict(action: PendingAction) -> dict:
    return {
        "id": action.id,
        "plan_text": action.plan_text,
        "tool_name": action.tool_name,
        "arguments": action.arguments,
        "targets": list(action.targets),
        "tier_at_statement": int(action.tier_at_statement),
        "expires_at": action.expires_at.isoformat(),
        "thread_id": action.thread_id,
        "requester": action.requester,
        "delegation_chain": list(action.delegation_chain),
        "claimed_by": action.claimed_by,
        "outcome": str(action.outcome) if action.outcome else None,
        "outcome_reason": action.outcome_reason,
    }


def _from_dict(raw: dict) -> PendingAction:
    action = PendingAction(
        plan_text=raw["plan_text"],
        tool_name=raw["tool_name"],
        arguments=raw.get("arguments") or {},
        targets=list(raw.get("targets") or []),
        tier_at_statement=Tier(int(raw["tier_at_statement"])),
        expires_at=datetime.fromisoformat(raw["expires_at"]),
        thread_id=raw.get("thread_id"),
        requester=raw.get("requester") or "lead_agent",
        delegation_chain=tuple(raw.get("delegation_chain") or ()),
        id=raw["id"],
    )
    action.claimed_by = raw.get("claimed_by")
    if raw.get("outcome"):
        action.outcome = Outcome(raw["outcome"])
    action.outcome_reason = raw.get("outcome_reason") or ""
    return action


@dataclass
class PendingStore:
    """One JSON file per pending action, so a claim is a filesystem operation.

    Deliberately NOT one file holding every action: an atomic claim across
    processes needs an operation the OS makes indivisible, and `os.link` on a
    per-action file gives that with no lock, lease or coordination service. A
    shared file would need read-modify-write, which is the race this exists to
    prevent.
    """

    directory: Path

    def __post_init__(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, action_id: str) -> Path:
        return self.directory / f"{action_id}.json"

    def _claim_path(self, action_id: str) -> Path:
        return self.directory / f"{action_id}.claim"

    def save(self, action: PendingAction) -> PendingAction:
        path = self._path(action.id)
        fd, tmp = tempfile.mkstemp(dir=str(self.directory), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(_to_dict(action), handle, indent=2, sort_keys=True)
            os.replace(tmp, path)  # atomic
        finally:
            Path(tmp).unlink(missing_ok=True)
        return action

    def get(self, action_id: str) -> PendingAction | None:
        try:
            return _from_dict(json.loads(self._path(action_id).read_text(encoding="utf-8")))
        except FileNotFoundError:
            return None
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.error("pending action %s is unreadable: %s", action_id, exc)
            return None

    def open_actions(self, now: datetime) -> list[PendingAction]:
        """Unresolved, unexpired actions — what a confirmation can address."""
        out = []
        for path in sorted(self.directory.glob("*.json")):
            action = self.get(path.stem)
            if action and action.outcome is None and not action.is_expired(now):
                out.append(action)
        return out

    def claim(self, action_id: str, claimant: str) -> PendingAction | None:
        """Take exclusive ownership. Returns the claimed action for exactly one
        caller, None for everyone else (FR-030).

        `os.link` fails if the destination exists, and the OS makes that check
        and the creation one indivisible operation — across processes, without a
        lock. A read-then-write would let two workers both see "unclaimed".

        RETURNS THE ACTION rather than a boolean, deliberately. A caller that
        claims and then re-reads has a window between the two in which another
        process can write the record, and the caller sees a version without its
        own claim on it — which surfaces as an audit entry that does not say who
        authorised the execution. Handing back the object it just wrote removes
        the window rather than narrowing it.
        """
        source, claim = self._path(action_id), self._claim_path(action_id)
        if not source.exists():
            return None
        try:
            os.link(source, claim)
        except FileExistsError:
            return None
        except OSError as exc:
            logger.error("could not claim pending action %s: %s", action_id, exc)
            return None

        action = self.get(action_id)
        if action is None:
            return None
        action.claimed_by = claimant
        self.save(action)
        return action

    def resolve(self, action: PendingAction, outcome: Outcome, reason: str = "") -> PendingAction:
        action.resolve(outcome, reason)
        return self.save(action)

    def expire_due(self, now: datetime) -> list[PendingAction]:
        """FR-019: expire without executing. Returns what expired, so the user
        can be told rather than seeing silence."""
        expired = []
        for path in sorted(self.directory.glob("*.json")):
            action = self.get(path.stem)
            if action and action.outcome is None and action.is_expired(now):
                self.resolve(action, Outcome.EXPIRED, f"not confirmed before {action.expires_at.isoformat()}")
                expired.append(action)
        return expired


def targets_still_match(action: PendingAction, current_targets: list[str]) -> bool:
    """FR-029. Recorded targets must still describe the world.

    Order-insensitive but membership-exact: confirming a plan to decline four
    specific meetings must not execute against three, or against four different
    ones.
    """
    return sorted(action.targets) == sorted(current_targets)
