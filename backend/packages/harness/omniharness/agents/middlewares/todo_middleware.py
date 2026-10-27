"""Middleware that extends TodoListMiddleware with context-loss detection and premature-exit prevention.

When the message history is truncated (e.g., by SummarizationMiddleware), the
original `write_todos` tool call and its ToolMessage can be scrolled out of the
active context window. This middleware detects that situation and injects a
reminder message so the model still knows about the outstanding todo list.

Additionally, this middleware prevents the agent from exiting the loop while
there are still incomplete todo items. When the model produces a final response
(no tool calls) but todos are not yet complete, the middleware injects a reminder
and jumps back to the model node to force continued engagement.
"""

from __future__ import annotations

from typing import Any, override

from langchain.agents.middleware import TodoListMiddleware
from langchain.agents.middleware.todo import PlanningState, Todo
from langchain.agents.middleware.types import hook_config
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime


def _todos_in_messages(messages: list[Any]) -> bool:
    """Return True if any AIMessage in *messages* contains a write_todos tool call."""
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                if tc.get("name") == "write_todos":
                    return True
    return False


def _reminder_in_messages(messages: list[Any]) -> bool:
    """Return True if a todo_reminder HumanMessage is already present in *messages*."""
    for msg in messages:
        if isinstance(msg, HumanMessage) and getattr(msg, "name", None) == "todo_reminder":
            return True
    return False


def _completion_reminder_count(messages: list[Any]) -> int:
    """The number of todo_completion_reminder messages in the CURRENT turn.

    Counted per turn (spec 009 FR-052), not over the whole thread: a thread
    whose earlier turns used up a thread-wide cap never reminded again."""
    from omniharness.agents.working_loop import turn_messages

    return sum(1 for msg in turn_messages(messages) if isinstance(msg, HumanMessage) and getattr(msg, "name", None) == "todo_completion_reminder")


def _format_todos(todos: list[Todo]) -> str:
    """Format a list of Todo items into a human-readable string."""
    lines: list[str] = []
    for todo in todos:
        status = todo.get("status", "pending")
        content = todo.get("content", "")
        lines.append(f"- [{status}] {content}")
    return "\n".join(lines)


class TodoMiddleware(TodoListMiddleware):
    """Extends TodoListMiddleware with `write_todos` context-loss detection.

    When the original `write_todos` tool call has been truncated from the message
    history (e.g., after summarization), the model loses awareness of the current
    todo list. This middleware detects that gap in `before_model` / `abefore_model`
    and injects a reminder message so the model can continue tracking progress.
    """

    @override
    def before_model(
        self,
        state: PlanningState,
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        """Inject a todo-list reminder when write_todos has left the context window."""
        todos: list[Todo] = state.get("todos") or []  # type: ignore[assignment]
        if not todos:
            return None

        messages = state.get("messages") or []
        if _todos_in_messages(messages):
            # write_todos is still visible in context — nothing to do.
            return None

        if _reminder_in_messages(messages):
            # A reminder was already injected and hasn't been truncated yet.
            return None

        # The todo list exists in state but the original write_todos call is gone.
        # Inject a reminder as a HumanMessage so the model stays aware.
        formatted = _format_todos(todos)
        reminder = HumanMessage(
            name="todo_reminder",
            content=(
                "<system_reminder>\n"
                "Your todo list from earlier is no longer visible in the current context window, "
                "but it is still active. Here is the current state:\n\n"
                f"{formatted}\n\n"
                "Continue tracking and updating this todo list as you work. "
                "Call `write_todos` whenever the status of any item changes.\n"
                "</system_reminder>"
            ),
        )
        return {"messages": [reminder]}

    @override
    async def abefore_model(
        self,
        state: PlanningState,
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        """Async version of before_model."""
        return self.before_model(state, runtime)

    # Completion reminders per turn before the agent may finish anyway (FR-052:
    # once). The reminder asks it to finish the items OR to report them as
    # not verified; a reply that already has a "Not verified" list is an
    # honest stop and is let through.
    _MAX_COMPLETION_REMINDERS = 1

    @hook_config(can_jump_to=["model"])
    @override
    def after_model(
        self,
        state: PlanningState,
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        """Send the lead back once when it would finish with unticked items.

        Spec 009 FR-052 (generalising PreviewVerificationMiddleware's gate):
        when the model gives a final reply (no tool calls) while checklist
        items are not completed, and the reply has no "Not verified" list
        naming what is missing, one reminder is injected and the model runs
        again. It may then finish the items, or stop honestly with a "Not
        verified" list. A forced stop by the loop detector is never sent back.
        """
        from omniharness.agents.working_loop import DONE_WHEN_RE, NOT_VERIFIED_RE, card_pending, text_of

        # 1. Preserve base class logic (parallel write_todos detection).
        base_result = super().after_model(state, runtime)
        if base_result is not None:
            return base_result

        # 2. Only intervene when the agent wants to exit (no tool calls).
        messages = state.get("messages") or []
        last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
        if not last_ai or last_ai.tool_calls:
            return None
        reply = text_of(last_ai)
        if "[FORCED STOP]" in reply:
            return None

        # 3. Allow exit when all todos are completed or there are no todos.
        todos: list[Todo] = state.get("todos") or []  # type: ignore[assignment]
        incomplete = [t for t in todos if t.get("status") != "completed" and not DONE_WHEN_RE.match(str(t.get("content") or ""))]
        if not todos or not incomplete:
            return None

        # 4. An honest stop: the reply lists what is not verified; or the turn
        #    stops at a confirmation card and resumes once it is answered.
        if NOT_VERIFIED_RE.search(reply) or card_pending(messages):
            return None

        # 5. Once per turn.
        if _completion_reminder_count(messages) >= self._MAX_COMPLETION_REMINDERS:
            return None

        incomplete_text = "\n".join(f"- [{t.get('status', 'pending')}] {t.get('content', '')}" for t in incomplete)
        reminder = HumanMessage(
            name="todo_completion_reminder",
            content=(
                "<system_reminder>\n"
                "Your checklist still has items that are not completed:\n\n"
                f"{incomplete_text}\n\n"
                "Finish them now if you can (tick each with write_todos as it is done). If an item cannot be "
                'done, do not claim it: end your reply with a "Not verified" list naming each such item and '
                "what is missing or what failed.\n"
                "</system_reminder>"
            ),
        )
        return {"jump_to": "model", "messages": [reminder]}

    @override
    @hook_config(can_jump_to=["model"])
    async def aafter_model(
        self,
        state: PlanningState,
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        """Async version of after_model."""
        return self.after_model(state, runtime)
