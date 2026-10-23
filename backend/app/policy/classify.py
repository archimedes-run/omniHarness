"""Deciding a call's tier (FR-008, FR-009, FR-037).

Three rules, each chosen so that ambiguity resolves toward ASKING:

  * an exception may only raise (enforced at load, see config.py)
  * where two patterns match, the HIGHEST tier wins
  * where nothing matches, the call is REFUSED (007): not run, not offered to
    the model, and named in the log. It used to be Tier 3 by default, which is
    how the Calendar MCP's hyphenated `create-event` sat at Tier 3 for months
    while its rule said Tier 2: a default tier hides a rule that does not
    match. A refusal makes the mismatch impossible to miss.
  * where the file could not be read, everything is Tier 3 — a broken file
    makes the assistant ask about everything, never act freely; and the state
    is recorded (`RuleSet.unreadable`), so it is inspectable, not a default.

Names are compared in canonical form (`omniharness.tools.names`), the same
function the tool surface uses at registration, on BOTH the call's name and
each rule's pattern. Nothing else in the policy layer normalises.
"""

from __future__ import annotations

import fnmatch
from typing import Any

from omniharness.tools.names import canonical_tool_name

from .config import RuleSet
from .models import ClassificationRule, PolicyDecision, RuleException, Tier
from .runtime_floors import runtime_floor

#: The tier carried by a call no rule matched. With readable rules such a call
#: is REFUSED (`PolicyDecision.refused`) and this tier is never acted on; with
#: unreadable rules it is the answer for everything (FR-009).
UNKNOWN_TOOL_TIER = Tier.TIER_3


def classify(tool_name: str, arguments: dict[str, Any] | None, ruleset: RuleSet, *, after_content: bool = False) -> PolicyDecision:
    """Classify one call.

    THE ONE code path for this. `explain.py` calls it too rather than
    reimplementing the logic — an inspector that answers a slightly different
    question is worse than none, because it is believed (FR-038).

    `after_content`: the call was led to by something other than the user's
    own message (content the agent read, an automation's turn, or a cause
    nobody could tell). Only `after_content` exceptions read it.
    """
    best: tuple[Tier, ClassificationRule | None, RuleException | None] = (UNKNOWN_TOOL_TIER, None, None)
    matched = False
    name = canonical_tool_name(tool_name)

    for rule in _candidates(name, ruleset):
        matched = True
        tier, raised_by = rule.tier, None
        for exception in rule.exceptions:
            if exception.matches(arguments or {}, after_content=after_content) and exception.tier > tier:
                tier, raised_by = exception.tier, exception
        # Highest tier wins on overlap — same direction as FR-037.
        if best[1] is None or tier > best[0]:
            best = (tier, rule, raised_by)

    if not matched:
        if ruleset.unreadable:
            # The rules could not be read: everything asks (FR-009). Not a
            # refusal — nothing is known to be unclassified, only unreadable.
            return PolicyDecision(tool_name=tool_name, tier=UNKNOWN_TOOL_TIER, deciding_rule=None)
        # Readable rules, and none names this tool: refused, never defaulted.
        return PolicyDecision(tool_name=tool_name, tier=UNKNOWN_TOOL_TIER, deciding_rule=None, refused=True)

    # A tier that holds only where the tool runs (runtime_floors): raised,
    # never lowered, when that place is not the hardened one.
    floor = runtime_floor(name)
    if floor is not None and floor > best[0]:
        return PolicyDecision(tool_name=tool_name, tier=floor, deciding_rule=best[1], raised_by=best[2])
    return PolicyDecision(tool_name=tool_name, tier=best[0], deciding_rule=best[1], raised_by=best[2])


#: Per rule set: canonical exact patterns -> rule positions, and the globs. The
#: shipped file has ~1,100 rules, almost all exact names; scanning each with
#: fnmatch on every call cost ~1.4 ms per call and is checked for every tool on
#: every model call. Keyed by identity: a RuleSet is immutable, and the loader
#: returns the same object while its file is unchanged.
_INDEX: dict[int, tuple[RuleSet, dict[str, list[int]], list[tuple[int, str]]]] = {}
_GLOB_CHARS = frozenset("*?[")


def _candidates(name: str, ruleset: RuleSet) -> list[ClassificationRule]:
    """The rules whose pattern matches `name` (canonical), in file order."""
    entry = _INDEX.get(id(ruleset))
    if entry is None or entry[0] is not ruleset:
        exact: dict[str, list[int]] = {}
        globs: list[tuple[int, str]] = []
        for position, rule in enumerate(ruleset.rules):
            pattern = canonical_tool_name(rule.pattern)
            if _GLOB_CHARS.isdisjoint(pattern):
                exact.setdefault(pattern, []).append(position)
            else:
                globs.append((position, pattern))
        if len(_INDEX) > 32:
            _INDEX.clear()
        entry = _INDEX[id(ruleset)] = (ruleset, exact, globs)
    _, exact, globs = entry
    positions = sorted([*exact.get(name, ()), *(p for p, pattern in globs if fnmatch.fnmatchcase(name, pattern))])
    return [ruleset.rules[p] for p in positions]
