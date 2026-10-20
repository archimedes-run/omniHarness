"""Standing grants: what an agent may do on its own in a scheduled run (Feature 006 Phase 3, FR-302).

Nobody is there to ask in a scheduled run, so an agent may be given standing
permission for a few REVERSIBLE action classes. The rules, each enforced here
and in PolicyMiddleware at the tool-dispatch chokepoint, not only in the UI:

  * SCHEDULED RUNS ONLY. A grant applies when the turn was injected by the
    trigger engine (provenance.is_synthetic_turn). In chat it never applies:
    the user is there, and Tier 3 asks.
  * REVERSIBLE ONLY. A class is grantable only when the rule deciding its tool
    is labelled `reversible: true` (default_rules.yaml), and a call whose tier
    an exception raised is never covered. The API refuses to store a grant for
    anything else, and dispatch re-checks, so a hand-edited config cannot
    widen it.
  * CONTENT-DERIVED RUNS STILL USE IT (user decision 2026-10-20): what caused
    the call (the schedule's turn, or a page the agent read) is recorded with
    every granted action, not used to refuse it.
  * CAPPED PER RUN: at most GRANT_CAP_PER_RUN granted actions in one run.
    Past that, each further one waits as an ordinary Tier 3 proposal, which
    is what Home's "Waiting on you" lists.
  * AUDITED: every use is a line in the policy audit log with its origin, and
    the run's reply discloses it.
  * REVOCABLE, EFFECTIVE FROM THE NEXT CALL: the grant is read from the
    agent's current version on every call (config_versions), never cached.

Grants are part of the agent's config ("autonomy": [class ids]) and are
written only through the versioned store, so each grant and revocation is a
version with who and when, and can be undone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .classify import classify
from .config import RuleSet
from .models import PolicyDecision, Tier

#: The most granted actions one scheduled run may take (user decision
#: 2026-10-20). The 21st waits for the user.
GRANT_CAP_PER_RUN = 20
AUTONOMY_KEY = "autonomy"


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
    decision = rule_for(action.tool, ruleset)
    if decision.deciding_rule is None or decision.deciding_rule.reversible is not True:
        return False, f"{action.label}: its tool ({action.tool}) is not labelled reversible in the rules in force, so it always waits for you"
    return True, ""


def covering_classes(decision: PolicyDecision, arguments: dict[str, Any], granted: list[str], ruleset: RuleSet) -> list[str] | None:
    """The granted classes that together cover this call, or None.

    None unless EVERY change in the call is covered by a granted, grantable
    class, the deciding rule is labelled reversible, and no exception raised
    the tier (a raise means this call is the irreversible case of its tool).
    """
    rule = decision.deciding_rule
    if decision.tier is not Tier.TIER_3 or rule is None or rule.reversible is not True or decision.raised_by is not None:
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
    from omniharness.config import config_versions

    try:
        snapshot = config_versions.current_agent_snapshot(user_id, agent)
    except (ValueError, OSError):
        return []
    granted = ((snapshot or {}).get("config") or {}).get(AUTONOMY_KEY) or []
    return [g for g in granted if isinstance(g, str)]


def always_waits(ruleset: RuleSet) -> list[str]:
    """Tier 3 rules that are not reversible: what never runs without the user.
    Generated from the rules in force (design-notes #13), never hand-written."""
    return [r.pattern for r in ruleset.rules if r.tier is Tier.TIER_3 and r.reversible is not True]
