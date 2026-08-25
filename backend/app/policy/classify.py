"""Deciding a call's tier (FR-008, FR-009, FR-037).

Three rules, each chosen so that ambiguity resolves toward ASKING:

  * an exception may only raise (enforced at load, see config.py)
  * where two patterns match, the HIGHEST tier wins
  * where nothing matches — or the file could not be read — the answer is Tier 3

The last is the one that carries the feature. A newly connected tool source is
dangerous until the user says otherwise, and that has to hold for tools that did
not exist when the rules were written.
"""

from __future__ import annotations

import fnmatch
from typing import Any

from .config import RuleSet
from .models import ClassificationRule, PolicyDecision, RuleException, Tier

#: The answer when nothing matches. Not a fallback — a decision (FR-009).
UNKNOWN_TOOL_TIER = Tier.TIER_3


def classify(tool_name: str, arguments: dict[str, Any] | None, ruleset: RuleSet) -> PolicyDecision:
    """Classify one call.

    THE ONE code path for this. `explain.py` calls it too rather than
    reimplementing the logic — an inspector that answers a slightly different
    question is worse than none, because it is believed (FR-038).
    """
    best: tuple[Tier, ClassificationRule | None, RuleException | None] = (UNKNOWN_TOOL_TIER, None, None)
    matched = False

    for rule in ruleset.rules:
        if not fnmatch.fnmatchcase(tool_name, rule.pattern):
            continue
        matched = True
        tier, raised_by = rule.tier, None
        for exception in rule.exceptions:
            if exception.matches(arguments or {}) and exception.tier > tier:
                tier, raised_by = exception.tier, exception
        # Highest tier wins on overlap — same direction as FR-037.
        if best[1] is None or tier > best[0]:
            best = (tier, rule, raised_by)

    if not matched:
        # No rule matched. This is FR-009, and it is the same answer whether the
        # rules are empty, the tool is new, or the file was unreadable.
        return PolicyDecision(tool_name=tool_name, tier=UNKNOWN_TOOL_TIER, deciding_rule=None)

    return PolicyDecision(tool_name=tool_name, tier=best[0], deciding_rule=best[1], raised_by=best[2])
