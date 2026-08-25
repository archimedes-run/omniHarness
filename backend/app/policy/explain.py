"""Inspecting a call's effective tier without executing it (FR-038).

Raise-only classification is safe but opaque: someone edits a default, forgets
an exception raises it, and is asked to confirm something they meant to be
silent. Without a way to see WHY, the pressure to add lowering exceptions comes
back — not because they are needed, but because the policy is unreadable.

This is what makes FR-037 livable rather than merely correct.

It calls `classify()` — the same function live dispatch uses. An inspector with
its own implementation answers a different question and diverges silently, which
is worse than having none because the answer is believed.
"""

from __future__ import annotations

from typing import Any

from .classify import classify
from .config import RuleSet
from .models import PolicyDecision


def explain(tool_name: str, arguments: dict[str, Any] | None, ruleset: RuleSet) -> PolicyDecision:
    """The effective tier of a hypothetical call, and what decided it."""
    return classify(tool_name, arguments, ruleset)


def render(decision: PolicyDecision, ruleset: RuleSet | None = None) -> str:
    """Operator-readable form."""
    lines = [
        f"tool:       {decision.tool_name}",
        f"tier:       {int(decision.tier)}",
        f"decided_by: {decision.deciding_rule.describe() if decision.deciding_rule else 'no matching rule — unknown tools are Tier 3 (FR-009)'}",
    ]
    if decision.raised_by is not None:
        lines.append(f"raised_by:  exception when {decision.raised_by.when} -> tier {int(decision.raised_by.tier)}")
    else:
        lines.append("raised_by:  —")
    if ruleset is not None and ruleset.unreadable:
        lines.append(f"NOTE:       the rules file could not be read ({ruleset.error}); every tool is Tier 3")
    return "\n".join(lines)
