#!/usr/bin/env python3
"""Composio MCP stdio proxy server.

Bridges a single Composio toolkit to the MCP stdio protocol using Composio's
v3 REST API (list: GET /api/v3/tools, execute: POST /api/v3/tools/execute/{slug}).

Required env vars:
  COMPOSIO_API_KEY            - Composio API key
  COMPOSIO_TOOLKIT            - Uppercase toolkit slug (e.g. GMAIL)
  COMPOSIO_CONNECTED_ACCOUNT_ID - Composio connected account ID (e.g. ca_xxx)
Optional:
  COMPOSIO_USER_ID            - User ID for multi-user accounts
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any

import anyio
import httpx
import mcp.server.stdio
import mcp.types as types
from mcp.server import Server

logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
logger = logging.getLogger(__name__)

_BASE = "https://backend.composio.dev/api"

API_KEY = os.environ.get("COMPOSIO_API_KEY", "")
TOOLKIT = os.environ.get("COMPOSIO_TOOLKIT", "").upper()
CONNECTED_ACCOUNT_ID = os.environ.get("COMPOSIO_CONNECTED_ACCOUNT_ID", "")
USER_ID = os.environ.get("COMPOSIO_USER_ID", "")

if not API_KEY:
    sys.exit("COMPOSIO_API_KEY is required")
if not TOOLKIT:
    sys.exit("COMPOSIO_TOOLKIT is required")
if not CONNECTED_ACCOUNT_ID:
    sys.exit("COMPOSIO_CONNECTED_ACCOUNT_ID is required")

_HEADERS = {"x-api-key": API_KEY, "Content-Type": "application/json"}


def _fetch_tools_sync() -> list[dict[str, Any]]:
    params: dict[str, str] = {"toolkit_slug": TOOLKIT.lower(), "limit": "100"}
    if CONNECTED_ACCOUNT_ID:
        params["connected_account_id"] = CONNECTED_ACCOUNT_ID
    with httpx.Client(headers=_HEADERS, base_url=_BASE, timeout=30.0) as client:
        r = client.get("/v3/tools", params=params)
        r.raise_for_status()
        return r.json().get("items", [])


async def _execute_tool_async(slug: str, arguments: dict[str, Any]) -> Any:
    body: dict[str, Any] = {
        "connected_account_id": CONNECTED_ACCOUNT_ID,
        "arguments": arguments,
    }
    if USER_ID:
        body["user_id"] = USER_ID
    async with httpx.AsyncClient(headers=_HEADERS, base_url=_BASE, timeout=60.0) as client:
        r = await client.post(f"/v3/tools/execute/{slug}", json=body)
        r.raise_for_status()
        return r.json()


def _build_mcp_tool(tool_def: dict[str, Any]) -> types.Tool | None:
    """Build an MCP Tool from a Composio v3 tool definition.

    The v3 API returns input_parameters as a JSON Schema object directly,
    so we use it as-is for inputSchema.
    """
    slug = tool_def.get("slug") or tool_def.get("name", "")
    if not slug:
        return None
    description = tool_def.get("description") or tool_def.get("display_name") or slug
    # input_parameters is already a JSON Schema {"type": "object", "properties": {...}}
    schema: dict[str, Any] = tool_def.get("input_parameters") or {"type": "object", "properties": {}}
    if not isinstance(schema, dict):
        schema = {"type": "object", "properties": {}}
    return types.Tool(
        name=slug,
        description=description,
        inputSchema=schema,
    )


async def main() -> None:
    try:
        loop = asyncio.get_running_loop()
        tools_raw = await loop.run_in_executor(None, _fetch_tools_sync)
    except Exception as exc:
        logger.error("composio_mcp_server: failed to fetch tools: %s", exc)
        tools_raw = []

    mcp_tools = [t for raw in tools_raw if (t := _build_mcp_tool(raw)) is not None]
    tools_by_name = {t.name: t for t in mcp_tools}

    server = Server(f"composio-{TOOLKIT.lower()}")

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        return mcp_tools

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, Any] | None) -> list[types.TextContent]:
        if name not in tools_by_name:
            return [types.TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]
        try:
            result = await _execute_tool_async(name, arguments or {})
            return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
        except httpx.HTTPStatusError as exc:
            error = {"error": str(exc), "status": exc.response.status_code, "body": exc.response.text[:500]}
            return [types.TextContent(type="text", text=json.dumps(error))]
        except Exception as exc:
            return [types.TextContent(type="text", text=json.dumps({"error": str(exc)}))]

    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        init_options = server.create_initialization_options()
        await server.run(read_stream, write_stream, init_options, raise_exceptions=True)


if __name__ == "__main__":
    anyio.run(main)
