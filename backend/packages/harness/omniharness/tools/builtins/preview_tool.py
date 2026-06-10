from typing import Annotated

from langchain.tools import InjectedToolCallId, ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from langgraph.typing import ContextT

from omniharness.agents.thread_state import ThreadState
from omniharness.preview.preview_controller import get_preview_controller
from omniharness.runtime.user_context import get_effective_user_id


def _get_thread_id(runtime: ToolRuntime[ContextT, ThreadState]) -> str | None:
    thread_id = runtime.context.get("thread_id") if runtime.context else None
    if thread_id:
        return thread_id
    runtime_config = getattr(runtime, "config", None) or {}
    return runtime_config.get("configurable", {}).get("thread_id")


def _get_user_id(runtime: ToolRuntime[ContextT, ThreadState]) -> str:
    user_id = runtime.context.get("user_id") if runtime.context else None
    return user_id or get_effective_user_id()


@tool(
    "preview",
    description=(
        "Start or refresh the live preview for the web application in this thread. "
        "Use after writing an artifact_manifest.json with type=web_app and preview.command. "
        "The preview server is started automatically using that manifest. "
        "Call this after creating or updating a web app, or when the user asks to preview it. "
        "Do not use for static_site artifacts — those are served directly from outputs."
    ),
)
async def preview_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    thread_id = _get_thread_id(runtime)
    if not thread_id:
        return Command(update={"messages": [ToolMessage("Error: thread_id not available in runtime context.", tool_call_id=tool_call_id)]})

    user_id = _get_user_id(runtime)
    controller = get_preview_controller()
    if controller is None:
        return Command(update={"messages": [ToolMessage("Preview service is not available in this environment.", tool_call_id=tool_call_id)]})

    try:
        await controller.request_preview(thread_id=thread_id, user_id=user_id)
        status = await controller.get_status(thread_id=thread_id, user_id=user_id)
    except Exception as exc:
        return Command(update={"messages": [ToolMessage(f"Error starting preview: {exc}", tool_call_id=tool_call_id)]})

    if not status.has_web_app:
        msg = "No web_app artifact manifest found. Write an artifact_manifest.json with type=web_app and preview.command before calling this tool."
    elif status.session_status in ("starting", "running"):
        msg = "Preview server is starting. It will be visible in the preview panel shortly."
    elif status.session_status == "failed":
        msg = f"Preview server failed to start: {status.session_error or 'unknown error'}. Check the dev server command and project structure."
    else:
        msg = f"Preview status: {status.session_status}."

    return Command(update={"messages": [ToolMessage(msg, tool_call_id=tool_call_id)]})
