"""Where content came from (FR-005, FR-006).

A DIFFERENT MECHANISM from turn provenance, and deliberately so. Article III
states both in one sentence, but in code they answer different questions and
read different things:

    FR-004  who is speaking?          -> runtime context, the synthetic-turn marker
    FR-005  where did this come from? -> message state, this module

Merging them is how one gets half-implemented. The run-config marker cannot
express content lineage: a trigger-injected turn and a user turn quoting a web
page are both "the user speaking" as far as run configuration is concerned.

WHAT THIS CAN AND CANNOT DO — stated plainly, because the limit matters.

It CAN determine that a given message IS a tool result: `ToolMessage` carries
`type == "tool"` and a `tool_call_id`, and every tool source normalises to it.
That is enough for the requirement as written, because a confirmation is only
ever sought from a genuine user turn — so the rule is that tool results are
never eligible, not that copied text must be traced.

It CANNOT prove that text inside a HumanMessage was not copied from a tool
result by the user. Nothing structural distinguishes a user typing "yes" from a
user pasting "yes" out of a web page, and that is fine: the user pasting it is
the user saying it. What must never happen is the SYSTEM treating tool output as
if the user had spoken, and that is exactly what this prevents.
"""

from __future__ import annotations

from typing import Any

#: Message types that are never eligible to confirm or initiate a Tier 3 action.
#: `tool` is the whole of it today; the set exists so adding a source that
#: introduces another is a one-line change in one place rather than a hunt.
NON_USER_ORIGINS = frozenset({"tool"})

#: Message types that represent the user actually speaking.
USER_ORIGINS = frozenset({"human"})


def _message_type(message: Any) -> str | None:
    if isinstance(message, dict):
        return message.get("type") or message.get("role")
    return getattr(message, "type", None)


def is_tool_result(message: Any) -> bool:
    """True when this message IS a tool result, whatever source produced it.

    Builtin, MCP, connector and ACP tools all execute through the same tool node
    and return `ToolMessage`, so one check covers every source. If a future
    source bypasses that, `test_lineage_control.py` is what notices.
    """
    if _message_type(message) in NON_USER_ORIGINS:
        return True
    # Belt and braces: a tool_call_id is only ever present on a tool result.
    if isinstance(message, dict):
        return message.get("tool_call_id") is not None
    return getattr(message, "tool_call_id", None) is not None


def is_user_turn(message: Any) -> bool:
    """True only for the user actually speaking.

    Deliberately a whitelist. An unrecognised message type is NOT a user turn,
    so a message shape nobody anticipated fails toward refusing rather than
    toward accepting — the same direction as FR-009's unknown-tool default.
    """
    return _message_type(message) in USER_ORIGINS and not is_tool_result(message)


def latest_user_turn(messages: list[Any]) -> Any | None:
    """The most recent genuine user turn, or None.

    This is what a confirmation is read from. Scanning backwards for the first
    eligible message means tool results interleaved after the user's reply
    cannot displace it.
    """
    for message in reversed(messages or []):
        if is_user_turn(message):
            return message
    return None


def eligible_to_confirm(message: Any) -> bool:
    """FR-005. Only a genuine user turn may satisfy a confirmation."""
    return is_user_turn(message)


def eligible_to_initiate(message: Any) -> bool:
    """FR-006. Tool-result content may not initiate a Tier 3 action either.

    Separate from `eligible_to_confirm` because they are separate requirements:
    one is about answering a question already asked, the other about causing the
    question to exist. A single function would let one be implemented and the
    other assumed.
    """
    return not is_tool_result(message)
