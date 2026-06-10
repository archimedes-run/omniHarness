"""PreviewVerificationMiddleware: gate that ensures a web-app preview is live
before the agent gives its final response.

Runs in ``aafter_model``. When the model wants to exit (no tool calls) and the
thread has a ``web_app`` artifact:

- ``not_started``  → auto-trigger via ``PreviewController.request_preview``,
                     inject a reminder, and jump back to the model.
- ``failed``       → inject a reminder describing the error, jump back.
- ``running`` + client errors → inject a reminder with the JS errors, jump back.
- ``running`` + no errors     → allow the agent to exit normally.

Retries are capped at ``_MAX_VERIFICATION_REMINDERS`` (default: 3) to prevent
infinite loops when the agent cannot fix the problem.
"""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import hook_config
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime

from omniharness.preview.preview_controller import get_preview_controller


def _verification_reminder_count(messages: list[Any]) -> int:
    return sum(1 for m in messages if isinstance(m, HumanMessage) and getattr(m, "name", None) == "preview_verification_reminder")


class PreviewVerificationMiddleware(AgentMiddleware):
    """Verifies the live preview is healthy before allowing the agent to finish."""

    _MAX_VERIFICATION_REMINDERS: int = 3

    @hook_config(can_jump_to=["model"])
    async def aafter_model(
        self,
        state: dict[str, Any],
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        # Only gate when the agent wants to exit (no tool calls in last AI message).
        messages = state.get("messages") or []
        last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
        if not last_ai or last_ai.tool_calls:
            return None

        # Cap retries to prevent infinite loops.
        if _verification_reminder_count(messages) >= self._MAX_VERIFICATION_REMINDERS:
            return None

        controller = get_preview_controller()
        if controller is None:
            return None

        thread_id: str | None = runtime.context.get("thread_id") if runtime.context else None
        user_id: str | None = runtime.context.get("user_id") if runtime.context else None
        if not thread_id or not user_id:
            return None

        try:
            status = await controller.get_status(thread_id=thread_id, user_id=user_id)
        except Exception:
            return None

        # No web_app artifact for this thread — nothing to verify.
        if not status.has_web_app:
            return None

        # ── Case 1: preview never started ─────────────────────────────────────
        if status.session_status == "not_started":
            try:
                await controller.request_preview(thread_id=thread_id, user_id=user_id)
            except Exception:
                pass
            reminder = HumanMessage(
                name="preview_verification_reminder",
                content=(
                    "<system_reminder>\n"
                    "Your web application preview has been automatically started. "
                    "Please verify it launched successfully — check the logs and confirm the dev server "
                    "is accepting connections before giving your final response.\n"
                    "</system_reminder>"
                ),
            )
            return {"jump_to": "model", "messages": [reminder]}

        # ── Case 2: preview server failed to start ─────────────────────────────
        if status.session_status == "failed":
            reminder = HumanMessage(
                name="preview_verification_reminder",
                content=(
                    "<system_reminder>\n"
                    f"Your web application preview failed to start: "
                    f"{status.session_error or 'unknown error'}.\n\n"
                    "Diagnose the issue (check the dev server command, missing dependencies, port conflicts), "
                    "fix the code, and call the `preview` tool to restart it.\n"
                    "</system_reminder>"
                ),
            )
            return {"jump_to": "model", "messages": [reminder]}

        # ── Case 3: running but client-side JS errors detected ─────────────────
        if status.session_status == "running" and status.client_errors:
            errors_text = "\n".join(f"  - {e}" for e in status.client_errors[:5])
            remaining = len(status.client_errors) - 5
            suffix = f"\n  … and {remaining} more" if remaining > 0 else ""
            reminder = HumanMessage(
                name="preview_verification_reminder",
                content=(
                    "<system_reminder>\n"
                    "Your web application is running but the browser reported client-side errors:\n\n"
                    f"{errors_text}{suffix}\n\n"
                    "Fix these JavaScript errors in the source code, then call the `preview` tool "
                    "to restart the preview with the corrected code.\n"
                    "</system_reminder>"
                ),
            )
            return {"jump_to": "model", "messages": [reminder]}

        # ── Case 4: running cleanly — allow the agent to exit ──────────────────
        return None

    @hook_config(can_jump_to=["model"])
    def after_model(
        self,
        state: dict[str, Any],
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        # Sync path is never reached in normal astream usage; keep as no-op.
        return None
