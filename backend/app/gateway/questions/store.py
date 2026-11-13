"""The question record and its durable store (specs/009-orchestration/question-card.md).

One JSON file per question, in a folder every gateway worker shares, the same
shape as the policy layer's pending store (app/policy/pending.py) and for the
same reason: a question opened by one worker is answered through another.

THE TERMINAL CLAIM IS ATOMIC. A question becomes `answered` or `expired`
exactly once. Both an answer and an expiry first hard-link the record to
`<id>.final`; `os.link` fails if the link exists, so of a click, a typed reply
in another worker and the sweep, exactly one wins and the others are told the
question is no longer open. Terminal states never change.

THE RESUME IS ONE-SHOT (QC-06). The asker's resume handler is called once per
question: the caller links `<id>.dispatched` before the call, and a failed
call is never retried.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import secrets
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# -- the contract's limits ----------------------------------------------------

QUESTION_MAX = 500
CONTEXT_MAX = 500
OPTIONS_MIN = 2
OPTIONS_MAX = 4
LABEL_MAX = 60
DESCRIPTION_MAX = 200
FREE_TEXT_MAX = 2000
#: The longest any asker may wait (QC record: max 7 days).
TIMEOUT_MAX_SECONDS = 7 * 24 * 3600

ORIGIN_SERVER = "server"  # the asker's own code wrote the question and options
ORIGIN_CONTENT = "content"  # a model or worker wrote them

OPEN = "open"
ANSWERED = "answered"
EXPIRED = "expired"

EXPIRY_STOP = "stop"
EXPIRED_TIMEOUT = "timeout"
EXPIRED_ASKER_ENDED = "asker_ended"

VIA_BUTTON = "button"
VIA_TAGGED_MESSAGE = "tagged_message"


class QuestionError(ValueError):
    """A question the contract refuses (bad limits, content expiring to an option)."""


@dataclass
class Question:
    thread_id: str
    owner_id: str
    asker: dict[str, Any]
    origin: str
    question: str
    options: list[dict[str, str]]
    expires_at: datetime
    recommended: int | None = None
    on_expiry: str = EXPIRY_STOP
    context: str = ""
    #: The asker kind's own extra data (the lead's turn key and run surface).
    #: Server-written only; never shown, never from a request.
    asker_data: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: "q" + secrets.token_hex(8))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    state: str = OPEN
    expired_reason: str = ""
    answer: dict[str, Any] | None = None

    # -- reading ---------------------------------------------------------------

    def is_due(self, now: datetime) -> bool:
        return self.state == OPEN and now >= self.expires_at

    def is_open(self, now: datetime) -> bool:
        return self.state == OPEN and now < self.expires_at

    def default_option(self) -> int | None:
        """The option an expiry applies, or None for `stop`."""
        if self.on_expiry.startswith("option:"):
            return int(self.on_expiry.split(":", 1)[1])
        return None

    def outcome_text(self) -> str:
        """What the card and the asker are told, in the same words (QC-04)."""
        if self.state == ANSWERED and self.answer:
            if self.answer.get("option") is not None:
                return f"Answered: {self.options[int(self.answer['option'])]['label']}"
            return "Answered in the person's own words."
        if self.state == EXPIRED:
            if self.expired_reason == EXPIRED_ASKER_ENDED:
                return "Closed without an answer: the task that asked it ended."
            at = self.expires_at.astimezone(UTC).strftime("%H:%M UTC")
            default = self.default_option()
            if default is not None:
                return f"No answer by {at}; used the default: {self.options[default]['label']}."
            return f"No answer by {at}; stopped this path."
        return ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "thread_id": self.thread_id,
            "owner_id": self.owner_id,
            "asker": dict(self.asker),
            "origin": self.origin,
            "question": self.question,
            "context": self.context,
            "options": [dict(o) for o in self.options],
            "recommended": self.recommended,
            "on_expiry": self.on_expiry,
            "expires_at": self.expires_at.isoformat(),
            "created_at": self.created_at.isoformat(),
            "state": self.state,
            "expired_reason": self.expired_reason,
            "answer": dict(self.answer) if self.answer else None,
            "asker_data": dict(self.asker_data),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Question:
        return cls(
            id=str(raw["id"]),
            thread_id=str(raw["thread_id"]),
            owner_id=str(raw["owner_id"]),
            asker=dict(raw.get("asker") or {}),
            # A record without an origin is judged as content (the strict side).
            origin=ORIGIN_SERVER if raw.get("origin") == ORIGIN_SERVER else ORIGIN_CONTENT,
            question=str(raw.get("question") or ""),
            context=str(raw.get("context") or ""),
            options=[{"label": str(o.get("label") or ""), "description": str(o.get("description") or "")} for o in raw.get("options") or []],
            recommended=raw.get("recommended") if isinstance(raw.get("recommended"), int) else None,
            on_expiry=str(raw.get("on_expiry") or EXPIRY_STOP),
            expires_at=datetime.fromisoformat(raw["expires_at"]),
            created_at=datetime.fromisoformat(raw["created_at"]) if raw.get("created_at") else datetime.now(UTC),
            state=str(raw.get("state") or OPEN),
            expired_reason=str(raw.get("expired_reason") or ""),
            answer=dict(raw["answer"]) if isinstance(raw.get("answer"), dict) else None,
            asker_data=dict(raw.get("asker_data") or {}),
        )


def _clean(text: Any) -> str:
    return str(text if text is not None else "").strip()


def build_question(
    *,
    thread_id: str,
    owner_id: str,
    asker: dict[str, Any],
    origin: str,
    question: str,
    options: list[Any],
    recommended: int | None = None,
    timeout_seconds: float,
    on_expiry: str = EXPIRY_STOP,
    context: str = "",
    asker_data: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> Question:
    """A new open question, checked against the contract, or QuestionError.

    The rules that matter for safety are here, not in any asker: a
    content-originated question always expires to `stop` (QC-05); options are
    2 to 4, distinct and non-empty; the recommended one exists.
    """
    if origin not in (ORIGIN_SERVER, ORIGIN_CONTENT):
        raise QuestionError("origin must be server or content")
    if not thread_id or not owner_id:
        raise QuestionError("a question belongs to one thread and one owner")
    kind = _clean((asker or {}).get("kind"))
    if not kind:
        raise QuestionError("asker.kind is required")
    text = _clean(question)
    if not 1 <= len(text) <= QUESTION_MAX:
        raise QuestionError(f"the question must be 1 to {QUESTION_MAX} characters")
    ctx = _clean(context)
    if len(ctx) > CONTEXT_MAX:
        raise QuestionError(f"the context must be at most {CONTEXT_MAX} characters")
    cleaned: list[dict[str, str]] = []
    for raw in options or []:
        if isinstance(raw, dict):
            label, description = _clean(raw.get("label")), _clean(raw.get("description"))
        else:
            label, description = _clean(raw), ""
        if not 1 <= len(label) <= LABEL_MAX:
            raise QuestionError(f"each option label must be 1 to {LABEL_MAX} characters")
        if len(description) > DESCRIPTION_MAX:
            raise QuestionError(f"each option description must be at most {DESCRIPTION_MAX} characters")
        cleaned.append({"label": label, "description": description})
    if not OPTIONS_MIN <= len(cleaned) <= OPTIONS_MAX:
        raise QuestionError(f"a question needs {OPTIONS_MIN} to {OPTIONS_MAX} options")
    if len({o["label"].casefold() for o in cleaned}) != len(cleaned):
        raise QuestionError("option labels must be distinct")
    if recommended is not None and not (isinstance(recommended, int) and 0 <= recommended < len(cleaned)):
        raise QuestionError("recommended must name one of the options")
    expiry = _clean(on_expiry) or EXPIRY_STOP
    if expiry != EXPIRY_STOP:
        if not expiry.startswith("option:"):
            raise QuestionError("on_expiry must be stop or option:<i>")
        # QC-05: only the asker's own code may choose a default; a question a
        # model or worker wrote always expires to stop.
        if origin != ORIGIN_SERVER:
            raise QuestionError("a content-originated question always expires to stop")
        try:
            index = int(expiry.split(":", 1)[1])
        except ValueError as exc:
            raise QuestionError("on_expiry must be stop or option:<i>") from exc
        if not 0 <= index < len(cleaned):
            raise QuestionError("on_expiry names no option")
    if not 0 < float(timeout_seconds) <= TIMEOUT_MAX_SECONDS:
        raise QuestionError("the timeout must be between 1 second and 7 days")
    now = now or datetime.now(UTC)
    return Question(
        thread_id=str(thread_id),
        owner_id=str(owner_id),
        asker={"kind": kind, "ref": dict((asker or {}).get("ref") or {})},
        origin=origin,
        question=text,
        context=ctx,
        options=cleaned,
        recommended=recommended,
        on_expiry=expiry,
        expires_at=now + timedelta(seconds=float(timeout_seconds)),
        created_at=now,
        asker_data=dict(asker_data or {}),
    )


@dataclass
class QuestionStore:
    """One JSON file per question; the terminal claim is a hard link."""

    directory: Path

    def __post_init__(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, qid: str) -> Path:
        return self.directory / f"{qid}.json"

    def _safe_id(self, qid: str) -> bool:
        return bool(qid) and qid.isalnum() and len(qid) <= 64

    def save(self, question: Question) -> Question:
        fd, tmp = tempfile.mkstemp(dir=str(self.directory), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(question.to_dict(), handle, indent=2, sort_keys=True)
            os.replace(tmp, self._path(question.id))
        finally:
            Path(tmp).unlink(missing_ok=True)
        return question

    def get(self, qid: str) -> Question | None:
        if not self._safe_id(str(qid or "")):
            return None
        try:
            return Question.from_dict(json.loads(self._path(qid).read_text(encoding="utf-8")))
        except FileNotFoundError:
            return None
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
            logger.error("question %s is unreadable: %s", qid, exc)
            return None

    def all(self) -> list[Question]:
        out = []
        for path in sorted(self.directory.glob("*.json")):
            question = self.get(path.stem)
            if question is not None:
                out.append(question)
        return out

    def in_thread(self, thread_id: str) -> list[Question]:
        return [q for q in self.all() if q.thread_id == thread_id]

    def open_in_thread(self, thread_id: str, owner_id: str | None, now: datetime) -> list[Question]:
        """Open, not yet due questions of this thread and owner."""
        return [q for q in self.in_thread(thread_id) if q.is_open(now) and (owner_id is None or q.owner_id == str(owner_id))]

    # -- the one terminal claim ------------------------------------------------

    def _finalise(self, qid: str, change: Any) -> Question | None:
        """Take the terminal claim and apply `change` to the open record.
        Returns the saved terminal question for exactly one caller, None for
        every other (already answered, expired, or missing)."""
        source, final = self._path(qid), self.directory / f"{qid}.final"
        if not self._safe_id(qid) or not source.exists():
            return None
        try:
            os.link(source, final)
        except FileExistsError:
            return None
        except OSError as exc:
            logger.error("could not claim question %s: %s", qid, exc)
            return None
        question = self.get(qid)
        if question is None or question.state != OPEN:
            return None
        change(question)
        return self.save(question)

    def answer(self, qid: str, *, option: int | None, text: str | None, via: str, now: datetime | None = None) -> Question | None:
        """Record the answer, once. None when the question is not open (or is
        due: an answer that arrives after the deadline expires it instead)."""
        now = now or datetime.now(UTC)
        current = self.get(qid)
        if current is None or current.state != OPEN:
            return None
        if current.is_due(now):
            self.expire(qid, EXPIRED_TIMEOUT, now=now)
            return None

        def apply(q: Question) -> None:
            q.state = ANSWERED
            q.answer = {"option": option, "text": text, "via": via, "at": now.isoformat()}

        return self._finalise(qid, apply)

    def expire(self, qid: str, reason: str, *, now: datetime | None = None) -> Question | None:
        def apply(q: Question) -> None:
            q.state = EXPIRED
            q.expired_reason = reason

        return self._finalise(qid, apply)

    def expire_due(self, now: datetime) -> list[Question]:
        return [q for q in (self.expire(c.id, EXPIRED_TIMEOUT, now=now) for c in self.all() if c.is_due(now)) if q is not None]

    # -- one-shot locks --------------------------------------------------------

    def take_once(self, qid: str, name: str) -> bool:
        """True for exactly one caller ever (a hard link named `<id>.<name>`)."""
        if not self._safe_id(qid) or not name.isalpha():
            return False
        source = self._path(qid)
        if not source.exists():
            return False
        try:
            os.link(source, self.directory / f"{qid}.{name}")
        except (FileExistsError, OSError):
            return False
        return True

    def was_taken(self, qid: str, name: str) -> bool:
        return (self.directory / f"{qid}.{name}").exists()

    def delete_thread(self, thread_id: str) -> None:
        """Forget a deleted thread's questions (after expiring the open ones)."""
        for question in self.in_thread(thread_id):
            for path in self.directory.glob(f"{question.id}.*"):
                with contextlib.suppress(FileNotFoundError):
                    path.unlink()
