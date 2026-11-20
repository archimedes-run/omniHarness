"""mcp_build — agent tool for submitting and testing an MCP server."""

from __future__ import annotations

import json
from typing import Annotated

from langchain.tools import InjectedToolCallId, ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from langgraph.typing import ContextT

from omniharness.agents.thread_state import ThreadState
from omniharness.runtime.mcp.controller import get_mcp_build_controller
from omniharness.runtime.mcp.studio import STUDIO_ONLY_MESSAGE, studio_build_server_id


def _reply(text: str, tool_call_id: str) -> Command:
    return Command(update={"messages": [ToolMessage(text, tool_call_id=tool_call_id)]})


@tool(
    "mcp_build",
    description=(
        "Submit source code for the MCP server this MCP Studio build run was started for, and run the automated checks. "
        "The pipeline runs static and LLM security scans and detects required secrets. "
        "It does NOT run the server: the test phase runs only in a container and is "
        "unavailable until the MCP Build redesign, so the result is phase 'failed' with that reason. "
        "Returns phase, tools_discovered, detected_secret_names, errors, and test_results. "
        "Call this after writing the complete server.py source code. "
        "Pass the server_id from the task and the full source_code string. "
        "IMPORTANT — available packages in the sandbox: the `mcp` SDK is installed; "
        "always use `from mcp.server.fastmcp import FastMCP` (NOT `from fastmcp import FastMCP` — "
        "the standalone fastmcp package is NOT available). "
        "`httpx` is available for HTTP. Do NOT use any other third-party packages "
        "unless they are part of the Python standard library."
    ),
)
async def mcp_build_tool(
    server_id: str,
    source_code: str,
    runtime: ToolRuntime[ContextT, ThreadState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Submit source code for an MCP server and run the automated test pipeline."""
    controller = get_mcp_build_controller()
    if controller is None:
        return _reply("MCP build service is not available in this environment.", tool_call_id)

    # Only a build run MCP Studio started, for its own server, and only when
    # the server's record confirms that run's thread and owner. Everything is
    # read from the run's server-set context; the server_id argument is only
    # compared against it.
    context = runtime.context if isinstance(runtime.context, dict) else {}
    target = studio_build_server_id(context)
    if target is None:
        return _reply(f"Not run: {STUDIO_ONLY_MESSAGE}", tool_call_id)
    if server_id != target:
        return _reply(f"Not run: this build run may only submit code for server {target}.", tool_call_id)
    user_id = context.get("user_id")
    thread_id = context.get("thread_id")
    if not isinstance(user_id, str) or not user_id or not isinstance(thread_id, str) or not thread_id:
        return _reply(f"Not run: {STUDIO_ONLY_MESSAGE}", tool_call_id)
    try:
        allowed = await controller.studio_build_allowed(server_id=target, thread_id=thread_id, user_id=user_id)
    except Exception:
        allowed = False
    if not allowed:
        return _reply(f"Not run: {STUDIO_ONLY_MESSAGE}", tool_call_id)

    try:
        status = await controller.submit_source_and_test(
            server_id=server_id,
            user_id=user_id,
            source_code=source_code,
        )
    except PermissionError as exc:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        f"Access denied: {exc}",
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        )
    except Exception as exc:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        f"MCP build error: {exc}",
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        )

    result = {
        "phase": status.phase,
        "tools_discovered": status.tools_discovered,
        "detected_secret_names": status.required_key_names,
        "errors": [status.error] if status.error else [],
        "test_results": status.test_results,
        "last_verified_at": status.last_verified_at,
    }

    return Command(
        update={
            "messages": [
                ToolMessage(
                    json.dumps(result, indent=2),
                    tool_call_id=tool_call_id,
                )
            ]
        }
    )
