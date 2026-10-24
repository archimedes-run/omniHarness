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


def explain(tool_name: str, arguments: dict[str, Any] | None, ruleset: RuleSet, *, after_content: bool = False, private_read: bool = False) -> PolicyDecision:
    """The effective tier of a hypothetical call, and what decided it.
    `after_content` asks about a call made after content entered the turn;
    `private_read` about one made after a private read in the turn."""
    return classify(tool_name, arguments, ruleset, after_content=after_content, private_read=private_read)
