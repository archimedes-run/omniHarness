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
