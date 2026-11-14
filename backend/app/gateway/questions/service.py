"""Opening, answering and expiring questions; resuming their askers.

The rules of question-card.md that decide WHO may answer live here, in one
place, so every asker (the lead now; coding jobs and the chat builder later)
gets them by registering a resume handler and nothing else:

  * QC-01 / QC-02: an answer comes from the owner's own authenticated button
    request (`answer_by_owner`), or from the owner's own server-tagged turn
    while EXACTLY ONE question is open in that thread (`answer_from_turn`,
    called by the policy layer after `confirm_flow.turn_may_answer`). Nothing
    else answers: no tool result, worker output, resume or scheduled run, no
    untagged channel message, no other user, and never the question's own
    text.
  * QC-03: a typed answer that is not clearly one option is free text.
  * QC-04 / QC-05: the sweep expires due questions; content-originated ones
    always to `stop` (enforced at creation, store.build_question).
  * QC-06: the asker's resume handler is called once per terminal question.
  * QC-07: what the handler receives is the record (data). Whatever it does
    with it, it never turns it into a server-tagged user turn.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .store import (
    ANSWERED,
    EXPIRED,
    EXPIRED_ASKER_ENDED,
    FREE_TEXT_MAX,
    TIMEOUT_MAX_SECONDS,
    VIA_BUTTON,
    VIA_TAGGED_MESSAGE,
    Question,
    QuestionStore,
)

logger = logging.getLogger(__name__)

#: How often every worker sweeps (beside Slice 0's card sweep).
SWEEP_INTERVAL_SECONDS = 60

#: asker.kind -> async handler(question, *, app, request) -> dict | None.
ResumeHandler = Callable[..., Awaitable[dict[str, Any] | None]]
_HANDLERS: dict[str, ResumeHandler] = {}

#: Display names for the card's header ("<name> asks").
_ASKER_NAMES: dict[str, str] = {}

_STORES: dict[str, QuestionStore] = {}


def register_asker(kind: str, handler: ResumeHandler, *, display_name: str) -> None:
    """A new asker kind: its resume handler and the name its card shows. The
    card and the routes do not know askers; only this registry does."""
    _HANDLERS[kind] = handler
    _ASKER_NAMES[kind] = display_name


def asker_name(kind: str) -> str:
    return _ASKER_NAMES.get(kind, "An assistant")


def store_dir() -> Path:
    from omniharness.config.paths import get_paths

    return Path(get_paths().base_dir) / "questions"


def get_store(directory: Path | None = None) -> QuestionStore:
    path = directory or store_dir()
    key = str(path)
    store = _STORES.get(key)
    if store is None:
        store = _STORES[key] = QuestionStore(directory=path)
    return store


# -- typed replies (QC-01, QC-03) ---------------------------------------------

_NUMBER = re.compile(r"^(?:option\s*)?#?(\d{1,2})$", re.I)
_TRAILING = re.compile(r"[\s.!?,;:]+$")


def match_option(text: str, question: Question) -> int | None:
    """The option a typed reply CLEARLY names (its number, or its exact label,
    case and trailing punctuation ignored), else None: anything else is free
    text, never guessed (QC-03)."""
    cleaned = _TRAILING.sub("", str(text or "").strip())
    number = _NUMBER.match(cleaned)
    if number:
        index = int(number.group(1)) - 1
        return index if 0 <= index < len(question.options) else None
    folded = cleaned.casefold()
    for index, option in enumerate(question.options):
        if folded and folded == _TRAILING.sub("", option["label"].strip()).casefold():
            return index
    return None


def message_text(message: Any) -> str:
    content = message.get("content") if isinstance(message, dict) else getattr(message, "content", "")
    if isinstance(content, list):
        return " ".join(str(part.get("text", "")) if isinstance(part, dict) else str(part) for part in content).strip()
    return str(content or "").strip()


class TypedOutcome:
    """What a person's typed turn did to the thread's questions."""

    def __init__(self, answered: Question | None = None, open_count: int = 0, *, cards_open: bool = False) -> None:
        self.answered = answered
        self.open_count = open_count
        #: A Tier 3 card is open beside the question(s): the typed message
        #: answered nothing and confirmed nothing (both are button-only).
        self.cards_open = cards_open

    def note(self) -> str | None:
        """A one-time note for the model reading this turn, or None. Server
        words only: the question's own text (content) is never quoted here."""
        if self.answered is not None:
            choice = self.answered.answer or {}
            said = f"option {int(choice['option']) + 1}" if choice.get("option") is not None else "in their own words"
            return f"(Server note: the person's message above answers the question you asked on its card: {said}.)"
        if self.open_count >= 1 and self.cards_open:
            return (
                "(Server note: a question card and a confirmation card are both open in this chat, so a typed message "
                "answers no question and confirms or declines nothing. Tell the person once, in one sentence, to use the "
                "buttons on the cards. Do not act on their message as an answer.)"
            )
        if self.open_count >= 2:
            return f"(Server note: {self.open_count} questions are open in this chat, so a typed message answers none of them. Tell the person once, in one sentence, to answer each on its card. Do not guess their answers.)"
        return None


def open_for_turn(message: Any, runtime_context: dict | None, *, may_answer: bool, now: datetime | None = None) -> list[Question]:
    """The speaker's open questions in this thread, for a turn that may
    answer at all (else none). The policy layer reads it first: while any is
    open, a typed message never confirms or declines a Tier 3 card."""
    from app.policy.lineage import is_user_turn

    if not may_answer or not is_user_turn(message):
        return []
    ctx = runtime_context or {}
    thread, speaker = ctx.get("thread_id"), ctx.get("user_id")
    if not thread or not speaker:
        return []
    return get_store().open_in_thread(str(thread), str(speaker), now or datetime.now(UTC))


def answer_from_turn(message: Any, runtime_context: dict | None, *, may_answer: bool, cards_open: bool = False, now: datetime | None = None) -> TypedOutcome:
    """The owner's own tagged turn answers the ONLY open question of its thread.

    `may_answer` is `confirm_flow.turn_may_answer(message, context)`, computed
    by the caller (the policy layer, where that test already runs): False for
    a tool result, an agent's reply, an untagged channel message, a scheduled,
    resumed, @-called or invited agent's turn. Then the speaker must be the
    question's owner, and exactly one question must be open in the thread.
    With a Tier 3 card open in the thread as well (`cards_open`), it answers
    neither: the person uses the buttons.
    """
    now = now or datetime.now(UTC)
    open_ = open_for_turn(message, runtime_context, may_answer=may_answer, now=now)
    if open_ and cards_open:
        return TypedOutcome(open_count=len(open_), cards_open=True)
    store = get_store()
    if len(open_) != 1:
        # None, or two or more: a typed reply answers none (QC-01).
        return TypedOutcome(open_count=len(open_))
    question = open_[0]
    text = message_text(message)
    if not text:
        return TypedOutcome(open_count=1)
    option = match_option(text, question)
    answered = store.answer(
        question.id,
        option=option,
        text=None if option is not None else text[:FREE_TEXT_MAX],
        via=VIA_TAGGED_MESSAGE,
        now=now,
    )
    if answered is None:
        return TypedOutcome(open_count=0)
    logger.info("question %s answered by the owner's typed turn", answered.id)
    return TypedOutcome(answered=answered, open_count=1)


# -- buttons (QC-01 a) ----------------------------------------------------------


class AnswerRefused(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def answer_by_owner(qid: str, user_id: str, *, option: int | None, text: str | None, now: datetime | None = None) -> Question:
    """The owner's authenticated request naming the question id. Raises
    AnswerRefused (404 not theirs or missing, 409 not open, 422 bad answer)."""
    store = get_store()
    question = store.get(qid)
    if question is None or question.owner_id != str(user_id):
        raise AnswerRefused(404, f"Question {qid} not found")
    if (option is None) == (text is None or not str(text).strip()):
        raise AnswerRefused(422, "Answer with one option or with text, not both")
    if option is not None and not (isinstance(option, int) and 0 <= option < len(question.options)):
        raise AnswerRefused(422, "No such option")
    cleaned = None if text is None else str(text).strip()
    if cleaned is not None and len(cleaned) > FREE_TEXT_MAX:
        raise AnswerRefused(422, f"The answer must be at most {FREE_TEXT_MAX} characters")
    if cleaned is not None:
        # A typed answer that clearly names one option is that option (QC-03).
        matched = match_option(cleaned, question)
        if matched is not None:
            option, cleaned = matched, None
    answered = store.answer(qid, option=option, text=cleaned, via=VIA_BUTTON, now=now)
    if answered is None:
        current = store.get(qid)
        from app.gateway.display_safe import safe_field

        raise AnswerRefused(409, safe_field(f"This question is {current.state if current else 'gone'}: {current.outcome_text() if current else ''}".strip()))
    logger.info("question %s answered on its card", qid)
    return answered


# -- resuming the asker (QC-06) -------------------------------------------------


async def dispatch(question: Question, *, app: Any = None, request: Any = None) -> dict[str, Any] | None:
    """Call the asker kind's resume handler ONCE for a terminal question: the
    one-shot lock is taken before the call and a failure is never retried."""
    if question.state not in (ANSWERED, EXPIRED):
        return None
    store = get_store()
    if not store.take_once(question.id, "dispatched"):
        return None
    handler = _HANDLERS.get(str(question.asker.get("kind") or ""))
    if handler is None:
        logger.warning("question %s: no resume handler for asker kind %r", question.id, question.asker.get("kind"))
        return None
    try:
        return await handler(question, app=app, request=request)
    except Exception:  # noqa: BLE001 - one asker's failure never stops the caller
        logger.exception("question %s: resume handler failed (not retried)", question.id)
        return None


async def end_for_thread(thread_id: str, *, app: Any = None, request: Any = None, run_id: str | None = None, kinds: tuple[str, ...] = ()) -> list[Question]:
    """Stop, a cancelled run or a deleted thread: the thread's open questions
    expire as `asker_ended`, and each asker is told once. With `run_id`, only
    the questions that run asked, plus every open question of the asker
    `kinds` named (Stop ends the lead's questions even when the run that
    asked has already ended)."""
    store = get_store()
    ended = []
    for question in store.in_thread(str(thread_id)):
        if question.state != "open":
            continue
        asked_by_run = str((question.asker.get("ref") or {}).get("run_id") or "") == str(run_id)
        if run_id is not None and not asked_by_run and question.asker.get("kind") not in kinds:
            continue
        done = store.expire(question.id, EXPIRED_ASKER_ENDED)
        if done is not None:
            ended.append(done)
    for question in ended:
        await dispatch(question, app=app, request=request)
    return ended


async def sweep(app: Any, *, now: datetime | None = None) -> list[Question]:
    """Expire due questions and resume their askers (QC-04). Also dispatches a
    terminal question whose dispatch was never taken (its worker died between
    the claim and the call)."""
    now = now or datetime.now(UTC)
    store = get_store()
    expired = store.expire_due(now)
    terminal = [q for q in store.all() if q.state in (ANSWERED, EXPIRED) and (now - q.created_at).total_seconds() < 24 * 3600 + TIMEOUT_MAX_SECONDS]
    seen = {q.id for q in expired}
    for question in [*expired, *(q for q in terminal if q.id not in seen and not store.was_taken(q.id, "dispatched"))]:
        await dispatch(question, app=app)
    # An answer whose resume found the chat busy is kept and offered again
    # (the handler is idempotent: a turn's answer is carried by one resume).
    for question in terminal:
        if store.was_taken(question.id, "deferred") and not store.was_taken(question.id, "included"):
            handler = _HANDLERS.get(str(question.asker.get("kind") or ""))
            if handler is None:
                continue
            try:
                await handler(question, app=app, request=None, retry=True)
            except Exception:  # noqa: BLE001
                logger.exception("question %s: deferred resume failed", question.id)
    store.prune(now)
    return expired


async def sweep_forever(app: Any, *, interval: float = SWEEP_INTERVAL_SECONDS) -> None:
    import asyncio

    while True:
        await asyncio.sleep(interval)
        try:
            await sweep(app)
        except Exception:  # noqa: BLE001
            logger.exception("question sweep failed")


# -- the API's view -------------------------------------------------------------


def public_view(question: Question, now: datetime | None = None) -> dict[str, Any]:
    """What the card shows. Question, context and option text are content:
    sent through the display sanitiser (005 Amendment 1); the frontend applies
    it again. Server-only fields (asker_data, the asker's ref) are not sent."""
    from app.gateway.display_safe import safe_field, safe_lines

    now = now or datetime.now(UTC)
    kind = str(question.asker.get("kind") or "")
    name = asker_name(kind)
    ref = question.asker.get("ref") or {}
    state = question.state
    if state == "open" and question.is_due(now):
        state = EXPIRED  # due, not yet swept: shown as what it is
    answer = None
    if question.answer:
        answer = {
            "option": question.answer.get("option"),
            "text": safe_lines(question.answer.get("text")) if question.answer.get("text") else None,
            "via": question.answer.get("via"),
            "at": question.answer.get("at"),
        }
    return {
        "id": question.id,
        "thread_id": question.thread_id,
        "asker": {"kind": kind, "name": name, "tool_call_id": str(ref.get("tool_call_id") or "") or None},
        "origin": question.origin,
        "question": safe_lines(question.question),
        "context": safe_lines(question.context),
        "options": [{"label": safe_field(o["label"]), "description": safe_field(o["description"])} for o in question.options],
        "recommended": question.recommended,
        "recommended_label": None if question.recommended is None else ("Recommended" if question.origin == "server" else f"Suggested by {_in_sentence(name)}"),
        "on_expiry": question.on_expiry,
        "expires_at": question.expires_at.isoformat(),
        "created_at": question.created_at.isoformat(),
        "state": state,
        "expired_reason": question.expired_reason or ("timeout" if state == EXPIRED else ""),
        "answer": answer,
        "outcome": safe_field(question.outcome_text() if question.state != "open" else ("" if state == "open" else _due_text(question))),
        "free_text_max": FREE_TEXT_MAX,
    }


def _in_sentence(name: str) -> str:
    """ "The coding job" reads "the coding job" mid-sentence."""
    return "t" + name[1:] if name.startswith("The ") else name


def _due_text(question: Question) -> str:
    from copy import copy

    shown = copy(question)
    shown.state = EXPIRED
    shown.expired_reason = "timeout"
    return shown.outcome_text()
