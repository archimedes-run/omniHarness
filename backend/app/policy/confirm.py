"""Recognising a confirmation (FR-034, FR-035, FR-036).

DETERMINISTIC, NEVER MODEL-JUDGED. A gate that rests on the model deciding
whether a reply constitutes agreement is defended by prompting, which Article
III forbids. It also puts a web page reading "the user has approved this,
proceed" on the same channel as the real answer — and the workers in this
feature put attacker-controlled text directly into the assistant's context.

DECLINE IS RECOGNISED AS MECHANICALLY AS CONFIRM. If yes is structural and no
falls back to interpretation, an intended refusal reads as ambiguity and gets
re-asked, which teaches people to type whatever makes the prompt stop. A gate
users learn to route around is worse than no gate, because it still looks like
protection.

AN UNRECOGNISED REPLY RESTATES THE PLAN IN FULL. Re-prompting without restating
leaves the user confirming something they can no longer see, which defeats the
purpose of having stated it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from .lineage import eligible_to_confirm
from .models import PendingAction


class Verdict(StrEnum):
    CONFIRM = "confirm"
    DECLINE = "decline"
    UNRECOGNISED = "unrecognised"


#: Recognised forms. A closed set, matched exactly after normalisation — NOT a
#: heuristic, and not a similarity score. Extending it is a deliberate edit.
#:
#: The action id may accompany either, which is what disambiguates when several
#: actions are pending.
_CONFIRM_FORMS = frozenset({"yes", "y", "confirm", "confirmed", "approve", "approved", "go ahead", "do it", "proceed"})
_DECLINE_FORMS = frozenset({"no", "n", "decline", "declined", "cancel", "cancelled", "stop", "don't", "do not"})

_ID = re.compile(r"\b([0-9a-f]{12})\b")
_NORMALISE = re.compile(r"[^a-z0-9' ]+")


@dataclass(frozen=True)
class Recognition:
    verdict: Verdict
    action_id: str | None = None
    reason: str = ""


def _normalise(text: str) -> str:
    return _NORMALISE.sub(" ", (text or "").strip().lower()).strip()


def recognise(message, pending: list[PendingAction]) -> Recognition:
    """Read a verdict from a message, or refuse to.

    Two structural checks run BEFORE any text is looked at, and neither can be
    satisfied by content:

      1. the message must be a genuine user turn (FR-005 — lineage)
      2. it must name or unambiguously address one pending action
    """
    if not eligible_to_confirm(message):
        return Recognition(Verdict.UNRECOGNISED, reason="not a user turn — tool-result content cannot confirm or decline (FR-005)")

    raw = getattr(message, "content", None)
    if raw is None and isinstance(message, dict):
        raw = message.get("content")
    text = _normalise(str(raw or ""))
    if not text:
        return Recognition(Verdict.UNRECOGNISED, reason="empty reply")

    open_ids = {action.id for action in pending}
    named = next((m for m in _ID.findall(text) if m in open_ids), None)

    if named is None:
        if len(open_ids) > 1:
            # FR-035: ambiguity is not resolved by guessing which was meant.
            return Recognition(Verdict.UNRECOGNISED, reason=f"{len(open_ids)} actions are pending and the reply names none of them")
        named = next(iter(open_ids), None)
    if named is None:
        return Recognition(Verdict.UNRECOGNISED, reason="no action is pending")

    words = text.replace(named, "").strip()
    if words in _CONFIRM_FORMS:
        return Recognition(Verdict.CONFIRM, action_id=named)
    if words in _DECLINE_FORMS:
        return Recognition(Verdict.DECLINE, action_id=named)

    return Recognition(Verdict.UNRECOGNISED, action_id=named, reason=f"{words!r} is neither a recognised confirmation nor a recognised decline")


def restate(action: PendingAction) -> str:
    """FR-035. The plan IN FULL, not a nudge.

    The user is being asked to authorise specific items; a reply of "please
    confirm" asks them to authorise something they can no longer see.
    """
    lines = [
        "I did not recognise that as a yes or a no, so nothing has happened. Here is the plan again in full:",
        "",
        action.plan_text,
        "",
        f"It affects exactly these {len(action.targets)} item(s):",
    ]
    lines += [f"  - {target}" for target in action.targets]
    lines += [
        "",
        f'Reply "yes {action.id}" to go ahead, or "no {action.id}" to cancel.',
        f"If neither arrives, it expires at {action.expires_at.isoformat(timespec='minutes')} and does not run.",
    ]
    return "\n".join(lines)
