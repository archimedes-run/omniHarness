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

from omniharness.agents.questions import QUESTION_MARKER, QuestionRefused, open_question

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


def problem_message(problem: str, call_id: str) -> ToolMessage:
    """A question that cannot be asked as it is: the model is told why and
    runs again (it is not a pause)."""
    return ToolMessage(
        content=f"Not asked: {problem}. Ask again with that fixed, or pick a sensible default, state it, and continue.",
        tool_call_id=call_id,
        name="ask_clarification",
    )


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
            additional_kwargs={self.DEFERRED_MARKER: True},
        )

    # -- the question card ---------------------------------------------------

    def _shape_problem(self, args: dict) -> str | None:
        """Why this question cannot be a card (2 to 4 short, distinct options,
        a question of 1 to 500 characters), or None. Checked only when the
        gateway makes cards; the store checks the same limits again."""
        if not card_questions_enabled():
            return None
        question = str(args.get("question") or "").strip()
        options = _options_list(args.get("options"))
        if not 1 <= len(question) <= 500:
            return "the question must be 1 to 500 characters"
        if not 2 <= len(options) <= 4:
            return "give 2 to 4 short options the person can pick from (they can still type their own answer)"
        if any(not 1 <= len(o) <= 60 for o in options):
            return "each option must be 1 to 60 characters"
        if len({o.casefold() for o in options}) != len(options):
            return "the options must be different from each other"
        raw = args.get("recommended")
        if raw is not None and _recommended_index(raw, len(options)) is None:
            return f"recommended must be an option number from 1 to {len(options)}"
        return None

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
        deferred = self._mid_task_deferral(request)
        if deferred is not None:
            return deferred

        # Extract clarification arguments
        args = request.tool_call.get("args", {})
        question = args.get("question", "")

        # Get the tool call ID
        tool_call_id = request.tool_call.get("id", "")
        problem = self._shape_problem(args)
        if problem is not None:
            return problem_message(problem, tool_call_id)

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
            formatted_message += "\n\nAnswer on the card, or reply with an option number or your own words."

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

    def _defer_sole_question(self, state: dict) -> dict | None:
        messages = state.get("messages") or []
        last = messages[-1] if messages else None
        if not isinstance(last, AIMessage) or len(last.tool_calls or []) != 1:
            return None
        call = last.tool_calls[0]
        if call.get("name") != "ask_clarification":
            return None
        deferred = self._deferral(messages, call.get("id", ""), call.get("args") or {})
        if deferred is None:
            problem = self._shape_problem(call.get("args") or {})
            if problem is None:
                return None
            deferred = problem_message(problem, call.get("id", ""))
        return {"jump_to": "model", "messages": [deferred]}

    @hook_config(can_jump_to=["model"])
    def after_model(self, state: ClarificationMiddlewareState, runtime) -> dict | None:  # noqa: ARG002
        return self._defer_sole_question(state)

    @hook_config(can_jump_to=["model"])
    async def aafter_model(self, state: ClarificationMiddlewareState, runtime) -> dict | None:  # noqa: ARG002
        return self._defer_sole_question(state)

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
