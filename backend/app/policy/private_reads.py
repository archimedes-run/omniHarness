"""Has this turn read the person's PRIVATE data? (owner decision 2026-10-24)

WHY THIS EXISTS. Exfiltration needs two things in one turn: the person's
private data in the model's hands, and a channel out. The outbound tools
(web_search, web_fetch, image_search: each sends an agent-chosen query or URL
off the machine) are the channel. They used to escalate to a confirmation card
once ANY tool result entered the turn (`after_content`), so a plain research
request ("find 5 date-night restaurants in Philly with links") turned into a
card per lookup as soon as the first search came back: untrusted, yes, but a
search result is not the person's data, and there was nothing to leak.

So for the outbound tools the condition is now "a tool that reads the person's
private data returned data in this turn" (`after_private_read` exceptions in
the rules file). Untrusted web content alone no longer escalates a lookup.
Every OTHER rule keeps `after_content`, and the card a content-led proposal
gets is still card-only (FR-006): this changes WHEN an outbound call needs a
card, not who may confirm one.

WHAT COUNTS AS A PRIVATE READ, FAIL-SAFE. Data-driven, from the rules file:

  * a rule's `reads_private: false` marks a tool whose result is NOT the
    person's data (the public web tools, pure utilities);
  * every other rule counts as a private read: unlabelled means yes, so a
    connector, an MCP server tool or a new tool added without thinking about
    this is private;
  * a tool no rule names, a result whose tool cannot be told, and unreadable
    rules all count as private reads.

WHERE IT IS TRACKED: from the run's own message state, the same walk lineage
(`initiation_origin`) makes for `after_content`: back from the call to the
start of the turn (the person's server-tagged message, or an invited agent's
instruction). The state is the server's (a client's input is rebuilt by
normalize_input, which never copies kwargs), and there is no flag a request
can set or clear: the policy middleware also ORs in three server-owned facts
the walk cannot see (an automation's turn; the inviting turn, for a delegate;
the confirmed calls' turn, for a resume after a confirmation), each defaulting
to "private" when absent.

KNOWN LIMITS (stated, not simulated): the person's own message, the system
prompt and context injected into it (memory, a summary of earlier turns) are
not counted as private reads, and neither is private data read in an EARLIER
turn that is still in the model's context. See
specs/007-agent-improvement/tier-changes.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from omniharness.tools.names import canonical_tool_name

from .config import RuleSet
from .lineage import _message_type, _tool_name_of, is_invitation, is_tool_result, is_user_turn

#: The source named when the walk never reached the start of the turn (a
#: summarised history, a hand-built message list): can't-tell, so private.
UNKNOWN_START = "the turn's start could not be found"


def reads_private(tool_name: str | None, ruleset: RuleSet) -> bool:
    """True when a result of `tool_name` counts as the person's private data.

    Only rules that ALL say `reads_private: false` make it public; no rule,
    an unlabelled rule, a name that cannot be told, or unreadable rules make
    it private.
    """
    from .classify import _candidates

    if ruleset.unreadable:
        return True
    name = canonical_tool_name(tool_name or "")
    if not name:
        return True
    rules = _candidates(name, ruleset)
    if not rules:
        return True
    return any(rule.reads_private is not False for rule in rules)


def is_outbound(tool_name: str | None, ruleset: RuleSet) -> bool:
    """True for a tool the rules escalate after a private read (an
    `after_private_read` exception): the outbound set, read from the rules."""
    from .classify import _candidates

    name = canonical_tool_name(tool_name or "")
    if not name or ruleset.unreadable:
        return False
    return any(exception.after_private_read for rule in _candidates(name, ruleset) for exception in rule.exceptions)


@dataclass(frozen=True)
class TurnPrivacy:
    """What the walk found for one call."""

    #: A private read happened in this turn (or it cannot be ruled out).
    private: bool
    #: The tools whose results counted, oldest first (or UNKNOWN_START).
    sources: tuple[str, ...] = field(default_factory=tuple)
    #: The id of the message that started the turn (the person's message or
    #: an invitation); "" when there is none. Groups a turn's cards.
    turn_key: str = ""


def private_reads_in_turn(messages: list[Any] | None, ruleset: RuleSet) -> TurnPrivacy:
    """Walk back from the call to the start of its turn.

    Every tool result on the way is judged by `reads_private`. Messages that
    are neither the person's turn nor an invitation (our own middlewares'
    injected human messages: a viewed image, a to-do reminder, a summary) are
    walked past, never treated as the start. A walk that never finds the start
    cannot rule a private read out, so it counts as one.
    """
    items = list(messages or [])
    sources: list[str] = []
    for index in range(len(items) - 1, -1, -1):
        message = items[index]
        if is_tool_result(message):
            name = _tool_name_of(items, message)
            if reads_private(name, ruleset) and name not in sources:
                sources.insert(0, name)
            continue
        if _message_type(message) == "ai":
            continue
        if is_user_turn(message) or is_invitation(message):
            key = message.get("id") if isinstance(message, dict) else getattr(message, "id", None)
            return TurnPrivacy(private=bool(sources), sources=tuple(sources), turn_key=str(key or ""))
    return TurnPrivacy(private=True, sources=(*sources, UNKNOWN_START))
