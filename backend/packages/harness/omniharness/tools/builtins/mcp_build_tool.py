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
from omniharness.runtime.user_context import get_effective_user_id


def _get_user_id(runtime: ToolRuntime[ContextT, ThreadState]) -> str:
    user_id = runtime.context.get("user_id") if runtime.context else None
    return user_id or get_effective_user_id()


@tool(
    "mcp_build",
    description=(
        "Submit source code for an MCP server and run the automated test pipeline. "
        "The pipeline runs static security scans, verifies required secrets are stored, "
        "starts the server in an isolated subprocess, connects the MCP client, "
        "and discovers + test-calls each tool. "
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
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        "MCP build service is not available in this environment.",
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        )

    user_id = _get_user_id(runtime)

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
