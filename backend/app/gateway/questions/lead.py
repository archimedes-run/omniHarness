"""The lead as a question asker (asker.kind = "lead", Slice 1b D1b-10).

`ask_clarification` still ends the lead's run at the question (Slice 0's
send-back rules are unchanged: ClarificationMiddleware decides first whether
the question is asked at all). When it is asked in a chat turn, the
middleware calls `open_lead_question` (through the harness hook
omniharness.agents.questions), which records a question card.

How the answer reaches the lead (QC-07):

  * by the card (a button or its text box): a server-started resume run whose
    input is the answer as the TOOL RESULT of an `ask_clarification` call,
    tagged untrusted, never a user turn (app.gateway.resume.resume_after_question);
  * by the owner's tagged message while it is the only open question: that
    message is already the owner's turn and the lead is running on it; there
    is nothing to resume;
  * on expiry: the question was written by the model, so it expires to
    `stop` and nothing runs (QC-05: no model spend). The card says so. Only
    when the same turn also has Tier 3 cards whose outcomes were waiting on
    this question does the lead resume, to report them (QC-08).
"""

from __future__ import annotations

import logging
from typing import Any

from .service import register_asker
from .store import (
    EXPIRED_ASKER_ENDED,
    ORIGIN_CONTENT,
    VIA_TAGGED_MESSAGE,
    Question,
    build_question,
)

logger = logging.getLogger(__name__)

LEAD = "lead"
#: The lead's question timeout (question-card.md: lead 24 h).
LEAD_TIMEOUT_SECONDS = 24 * 3600


def _turn(messages: list[Any] | None, context: dict) -> tuple[bool, str]:
    """(private_read, turn_key) of the turn asking: the same walk the policy
    layer groups a turn's cards by, so the lead's question and its cards share
    a turn key. Unknown privacy counts as private (the strict side)."""
    from omniharness.agents.called_agents import RESUME_ACTION_KEY

    try:
        from app.policy.private_reads import private_reads_in_turn
        from app.policy.registration import shared_loader
        from omniharness.config import get_app_config

        policy = getattr(get_app_config(), "policy", None)
        privacy = private_reads_in_turn(messages, shared_loader(policy).load(notify=False))
        private, key = privacy.private, privacy.turn_key
    except Exception:  # noqa: BLE001 - no policy config: judged private, keyed by nothing
        logger.debug("question: turn privacy unknown", exc_info=True)
        private, key = True, ""
    resume = context.get(RESUME_ACTION_KEY)
    if isinstance(resume, dict) and resume.get("private_read", True) is not False:
        private = True
    return private, key


def asks_with_a_card(context: dict | None) -> bool:
    """Only the lead in a person's chat asks with a card: not a scheduled run
    (nobody is there), not an invited agent, a subagent or an @-called agent
    (their questions are their inviter's business)."""
    from app.policy.provenance import is_synthetic_turn
    from omniharness.agents.called_agents import CALLED_AGENT_KEY
    from omniharness.agents.invitation import DELEGATION_CHAIN_KEY, INVITED_ORIGIN_KEY

    ctx = context or {}
    if not ctx.get("thread_id") or not ctx.get("user_id"):
        return False
    if is_synthetic_turn(ctx) or ctx.get(CALLED_AGENT_KEY) or INVITED_ORIGIN_KEY in ctx or ctx.get(DELEGATION_CHAIN_KEY):
        return False
    return True


def open_lead_question(
    *,
    question: str,
    options: list[Any],
    recommended: int | None,
    context_text: str,
    tool_call_id: str,
    messages: list[Any] | None,
    runtime_context: dict | None,
) -> dict[str, Any] | None:
    """Record the lead's question as a card. None when this run does not ask
    with a card (the question is then shown as text, as before); raises
    store.QuestionError when the question breaks the contract."""
    from omniharness.agents.tool_surface import lead_surface

    from .service import get_store

    ctx = dict(runtime_context or {})
    if not asks_with_a_card(ctx):
        return None
    private, turn_key = _turn(messages, ctx)
    record = build_question(
        thread_id=str(ctx["thread_id"]),
        owner_id=str(ctx["user_id"]),
        asker={"kind": LEAD, "ref": {"run_id": str(ctx.get("run_id") or ""), "tool_call_id": str(tool_call_id or "")}},
        # The model wrote the question and its options: content, so it
        # expires to stop and its suggestion is labelled as the lead's.
        origin=ORIGIN_CONTENT,
        question=question,
        options=options,
        recommended=recommended,
        timeout_seconds=LEAD_TIMEOUT_SECONDS,
        context=context_text,
        asker_data={"turn_key": turn_key, "private_read": private, "surface": lead_surface(ctx)},
    )
    get_store().save(record)
    logger.info("question %s opened by the lead", record.id)
    return {"id": record.id, "expires_at": record.expires_at.isoformat()}


async def resume_lead(question: Question, *, app: Any = None, request: Any = None, retry: bool = False) -> dict[str, Any] | None:
    """The lead's resume handler (called once per terminal question)."""
    from .service import get_store

    store = get_store()
    answer = question.answer or {}
    if answer.get("via") == VIA_TAGGED_MESSAGE or question.expired_reason == EXPIRED_ASKER_ENDED:
        # Typed: the owner's own turn is already running the lead. Ended: the
        # task stopped. Either way nothing is resumed, and a later card
        # resume of the same turn does not report it again.
        store.take_once(question.id, "included")
        return None
    from app.gateway.resume import _owner_request, resume_after_question

    # From the sweep (an expiry, or an answer whose resume found the chat
    # busy): resumed as the question's owner, and not when the person has
    # moved on since.
    from_sweep = request is None
    if request is None:
        request = await _owner_request(app, user_id=question.owner_id)
        if request is None:
            return None
    run_id = await resume_after_question(request, question, from_sweep=from_sweep)
    return {"resume_run_id": run_id} if run_id else None


def install() -> None:
    register_asker(LEAD, resume_lead, display_name="OmniHarness")


def makes_cards(runtime_context: dict | None) -> bool:
    """For the harness: does this run ask with a card at all? (The card's
    option limits are checked only for runs that do.)"""
    try:
        return asks_with_a_card(runtime_context)
    except Exception:  # noqa: BLE001
        return False
