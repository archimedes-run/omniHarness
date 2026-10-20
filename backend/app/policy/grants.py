"""Standing grants: what an agent may do on its own in a scheduled run (Feature 006 Phase 3, FR-302).

THE TIERS DECIDE FIRST, AND TIER 3 ALWAYS ASKS (user decision 2026-10-20). A
grant never skips a confirmation. The routine, reversible ledger ops (create
or update a task, add a note) are Tier 2 in the shipped rules: run, then
disclose. Grants only change how those GRANT-GOVERNED Tier 2 calls behave in a
SCHEDULED run, where nobody reads the reply as it happens:

  * IN CHAT a grant changes nothing: Tier 2 runs and the reply says so.
  * IN A SCHEDULED RUN (provenance.is_synthetic_turn) a grant-governed Tier 2
    call runs only when a granted class covers every change in it, and within
    the cap; otherwise it waits on Home's "Waiting on you" like a proposal.
  * REVERSIBLE TIER 2 ONLY. A class is grantable only when the rule deciding
    its tool is Tier 2 and labelled `reversible: true` (default_rules.yaml);
    a call whose tier an exception raised is Tier 3 and asks. The API refuses
    to store a grant for anything else, and dispatch re-checks, so a
    hand-edited config cannot widen it.
  * CONTENT-DERIVED RUNS STILL USE IT (user decision 2026-10-20): what caused
    the call (the schedule's turn, or a page the agent read) is recorded with
    every granted action, not used to refuse it.
  * CAPPED PER RUN: at most GRANT_CAP_PER_RUN granted ACTIONS in one run (a
    ledger_apply with N changes is N actions). Past that, each further call
    waits.
  * AUDITED: every use is a line in the policy audit log with its origin, and
    the run's reply discloses it.
  * REVOCABLE, EFFECTIVE FROM THE NEXT CALL: the grant is read from the
    agent's current version on every call (config_versions), never cached.

Grants are part of the agent's config ("autonomy": [class ids]) and are
written only through the versioned store, by the Autonomy action alone: undo
and every other edit keep the grants as they are (config_versions.write_agent).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from omniharness.config import config_versions

from .classify import classify
from .config import RuleSet
from .models import PolicyDecision, Tier

#: The most granted ACTIONS one scheduled run may take (user decision
#: 2026-10-20). A ledger_apply with N changes is N actions. The 21st waits.
GRANT_CAP_PER_RUN = 20
AUTONOMY_KEY = config_versions.AUTONOMY_KEY


@dataclass(frozen=True)
class ActionClass:
    id: str
    label: str
    #: What it allows, in plain words, shown beside the checkbox.
    allows: str
    tool: str

    def covers(self, change: dict) -> bool:
        op = change.get("op")
        status = change.get("status")
        if self.id == "tasks":
            return op == "create_task" or (op == "update_task" and status != "dropped")
        if self.id == "notes":
            return op == "add_note"
        if self.id == "archive":
            return op == "update_task" and status == "dropped"
        return False


ACTION_CLASSES: tuple[ActionClass, ...] = (
    ActionClass("tasks", "Create and update tasks", "Add tasks to your projects, and change a task's title, due date or status. It never drops a task.", "ledger_apply"),
    ActionClass("notes", "Add notes and decisions", "Write a note or a decision into a project. You can edit or remove it later.", "ledger_apply"),
    ActionClass("archive", "Archive stale tasks", "Mark a task dropped, which hides it from the lists. Changing its status brings it back.", "ledger_apply"),
)
BY_ID = {c.id: c for c in ACTION_CLASSES}


def rule_for(tool: str, ruleset: RuleSet) -> PolicyDecision:
    return classify(tool, {}, ruleset)


def grantable(class_id: str, ruleset: RuleSet) -> tuple[bool, str]:
    """(may it be granted, why not). Asked of the RULES IN FORCE, so a class
    whose tool is relabelled irreversible stops being grantable at once."""
    if class_id.startswith("tool:"):
        decision = rule_for(class_id[5:], ruleset)
        if decision.deciding_rule is None or decision.deciding_rule.reversible is not True:
            return False, f"{class_id[5:]} can't be undone, so it always waits for you"
        return False, f"{class_id[5:]} is granted through its named action classes only"
    action = BY_ID.get(class_id)
    if action is None:
        return False, f"unknown action class {class_id!r}"
    rule = rule_for(action.tool, ruleset).deciding_rule
    if rule is None or rule.reversible is not True:
        return False, f"{action.label}: its tool ({action.tool}) is not labelled reversible in the rules in force, so it always waits for you"
    if rule.tier is not Tier.TIER_2:
        return False, f"{action.label}: its tool ({action.tool}) is Tier {int(rule.tier)} in the rules in force, and only a Tier 2 action can be granted; Tier 3 always asks you"
    return True, ""


def covering_classes(decision: PolicyDecision, arguments: dict[str, Any], granted: list[str], ruleset: RuleSet) -> list[str] | None:
    """The granted classes that together cover this call, or None.

    None unless the call is Tier 2 (a grant never covers Tier 3), EVERY change
    in it is covered by a granted, grantable class, the deciding rule is
    labelled reversible, and no exception raised the tier.
    """
    rule = decision.deciding_rule
    if decision.tier is not Tier.TIER_2 or rule is None or rule.reversible is not True or decision.raised_by is not None:
        return None
    usable = [BY_ID[c] for c in granted if c in BY_ID and BY_ID[c].tool == decision.tool_name and grantable(c, ruleset)[0]]
    if not usable:
        return None
    changes = arguments.get("changes")
    if not isinstance(changes, list) or not changes:
        return None
    used: list[str] = []
    for change in changes:
        if not isinstance(change, dict):
            return None
        match = next((c for c in usable if c.covers(change)), None)
        if match is None:
            return None
        if match.id not in used:
            used.append(match.id)
    return used


def granted_classes(user_id: str, agent: str) -> list[str]:
    """The agent's grants as of its CURRENT version: read on every call, so a
    revocation applies from the next one."""

    try:
        versions = config_versions.agent_history(user_id, agent)
    except (ValueError, OSError):
        return []
    if not versions:
        # Grants come ONLY from the versioned store, where the Autonomy action
        # alone writes them. An agent with no history has none, whatever its
        # config.yaml on disk says (a restored backup, a migration, a hand
        # edit): that is reported, never honoured.
        _report_unversioned_grants(user_id, agent)
        return []
    granted = ((versions[-1].snapshot or {}).get("config") or {}).get(AUTONOMY_KEY) or []
    return [g for g in granted if isinstance(g, str)]


def _report_unversioned_grants(user_id: str, agent: str) -> None:
    import logging

    try:
        on_disk = ((config_versions.current_agent_snapshot(user_id, agent) or {}).get("config") or {}).get(AUTONOMY_KEY)
    except (ValueError, OSError):
        return
    if on_disk:
        logging.getLogger(__name__).warning("agent %s has grants %s in its config.yaml but no versioned Autonomy record; they are ignored until granted on its Autonomy tab", agent, on_disk)


def _norm(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def change_signatures(arguments: dict[str, Any]) -> set[tuple[str, ...]]:
    """What a ledger_apply would do, normalised (case and whitespace): one
    (op, project, task, title-or-note, status) per change. Two calls that
    share any signature are "the same write" for the declined-stays-declined
    rule, however the model rephrased the rest."""
    changes = arguments.get("changes")
    if not isinstance(changes, list):
        return set()
    out = set()
    for c in changes:
        if isinstance(c, dict):
            out.add((_norm(c.get("op")), _norm(c.get("project")), _norm(c.get("task")), _norm(c.get("title") or c.get("decided")), _norm(c.get("status"))))
    return out


def governed_by_grants(tool_name: str) -> bool:
    """A tool some action class names: in a scheduled run, its Tier 2 calls
    run only under a grant."""
    return any(c.tool == tool_name for c in ACTION_CLASSES)


def always_waits(ruleset: RuleSet) -> list[str]:
    """Tier 3 rules: what never runs without the user, grant or not.
    Generated from the rules in force (design-notes #13), never hand-written."""
    return [r.pattern for r in ruleset.rules if r.tier is Tier.TIER_3]


def action_count(arguments: dict[str, Any]) -> int:
    """How many actions a call takes, for the cap: one per change (a call
    covering_classes accepted always has a non-empty list of them)."""
    changes = arguments.get("changes")
    return len(changes) if isinstance(changes, list) else 1


@dataclass(frozen=True)
class GrantedCall:
    """A call a grant lets run: its classes, how many actions it takes, and
    the run's count once they are reserved."""

    classes: list[str]
    actions: int
    total: int
    run_key: str


class GrantRunCounts:
    """Granted actions per scheduled run, DURABLE and ATOMIC.

    Keyed by the trigger firing (trigger_firing_id: the event's fingerprint),
    which is the same for every attempt at that firing, so a retry or a resume
    continues the count rather than starting a fresh 20. A reservation is one
    SQLite write transaction (BEGIN IMMEDIATE): the check and the increment
    cannot interleave, across threads, event-loop tasks or worker processes,
    so parallel calls in one step cannot take the run past the cap. The
    actions are reserved BEFORE the call runs; a call that raises gives its
    reservation back.
    """

    #: Rows older than this are dropped on write; a firing is long settled.
    KEEP = timedelta(days=30)

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = self._connect()
        try:
            db.execute("CREATE TABLE IF NOT EXISTS grant_run_counts (run_key TEXT PRIMARY KEY, used INTEGER NOT NULL, updated_at TEXT NOT NULL)")
        finally:
            db.close()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=30, isolation_level=None)

    def reserve(self, run_key: str, actions: int, cap: int) -> int | None:
        """Add `actions` to the run's count if the total stays within `cap`.
        The new total, or None (nothing reserved) when it would not fit."""
        now = datetime.now(UTC)
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO grant_run_counts (run_key, used, updated_at) VALUES (?, 0, ?)", (run_key, now.isoformat()))
            cursor = db.execute(
                "UPDATE grant_run_counts SET used = used + ?, updated_at = ? WHERE run_key = ? AND used + ? <= ?",
                (actions, now.isoformat(), run_key, actions, cap),
            )
            total = db.execute("SELECT used FROM grant_run_counts WHERE run_key = ?", (run_key,)).fetchone()[0]
            db.execute("DELETE FROM grant_run_counts WHERE updated_at < ?", ((now - self.KEEP).isoformat(),))
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()
        return int(total) if cursor.rowcount == 1 else None

    def release(self, run_key: str, actions: int) -> None:
        db = self._connect()
        try:
            db.execute("UPDATE grant_run_counts SET used = MAX(used - ?, 0) WHERE run_key = ?", (actions, run_key))
        finally:
            db.close()

    def used(self, run_key: str) -> int:
        db = self._connect()
        try:
            row = db.execute("SELECT used FROM grant_run_counts WHERE run_key = ?", (run_key,)).fetchone()
        finally:
            db.close()
        return int(row[0]) if row else 0
