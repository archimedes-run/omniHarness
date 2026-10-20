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

from omniharness.agents.turns import USER_TURN_MARKER, mark_user_turn  # noqa: F401 (re-exported)

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


#: Set by the SERVER on the human message(s) of a request it received from the
#: person (services.normalize_input), in ``additional_kwargs``. A client cannot
#: set it: normalize_input rebuilds every message and never copies client kwargs.
#: (USER_TURN_MARKER and mark_user_turn live in omniharness.agents.turns.)


def user_turn(content: Any, **kwargs: Any) -> Any:
    """A HumanMessage the person sent, tagged as such (for the server and tests)."""
    from langchain_core.messages import HumanMessage

    return mark_user_turn(HumanMessage(content=content, **kwargs))


def is_user_turn(message: Any) -> bool:
    """THE one test of "the user said this" (lineage, typed confirmations, ...).

    A HumanMessage is NOT enough: our own middlewares inject HumanMessages
    mid-turn (the viewed image, todo reminders, the summary, browser-reported
    preview errors) and workflow runs start from one. Each of those reset the
    origin to "user", so content read earlier in the turn ran as if the user
    had asked. Only a human message carrying the server's USER_TURN_MARKER is
    the user. Everything else fails toward content / card-only.
    """
    if _message_type(message) not in USER_ORIGINS or is_tool_result(message):
        return False
    kwargs = message.get("additional_kwargs") if isinstance(message, dict) else getattr(message, "additional_kwargs", None)
    return bool(isinstance(kwargs, dict) and kwargs.get(USER_TURN_MARKER) is True)


def is_invitation(message: Any) -> bool:
    """An invited agent's instruction message (omniharness.agents.turns)."""
    from omniharness.agents.turns import INVITATION_MARKER

    kwargs = message.get("additional_kwargs") if isinstance(message, dict) else getattr(message, "additional_kwargs", None)
    return bool(isinstance(kwargs, dict) and kwargs.get(INVITATION_MARKER) is True)


def eligible_to_confirm(message: Any) -> bool:
    """FR-005. Only a genuine user turn may satisfy a confirmation."""
    return is_user_turn(message)


#: What caused a Tier 3 proposal (FR-006, applied globally 2026-10-19).
ORIGIN_USER = "user"  # the user's own latest message
ORIGIN_CONTENT = "content"  # something the agent READ: a page, an email, any tool output
ORIGIN_AUTOMATION = "automation"  # a trigger's synthetic turn
ORIGIN_UNKNOWN = "unknown"  # nothing structural said; treated like content
ORIGIN_INVITATION = "invitation"  # an invited agent's instruction: the inviter's origin applies


def initiation_origin(messages: list[Any] | None, *, synthetic: bool = False) -> tuple[str, str]:
    """FR-006. Which turn caused the call being dispatched, and its source.

    Content the agent READ may SUGGEST an action but can never confirm it or
    originate it silently. So the question is not "is the last message a tool
    result" — at dispatch the last message is ALWAYS the AI message making the
    call, which is why that check never fired (reported 2026-10-19). Walk back
    past the AI message(s) of this step; the first other message is the cause:

      a genuine user turn  -> ("user", "")
      tool result(s)       -> ("content", "<the tool(s) that produced them>")
      anything else        -> ("unknown", "")   fails toward card-only

    A trigger-injected turn is a HumanMessage by shape, so `synthetic` (from
    runtime context, provenance.is_synthetic_turn) is consulted first.
    """
    if synthetic:
        return ORIGIN_AUTOMATION, ""
    items = list(messages or [])
    for index in range(len(items) - 1, -1, -1):
        message = items[index]
        if _message_type(message) == "ai" and not is_tool_result(message):
            continue
        if is_tool_result(message):
            return ORIGIN_CONTENT, _content_source(items, index)
        if is_invitation(message):
            return ORIGIN_INVITATION, ""
        if is_user_turn(message):
            return ORIGIN_USER, ""
        return ORIGIN_UNKNOWN, ""
    return ORIGIN_UNKNOWN, ""


def _content_source(items: list[Any], index: int) -> str:
    """The tool(s) whose results sit at the end of the read, in call order."""
    names: list[str] = []
    while index >= 0 and is_tool_result(items[index]):
        name = _tool_name_of(items, items[index])
        if name not in names:
            names.insert(0, name)
        index -= 1
    return ", ".join(names)


def _tool_name_of(items: list[Any], result: Any) -> str:
    name = result.get("name") if isinstance(result, dict) else getattr(result, "name", None)
    if name:
        return str(name)
    call_id = result.get("tool_call_id") if isinstance(result, dict) else getattr(result, "tool_call_id", None)
    for message in items:
        calls = message.get("tool_calls") if isinstance(message, dict) else getattr(message, "tool_calls", None)
        for call in calls or []:
            if call.get("id") == call_id and call.get("name"):
                return str(call["name"])
    return "a tool result"
