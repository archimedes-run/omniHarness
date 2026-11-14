"""Middleware for intercepting clarification requests and presenting them to the user."""

import json
import logging
from collections.abc import Callable
from hashlib import sha256
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import hook_config
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import END
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from omniharness.agents.questions import QUESTION_MARKER, QuestionRefused, makes_cards, open_question

logger = logging.getLogger(__name__)


def _options_list(raw: object) -> list[str]:
    """The options as a list of stripped strings (some models send a JSON
    string instead of an array)."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            raw = [raw]
    if raw is None:
        return []
    if not isinstance(raw, list):
        raw = [raw]
    return [str(o).strip() for o in raw]


def _recommended_index(raw: object, count: int) -> int | None:
    """The tool's 1-based `recommended` as a 0-based index, or None."""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        number = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return number - 1 if 1 <= number <= count else None


#: On every ask_clarification result that did NOT ask the person anything
#: ("Not asked: ..."): an instruction to the model, never shown in the chat as
#: a question (frontend core/messages/utils.ts hides it).
NOT_ASKED_MARKER = "omniharness_not_asked"


def problem_message(problem: str, call_id: str, *, marker: str | None = None) -> ToolMessage:
    """A question that cannot be asked as it is: the model is told why and
    runs again (it is not a pause)."""
    kwargs = {NOT_ASKED_MARKER: True, **({marker: True} if marker else {})}
    return ToolMessage(
        content=f"Not asked: {problem}. Ask again with that fixed, or pick a sensible default, state it, and continue.",
        tool_call_id=call_id,
        name="ask_clarification",
        additional_kwargs=kwargs,
    )


#: The builder's "what should it do?" question: at most this many suggestions.
BUILDER_ASK_MAX_OPTIONS = 3
#: The caption a builder question's suggestions carry when memory informs them.
MEMORY_CAPTION = "Suggestions based on what I know about you"


def _builder_refusal_index(turn: list) -> int | None:
    """Index of the latest builder "ask first" refusal in the turn, or None."""
    from omniharness.runtime.builder.surface import ASK_FIRST_PREFIX

    found = None
    for index, message in enumerate(turn):
        if isinstance(message, ToolMessage) and message.name == "builder_draft" and str(message.content).startswith(ASK_FIRST_PREFIX):
            found = index
    return found


def builder_ask(turn: list, call_id: str) -> bool:
    """This call is THE one question asked directly after the builder's latest
    "ask first" refusal (spec 010)."""
    index = _builder_refusal_index(turn)
    if index is None:
        return False
    following = next((m for m in turn[index + 1 :] if getattr(m, "tool_calls", None)), None)
    return following is not None and any(c.get("id") == call_id for c in following.tool_calls)


def builder_answered(turn: list, context: dict | None) -> bool:
    """A run resumed on the owner's answer to the builder's question, with no
    new "ask first" refusal since: the owner has said what it is for, so it is
    drafted now, not asked about again (spec 010)."""
    from omniharness.runtime.builder.surface import QUESTION_ANSWER_KEY, question_resume

    if not question_resume(context):
        return False
    index = _builder_refusal_index(turn)
    if index is None:
        return False
    answered = [i for i, m in enumerate(turn) if isinstance(m, ToolMessage) and (m.additional_kwargs or {}).get(QUESTION_ANSWER_KEY)]
    return bool(answered) and index < answered[-1]


def answered_refusal(call_id: str) -> ToolMessage:
    """A question after the owner answered the builder's question: not asked."""
    return ToolMessage(
        content="Not asked: the person already answered what it should do. Draft it now from their answer, with sensible defaults for anything else, and propose saving it.",
        tool_call_id=call_id,
        name="ask_clarification",
        additional_kwargs={NOT_ASKED_MARKER: True},
    )


def _memory_on(context: dict | None) -> bool:
    """Memory informs this chat: on in the install, and not switched off for
    the chat (the run context's `memory_off`, when the gateway sets it)."""
    if (context or {}).get("memory_off"):
        return False
    try:
        from omniharness.config import get_app_config

        return bool(get_app_config().memory.enabled)
    except Exception:  # noqa: BLE001 - unknown: no suggestions from memory
        return False


def shape_builder_question(args: dict, context: dict | None) -> dict:
    """The builder's one question: at most 3 suggestions, each at most 60
    characters, none pre-picked (they come from what the model knows, so all
    look equal), captioned as suggestions from memory when memory is on in
    this chat, and none at all when it is off."""
    options = _options_list(args.get("options")) if _memory_on(context) else []
    trimmed = [(o if len(o) <= 60 else o[:59].rstrip() + "…") for o in options][:BUILDER_ASK_MAX_OPTIONS]
    trimmed = list(dict.fromkeys(trimmed))
    if len(trimmed) == 1:
        trimmed = []
    return {**args, "options": trimmed, "recommended": None, "context": MEMORY_CAPTION if trimmed else ""}


def card_questions_enabled() -> bool:
    from omniharness.agents import questions

    return questions._opener is not None


class ClarificationMiddlewareState(AgentState):
    """Compatible with the `ThreadState` schema."""

    pass


class ClarificationMiddleware(AgentMiddleware[ClarificationMiddlewareState]):
    """Intercepts clarification tool calls and interrupts execution to present questions to the user.

    When the model calls the `ask_clarification` tool, this middleware:
    1. Intercepts the tool call before execution
    2. Extracts the clarification question and metadata
    3. Formats a user-friendly message
    4. Returns a Command that interrupts execution and presents the question
    5. Waits for user response before continuing

    This replaces the tool-based approach where clarification continued the conversation flow.
    """

    state_schema = ClarificationMiddlewareState

    def _stable_message_id(self, tool_call_id: str, formatted_message: str) -> str:
        """Build a deterministic message ID so retried clarification calls replace, not append."""
        if tool_call_id:
            return f"clarification:{tool_call_id}"
        digest = sha256(formatted_message.encode("utf-8")).hexdigest()[:16]
        return f"clarification:{digest}"

    def _is_chinese(self, text: str) -> bool:
        """Check if text contains Chinese characters.

        Args:
            text: Text to check

        Returns:
            True if text contains Chinese characters
        """
        return any("\u4e00" <= char <= "\u9fff" for char in text)

    def _format_clarification_message(self, args: dict) -> str:
        """Format the clarification arguments into a user-friendly message.

        Args:
            args: The tool call arguments containing clarification details

        Returns:
            Formatted message string
        """
        from omniharness.tools.builtins.clarification_tool import CLARIFICATION_TYPES

        question = args.get("question", "")
        clarification_type = args.get("clarification_type", "missing_info")
        if clarification_type not in CLARIFICATION_TYPES:
            # A removed kind (approach_choice, risk_confirmation, suggestion:
            # spec 009 FR-057) sent anyway is shown as a plain question.
            clarification_type = "missing_info"
        context = args.get("context")
        options = args.get("options", [])

        # Some models (e.g. Qwen3-Max) serialize array parameters as JSON strings
        # instead of native arrays. Deserialize and normalize so `options`
        # is always a list for the rendering logic below.
        if isinstance(options, str):
            try:
                options = json.loads(options)
            except (json.JSONDecodeError, TypeError):
                options = [options]

        if options is None:
            options = []
        elif not isinstance(options, list):
            options = [options]

        # Type-specific icons
        type_icons = {
            "missing_info": "❓",
            "ambiguous_requirement": "🤔",
            "approach_choice": "🔀",
            "risk_confirmation": "⚠️",
            "suggestion": "💡",
        }

        icon = type_icons.get(clarification_type, "❓")

        # Build the message naturally
        message_parts = []

        # Add icon and question together for a more natural flow
        if context:
            # If there's context, present it first as background
            message_parts.append(f"{icon} {context}")
            message_parts.append(f"\n{question}")
        else:
            # Just the question with icon
            message_parts.append(f"{icon} {question}")

        # Add options in a cleaner format
        recommended = _recommended_index(args.get("recommended"), len(options))
        if options and len(options) > 0:
            message_parts.append("")  # blank line for spacing
            for i, option in enumerate(options, 1):
                mark = " (suggested)" if recommended == i - 1 else ""
                message_parts.append(f"  {i}. {option}{mark}")

        return "\n".join(message_parts)

    #: On the tool result that sent a mid-task question back (FR-057): one
    #: per turn, so a task that truly became impossible can still ask.
    DEFERRED_MARKER = "omniharness_clarification_deferred"

    def _mid_task_deferral(self, request: ToolCallRequest) -> ToolMessage | None:
        """A question asked after work has started in this turn is sent back
        once (spec 009 FR-056/FR-057): the model is told to pick a default and
        continue, or to stop as blocked. Before any work, or the second time in
        a turn, the question goes to the person as usual."""
        state = getattr(request, "state", None) or {}
        messages = state.get("messages") if isinstance(state, dict) else None
        return self._deferral(messages, request.tool_call.get("id", ""), request.tool_call.get("args") or {})

    #: Sent back for a question asked before any work whose kind is
    #: "ambiguous_requirement" (owner rule, 2026-11-13: a research request is
    #: researched, not answered with a question). "missing_info" before work
    #: still goes to the person.
    AMBIGUOUS_TEXT = (
        "Not asked: an open word in the request (latest, best, which kind) is not a reason to stop before working. "
        "Take the most common reading, state it in one line in your reply, and do the work with your read tools. "
        "Ask only if a required value is missing that no read can find."
    )

    def _deferral(self, messages: list | None, call_id: str, args: dict | None = None) -> ToolMessage | None:
        from omniharness.agents.working_loop import NON_EVIDENCE_TOOLS, tool_steps, turn_messages

        if not messages:
            return None
        turn = turn_messages(list(messages))
        if builder_ask(turn, call_id):
            # The builder refused to draft something new with no purpose and
            # asked for ONE question (spec 010): that question, and only it.
            return None
        started = [s for s in tool_steps(turn) if s["name"] not in NON_EVIDENCE_TOOLS and s["id"] != call_id and s["ok"] is not None]
        ambiguous = str((args or {}).get("clarification_type") or "") == "ambiguous_requirement"
        if not started and not ambiguous:
            return None
        for message in turn:
            if isinstance(message, ToolMessage) and (message.additional_kwargs or {}).get(self.DEFERRED_MARKER):
                return None
        logger.info("Clarification sent back once with the default rule (%s)", "mid-task" if started else "ambiguous, before work")
        return ToolMessage(
            content=(
                (
                    "Not asked: work on this task has already started. Do not ask the person to choose mid-task. "
                    "Pick the most sensible default, state the assumption in one line, and continue. If the task truly "
                    "cannot go ahead, stop and say what is done, the exact blocker and what the person needs to do."
                )
                if started
                else self.AMBIGUOUS_TEXT
            ),
            tool_call_id=call_id,
            name="ask_clarification",
            additional_kwargs={self.DEFERRED_MARKER: True, NOT_ASKED_MARKER: True},
        )

    # -- the question card ---------------------------------------------------

    #: On the tool result that sent a badly shaped question back: once per
    #: turn; a second bad one is shown as a free-form question instead.
    SHAPE_MARKER = "omniharness_question_shape"

    @staticmethod
    def _problem_of(args: dict) -> str | None:
        question = str(args.get("question") or "").strip()
        options = _options_list(args.get("options"))
        if not 1 <= len(question) <= 500:
            return "the question must be 1 to 500 characters"
        if len(options) == 1 or len(options) > 4:
            return "give 2 to 4 short options the person can pick from, or none for an open question (they can always type their own answer)"
        if any(not 1 <= len(o) <= 60 for o in options):
            return "each option must be 1 to 60 characters"
        if len({o.casefold() for o in options}) != len(options):
            return "the options must be different from each other"
        raw = args.get("recommended")
        if raw is not None and options and _recommended_index(raw, len(options)) is None:
            return f"recommended must be an option number from 1 to {len(options)}"
        return None

    def _shape(self, args: dict, context: dict | None, messages: list | None) -> tuple[str | None, dict]:
        """(why this question cannot be a card, the args to use). Checked only
        for runs that get a card; the store checks the same limits again. A
        question is sent back at most ONCE per turn: the second bad one is
        shown as a free-form question (its options dropped), never looped."""
        if not card_questions_enabled() or not makes_cards(context):
            return None, args
        problem = self._problem_of(args)
        if problem is None:
            return None, args
        from omniharness.agents.working_loop import turn_messages

        sent_back = any(isinstance(m, ToolMessage) and (m.additional_kwargs or {}).get(self.SHAPE_MARKER) for m in turn_messages(list(messages or [])))
        if not sent_back:
            return problem, args
        fixed = {**args, "question": str(args.get("question") or "").strip()[:500] or "Could you tell me more?", "options": [], "recommended": None}
        return None, fixed

    @staticmethod
    def _turn_of(state: object) -> list:
        from omniharness.agents.working_loop import turn_messages

        messages = state.get("messages") if isinstance(state, dict) else None
        return turn_messages(list(messages or []))

    @staticmethod
    def _context_of(runtime: object) -> dict:
        context = getattr(runtime, "context", None) or {}
        return dict(context) if isinstance(context, dict) else {}

    def _open_card(self, request: ToolCallRequest, args: dict, tool_call_id: str) -> dict | None:
        runtime = getattr(request, "runtime", None)
        context = getattr(runtime, "context", None) or {}
        state = getattr(request, "state", None) or {}
        options = _options_list(args.get("options"))
        card = open_question(
            question=str(args.get("question") or ""),
            options=options,
            recommended=_recommended_index(args.get("recommended"), len(options)),
            context_text=str(args.get("context") or ""),
            tool_call_id=tool_call_id,
            messages=list(state.get("messages") or []) if isinstance(state, dict) else [],
            runtime_context=dict(context) if isinstance(context, dict) else {},
        )
        if card is not None:
            try:
                from langgraph.config import get_stream_writer

                get_stream_writer()({"type": "question.opened", "question_id": card["id"], "tool_call_id": tool_call_id})
            except Exception:  # noqa: BLE001 - no live stream (a test, a resume): the card is read from the API
                pass
        return card

    def _handle_clarification(self, request: ToolCallRequest) -> Command | ToolMessage:
        """Handle clarification request and return command to interrupt execution.

        Args:
            request: Tool call request

        Returns:
            Command that interrupts execution with the formatted clarification message
        """
        state = getattr(request, "state", None) or {}
        turn = self._turn_of(state)
        call_id = request.tool_call.get("id", "")
        context = self._context_of(getattr(request, "runtime", None))
        if builder_answered(turn, context):
            return answered_refusal(call_id)
        deferred = self._mid_task_deferral(request)
        if deferred is not None:
            return deferred

        # Extract clarification arguments
        args = request.tool_call.get("args", {})
        if builder_ask(turn, call_id):
            args = shape_builder_question(dict(args), context)
        question = args.get("question", "")

        # Get the tool call ID
        tool_call_id = request.tool_call.get("id", "")
        state = getattr(request, "state", None) or {}
        problem, args = self._shape(args, self._context_of(getattr(request, "runtime", None)), state.get("messages") if isinstance(state, dict) else None)
        if problem is not None:
            return problem_message(problem, tool_call_id, marker=self.SHAPE_MARKER)

        logger.info("Intercepted clarification request")
        logger.debug("Clarification question: %s", question)

        # Format the clarification message
        formatted_message = self._format_clarification_message(args)

        # The question card (009 question-card.md): recorded by the gateway,
        # answered only by the owner's click or the owner's own tagged reply.
        card = None
        try:
            card = self._open_card(request, args, tool_call_id)
        except QuestionRefused as exc:
            return problem_message(str(exc), tool_call_id)
        kwargs = {}
        if card is not None:
            kwargs[QUESTION_MARKER] = {"id": card["id"]}
            # Read as text where there is no card (a channel, the model's own
            # history): how to answer.
            formatted_message += "\n\nAnswer on the card, or reply with an option number or your own words." if _options_list(args.get("options")) else "\n\nAnswer on the card, or reply with your answer."

        # Create a ToolMessage with the formatted question
        # This will be added to the message history
        tool_message = ToolMessage(
            id=self._stable_message_id(tool_call_id, formatted_message),
            content=formatted_message,
            tool_call_id=tool_call_id,
            name="ask_clarification",
            additional_kwargs=kwargs,
        )

        # Return a Command that:
        # 1. Adds the formatted tool message
        # 2. Interrupts execution by going to __end__
        # Note: We don't add an extra AIMessage here - the frontend will detect
        # and display ask_clarification tool messages directly
        return Command(
            update={"messages": [tool_message]},
            goto=END,
        )

    # -- a question that is the reply's ONLY call --------------------------
    #
    # ask_clarification is `return_direct`: when it is the only tool call of a
    # model reply, the agent ends after the tool node whatever the tool
    # returned. So a mid-task question sent back from wrap_tool_call (below)
    # ended the run on the "Not asked" result and the task never continued
    # (eval M-MIDASK passed on its checks while its final reply was empty).
    # That case is handled here, before the tool node: the "Not asked" result
    # is added for the call and the model runs again. A question asked
    # together with other calls goes through the tool node, which loops on
    # (not every call is return_direct), and is sent back in wrap_tool_call.

    def _defer_sole_question(self, state: dict, runtime: object = None) -> dict | None:
        messages = state.get("messages") or []
        last = messages[-1] if messages else None
        if not isinstance(last, AIMessage) or len(last.tool_calls or []) != 1:
            return None
        call = last.tool_calls[0]
        if call.get("name") != "ask_clarification":
            return None
        context = self._context_of(runtime)
        turn = self._turn_of(state)
        if builder_answered(turn, context):
            return {"jump_to": "model", "messages": [answered_refusal(call.get("id", ""))]}
        args = call.get("args") or {}
        if builder_ask(turn, call.get("id", "")):
            args = shape_builder_question(dict(args), context)
        deferred = self._deferral(messages, call.get("id", ""), args)
        if deferred is None:
            problem, _ = self._shape(args, context, messages)
            if problem is None:
                return None
            deferred = problem_message(problem, call.get("id", ""), marker=self.SHAPE_MARKER)
        return {"jump_to": "model", "messages": [deferred]}

    @hook_config(can_jump_to=["model"])
    def after_model(self, state: ClarificationMiddlewareState, runtime) -> dict | None:
        return self._defer_sole_question(state, runtime)

    @hook_config(can_jump_to=["model"])
    async def aafter_model(self, state: ClarificationMiddlewareState, runtime) -> dict | None:
        return self._defer_sole_question(state, runtime)

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """Intercept ask_clarification tool calls and interrupt execution (sync version).

        Args:
            request: Tool call request
            handler: Original tool execution handler

        Returns:
            Command that interrupts execution with the formatted clarification message
        """
        # Check if this is an ask_clarification tool call
        if request.tool_call.get("name") != "ask_clarification":
            # Not a clarification call, execute normally
            return handler(request)

        return self._handle_clarification(request)

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """Intercept ask_clarification tool calls and interrupt execution (async version).

        Args:
            request: Tool call request
            handler: Original tool execution handler (async)

        Returns:
            Command that interrupts execution with the formatted clarification message
        """
        # Check if this is an ask_clarification tool call
        if request.tool_call.get("name") != "ask_clarification":
            # Not a clarification call, execute normally
            return await handler(request)

        return self._handle_clarification(request)
