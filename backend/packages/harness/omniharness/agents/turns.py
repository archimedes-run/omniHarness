"""The server's mark on a human message that IS the person's turn.

Lives in the harness so both the gateway (services.normalize_input, the only
place a request's human message is tagged) and the harness (an invited agent's
instruction message, see subagents/executor.py) can set it. The one reader is
app.policy.lineage.is_user_turn.
"""

from __future__ import annotations

from typing import Any

USER_TURN_MARKER = "omniharness_user_turn"


#: On an invited agent's (subagent's) instruction message. NOT a user turn:
#: its author is the inviting agent's model. Lineage maps it to the inviter's
#: recorded origin (PolicyMiddleware._origin); typed confirmations refuse it.
INVITATION_MARKER = "omniharness_invitation"


def mark_invitation(message: Any) -> Any:
    kwargs = dict(getattr(message, "additional_kwargs", None) or {})
    kwargs[INVITATION_MARKER] = True
    message.additional_kwargs = kwargs
    return message


def mark_user_turn(message: Any) -> Any:
    """Tag a message as the person's own turn (server-side only)."""
    if isinstance(message, dict):
        message.setdefault("additional_kwargs", {})[USER_TURN_MARKER] = True
    else:
        kwargs = dict(getattr(message, "additional_kwargs", None) or {})
        kwargs[USER_TURN_MARKER] = True
        message.additional_kwargs = kwargs
    return message


#: On a tool result, set by the policy layer (app.policy.middleware): the
#: call's tier and outcome ("ran", "needs_confirmation", "refused") and its
#: card id. Display and measurement data (the per-run trace, the todo gate's
#: "stopped at a card"); no policy decision reads it back.
POLICY_STEP_MARKER = "omniharness_policy_step"


#: On the summary message that replaces history (summarization_middleware):
#: what the summarized part of the CURRENT turn was, so the policy's
#: private-read walk (app.policy.private_reads) can still judge it once the
#: person's tagged message is gone. Server-set only; a missing or malformed
#: record counts as a private read.
TURN_SUMMARY_MARKER = "omniharness_turn_summary"

#: On a run's input message that is NOT the person's turn (a relayed channel
#: message from someone else, a non-JSON message; services.normalize_input).
#: It starts a turn of its own, so neither the private-read walk nor a
#: summary record may carry an earlier turn's verdict across it.
UNTAGGED_INPUT_MARKER = "omniharness_untagged_input"


def mark_untagged_input(message: Any) -> Any:
    kwargs = dict(getattr(message, "additional_kwargs", None) or {})
    kwargs[UNTAGGED_INPUT_MARKER] = True
    message.additional_kwargs = kwargs
    return message


def is_untagged_input(message: Any) -> bool:
    return _type(message) == "human" and _kwargs(message).get(UNTAGGED_INPUT_MARKER) is True


def _kwargs(message: Any) -> dict:
    kwargs = message.get("additional_kwargs") if isinstance(message, dict) else getattr(message, "additional_kwargs", None)
    return kwargs if isinstance(kwargs, dict) else {}


def _type(message: Any) -> str | None:
    return (message.get("type") or message.get("role")) if isinstance(message, dict) else getattr(message, "type", None)


def _result_tool_name(messages: list[Any], result: Any) -> str:
    """The tool behind a result; "" when it cannot be told (counts as private)."""
    name = result.get("name") if isinstance(result, dict) else getattr(result, "name", None)
    if name:
        return str(name)
    call_id = result.get("tool_call_id") if isinstance(result, dict) else getattr(result, "tool_call_id", None)
    for message in messages:
        calls = message.get("tool_calls") if isinstance(message, dict) else getattr(message, "tool_calls", None)
        for call in calls or []:
            if call.get("id") == call_id and call.get("name"):
                return str(call["name"])
    return ""


def summarized_turn(messages: list[Any]) -> dict[str, Any]:
    """The record for TURN_SUMMARY_MARKER: walking back from the newest
    summarized message to the latest turn start (the person's tagged message
    or an invitation), the tools whose results are folded into the summary.
    An earlier summary of the same turn is carried forward. No start found:
    `start_found` is False, and the walk counts the turn as private."""
    tools: list[str] = []
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        kind = _type(message)
        if kind == "tool":
            tools.insert(0, _result_tool_name(messages, message))
            continue
        if kind != "human":
            continue
        kwargs = _kwargs(message)
        if kwargs.get(USER_TURN_MARKER) is True or kwargs.get(INVITATION_MARKER) is True:
            key = message.get("id") if isinstance(message, dict) else getattr(message, "id", None)
            return {"turn_key": str(key or ""), "tools": tools, "start_found": True}
        if kwargs.get(UNTAGGED_INPUT_MARKER) is True:
            return {"turn_key": "", "tools": tools, "start_found": False}
        if TURN_SUMMARY_MARKER in kwargs:
            earlier = kwargs[TURN_SUMMARY_MARKER]
            prior = earlier.get("tools") if isinstance(earlier, dict) else None
            if not isinstance(prior, list):
                return {"turn_key": "", "tools": tools, "start_found": False}
            return {"turn_key": str(earlier.get("turn_key") or ""), "tools": [*prior, *tools], "start_found": earlier.get("start_found") is True}
    return {"turn_key": "", "tools": tools, "start_found": False}
