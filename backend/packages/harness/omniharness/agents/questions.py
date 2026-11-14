"""The harness side of the shared question card (009 question-card.md).

The harness does not import the gateway. The gateway registers the function
that records a question (app.gateway.questions.install); the lead's
ClarificationMiddleware calls it through here. With nothing registered (the
embedded client, a bare harness test) a question is shown as text, as before.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

#: On the ask_clarification tool message whose question became a card:
#: {"id": <question id>}. Display data; nothing decides on it.
QUESTION_MARKER = "omniharness_question"


class QuestionRefused(ValueError):
    """The question breaks the card's limits; the model is told why."""


_opener: Callable[..., dict[str, Any] | None] | None = None
_refusal: type[Exception] | None = None
_applies: Callable[[dict | None], bool] | None = None


def register_question_opener(opener: Callable[..., dict[str, Any] | None], refusal: type[Exception], applies: Callable[[dict | None], bool] | None = None) -> None:
    global _opener, _refusal, _applies
    _opener, _refusal, _applies = opener, refusal, applies


def makes_cards(runtime_context: dict | None) -> bool:
    """Would a question asked in this run become a card? False with no
    opener, and for runs that never get one (scheduled, invited, @-called)."""
    if _opener is None:
        return False
    return True if _applies is None else bool(_applies(runtime_context))


def open_question(**kwargs: Any) -> dict[str, Any] | None:
    """Record a question card; None when no card is made (no opener, or a run
    that does not ask with a card). Raises QuestionRefused with the reason."""
    if _opener is None:
        return None
    try:
        return _opener(**kwargs)
    except Exception as exc:
        if _refusal is not None and isinstance(exc, _refusal):
            raise QuestionRefused(str(exc)) from exc
        raise
