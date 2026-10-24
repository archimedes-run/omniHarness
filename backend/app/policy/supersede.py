"""When the rules change, stop asking about what no longer needs asking (FR-042).

The occasion (ROADMAP-FOLLOWUPS, 2026-09-23): three read-only email calls were
Tier 3 under rules that did not match the connector's tool names. The rules were
fixed — those tools became Tier 1 — and the three pending actions became
permanently un-confirmable: `recognise` correctly refuses a bare "approved"
with several pending, and nothing resolved an action whose tool was no longer
Tier 3. They blocked every confirmation for four hours.

`PendingAction` records `tier_at_statement` so a later rule change cannot
retroactively AUTHORISE anything. This is the other half: a rule change may
retroactively REMOVE a demand for confirmation that the current rules say is
unnecessary. Never grant one, and never act: superseding resolves the action
and runs nothing. The user asked under rules that required approval; the answer
is to stop asking, not to proceed unasked.
"""

from __future__ import annotations

import logging
from datetime import datetime

from .classify import classify
from .config import RuleSet
from .confirm_flow import take_claim
from .models import Outcome, PendingAction, Tier
from .pending import PendingStore

logger = logging.getLogger(__name__)

#: The claimant recorded on a superseded action, so the record says who
#: resolved it.
CLAIMANT = "rules-reload"


def refuse_removed_agent(store: PendingStore, thread_id: str, agent: str, now: datetime) -> list[PendingAction]:
    """An agent taken out of a chat: its open actions there are refused, never run.

    Claimed through the one claim site first, so a confirmation racing the
    removal either wins (and ran before the removal) or finds it resolved.
    """
    refused: list[PendingAction] = []
    for action in store.open_actions(now):
        if action.thread_id != thread_id or action.requester != agent or not action.surface.get("called_agent"):
            continue
        claimed = take_claim(store, action.id, "member-removed")
        if claimed is None:
            continue
        store.resolve(claimed, Outcome.DECLINED, f"{agent} was taken out of this chat, so its request was refused. Nothing has run.")
        refused.append(claimed)
    return refused


def supersede_unneeded(store: PendingStore, ruleset: RuleSet, now: datetime) -> list[PendingAction]:
    """Resolve SUPERSEDED every open action the current rules make LESS
    demanding than when it was stated.

    Usually that is a Tier 3 action whose tool is now Tier 1 or 2. Since
    Feature 006 a Tier 2 call can also wait (a scheduled run with no standing
    grant covering it, or over the run's cap): it was stated at Tier 2, so it
    stays open while its call is still Tier 2, and is superseded only if the
    call becomes Tier 1."""
    if ruleset.unreadable:
        # Unreadable rules make every tool Tier 3; nothing is less demanding.
        return []
    superseded = []
    for action in store.open_actions(now):
        # Classified as it was stated: an action content led to stays judged
        # after content, or a rules reload would wave every one of them away.
        decision = classify(action.tool_name, action.arguments, ruleset, after_content=action.origin != "user")
        if not decision.refused and decision.tier >= min(action.tier_at_statement, Tier.TIER_3):
            continue
        # Claimed first, through the same one-shot claim confirmation uses, so
        # a supersede cannot race a confirmation on another worker into a
        # double resolution.
        claimed = take_claim(store, action.id, CLAIMANT)
        if claimed is None:
            continue
        if decision.refused:
            # 007: no rule names it any more, so it may not run at all — not
            # even with the confirmation it was waiting for.
            store.resolve(claimed, Outcome.SUPERSEDED, f"the rules changed: no policy rule covers {action.tool_name} any more, so it is refused. It was NOT run.")
            logger.info("policy: superseded %s (%s now has no rule)", action.id, action.tool_name)
            superseded.append(claimed)
            continue
        rule = decision.deciding_rule.pattern if decision.deciding_rule is not None else "the default"
        store.resolve(
            claimed,
            Outcome.SUPERSEDED,
            f"the rules changed: {action.tool_name} is now Tier {int(decision.tier)} (rule {rule!r}), so it no longer needs your confirmation. It was NOT run; ask again if you still want it.",
        )
        logger.info("policy: superseded %s (%s now Tier %d)", action.id, action.tool_name, int(decision.tier))
        superseded.append(claimed)
    return superseded
