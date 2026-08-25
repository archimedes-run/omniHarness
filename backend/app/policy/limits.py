"""Honest-limits wording (FR-023, Article X).

The assistant's only product is trustworthy status. Where a capability is absent
or an action needs confirmation, the wording must say what is TRUE — never imply
a capability that does not exist, and never imply a limitation is a policy choice
when it is a hard absence, or vice versa.

The distinction matters to the user in a way that is easy to flatten:

    "I'm not allowed to send email"     implies a setting they could change
    "I can't send email"                is the truth — there is no such tool

The first invites "well, allow it then". The second is accurate and closes the
conversation honestly.
"""

from __future__ import annotations

from .models import PendingAction, Tier

#: Capabilities deliberately absent from the tool surface (FR-012), with what to
#: say instead. Keyed by the thing a user is likely to ask for.
ABSENT_CAPABILITIES = {
    "send email": ("I can't send email — I have no tool that sends. I can read your mail and write a draft, and the draft stays in your drafts folder until you send it yourself."),
}


def describe_absent(capability: str) -> str | None:
    """Wording for a capability that does not exist. None if it does."""
    return ABSENT_CAPABILITIES.get(capability.strip().lower())


def describe_tier(tier: Tier, tool_name: str) -> str:
    """What will happen, stated before it happens."""
    if tier is Tier.TIER_1:
        return f"I'll use {tool_name} to look that up."
    if tier is Tier.TIER_2:
        return f"I'll use {tool_name}, and I'll tell you exactly what changed."
    return f"I won't use {tool_name} until you confirm. I'll tell you what I intend to do first."


def describe_expiry(action: PendingAction) -> str:
    """FR-019, said plainly rather than left as silence.

    An action that vanished without explanation is indistinguishable from one
    that never existed — the same shape as Feature 001's empty registry reading
    as "you have no sessions running".
    """
    return f"I asked about this at {action.expires_at.isoformat(timespec='minutes')} and didn't hear back, so I did NOT do it. Nothing changed. Ask again if you still want it."


#: Article X: this is measured, not estimated. If the browser worker lands, this
#: figure goes in setup guidance rather than being omitted for being awkward.
BROWSER_DISK_COST_MB = 550
BROWSER_DISK_NOTE = "A browser adds about 550 MB of disk (measured: a 356 MB Chromium build plus a 196 MB headless shell). It runs only when asked and is not held in memory."
