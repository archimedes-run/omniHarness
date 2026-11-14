"""The shared question card: store, expiry sweep, resume registry, lead asker.

Contract: specs/009-orchestration/question-card.md. New askers (a coding job,
a chat-builder flow) call `build_question` + `get_store().save(...)` to open a
card and `register_asker(kind, handler, display_name=...)` to be resumed.
"""

from __future__ import annotations

from .service import (
    AnswerRefused,
    answer_by_owner,
    answer_from_turn,
    asker_name,
    dispatch,
    end_for_thread,
    get_store,
    match_option,
    public_view,
    register_asker,
    sweep,
    sweep_forever,
)
from .store import Question, QuestionError, QuestionStore, build_question

__all__ = [
    "AnswerRefused",
    "Question",
    "QuestionError",
    "QuestionStore",
    "answer_by_owner",
    "answer_from_turn",
    "asker_name",
    "build_question",
    "dispatch",
    "end_for_thread",
    "get_store",
    "install",
    "match_option",
    "public_view",
    "register_asker",
    "sweep",
    "sweep_forever",
]


def install() -> None:
    """Called once per gateway process: the lead asker and the harness hook."""
    from omniharness.agents.questions import register_question_opener

    from .lead import install as install_lead
    from .lead import makes_cards, open_lead_question

    install_lead()
    register_question_opener(open_lead_question, QuestionError, applies=makes_cards)
