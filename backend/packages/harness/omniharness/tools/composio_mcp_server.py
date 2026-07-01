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

# Expose only Composio's curated "important" tools per toolkit (default on).
# Toolkits like GitHub have 500+ tools; loading them all blows past LLM tool
# caps (OpenAI allows max 128 tools per request). Set COMPOSIO_IMPORTANT_ONLY
# to "false"/"0"/"no" to load the full catalogue for a toolkit instead.
IMPORTANT_ONLY = os.environ.get("COMPOSIO_IMPORTANT_ONLY", "true").strip().lower() not in ("false", "0", "no")

if not API_KEY:
    sys.exit("COMPOSIO_API_KEY is required")
if not TOOLKIT:
    sys.exit("COMPOSIO_TOOLKIT is required")
if not CONNECTED_ACCOUNT_ID:
    sys.exit("COMPOSIO_CONNECTED_ACCOUNT_ID is required")

_HEADERS = {"x-api-key": API_KEY, "Content-Type": "application/json"}


def _fetch_tools_sync() -> list[dict[str, Any]]:
    params: dict[str, str] = {"toolkit_slug": TOOLKIT.lower(), "limit": "100"}
    if IMPORTANT_ONLY:
        params["important"] = "true"
    if CONNECTED_ACCOUNT_ID:
        params["connected_account_id"] = CONNECTED_ACCOUNT_ID
    with httpx.Client(headers=_HEADERS, base_url=_BASE, timeout=30.0) as client:
        r = client.get("/v3/tools", params=params)
        r.raise_for_status()
        return r.json().get("items", [])


def _prune_empty(value: Any) -> Any:
    """Recursively strip empty values that Composio's execute API rejects.

    Composio rejects empty object params — e.g. ``attachment={}`` or
    ``attachment={"s3key": ""}`` fail with "Omit attachment or set it to null".
    LLM/MCP argument coercion frequently injects such empty optionals, so we
    drop empty strings, empty dicts, empty lists, and ``None`` before sending.
    Falsy-but-meaningful values (``False``, ``0``, ``0.0``) are preserved.
    Returns ``None`` to signal "drop this key".
    """
    if isinstance(value, dict):
        cleaned = {k: pv for k, v in value.items() if (pv := _prune_empty(v)) is not None}
        return cleaned or None
    if isinstance(value, list):
        cleaned = [pv for item in value if (pv := _prune_empty(item)) is not None]
        return cleaned or None
    if value == "":
        return None
    return value


def _sanitize_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Drop empty/auto-injected optional params before calling Composio."""
    cleaned = _prune_empty(arguments)
    return cleaned if isinstance(cleaned, dict) else {}


async def _execute_tool_async(slug: str, arguments: dict[str, Any]) -> Any:
    body: dict[str, Any] = {
        "connected_account_id": CONNECTED_ACCOUNT_ID,
        "arguments": _sanitize_arguments(arguments),
    }
    if USER_ID:
        body["user_id"] = USER_ID
    async with httpx.AsyncClient(headers=_HEADERS, base_url=_BASE, timeout=60.0) as client:
        r = await client.post(f"/v3/tools/execute/{slug}", json=body)
        r.raise_for_status()
        return r.json()


def _strip_required_deep(schema: dict[str, Any]) -> None:
    """Remove ``required`` from a schema and all of its sub-schemas, in place."""
    if not isinstance(schema, dict):
        return
    schema.pop("required", None)
    for sub in (schema.get("properties") or {}).values():
        _strip_required_deep(sub)
    items = schema.get("items")
    if isinstance(items, dict):
        _strip_required_deep(items)


def _relax_nested_required(schema: dict[str, Any]) -> None:
    """Drop ``required`` from NESTED object sub-schemas (in place).

    Composio marks optional objects (e.g. ``attachment``) as having required
    sub-fields (``name``, ``s3key``). When the model passes an empty/partial
    optional object like ``attachment={}``, the MCP layer's jsonschema
    validation rejects it BEFORE our execution-time sanitizer can strip it
    (mcp/server/lowlevel/server.py validates against inputSchema first).

    We keep the TOP-LEVEL ``required`` (genuinely required params such as
    ``recipient_email``/``body``) but relax everything below it, so empty
    optionals pass validation and reach :func:`_sanitize_arguments`, which
    removes them before the call hits Composio.
    """
    for sub in (schema.get("properties") or {}).values():
        if isinstance(sub, dict):
            _strip_required_deep(sub)
    items = schema.get("items")
    if isinstance(items, dict):
        _strip_required_deep(items)


def _build_mcp_tool(tool_def: dict[str, Any]) -> types.Tool | None:
    """Build an MCP Tool from a Composio v3 tool definition.

    The v3 API returns input_parameters as a JSON Schema object directly. We
    relax nested ``required`` constraints so optional objects the model leaves
    empty (e.g. ``attachment={}``) aren't rejected by client-side validation.
    """
    slug = tool_def.get("slug") or tool_def.get("name", "")
    if not slug:
        return None
    description = tool_def.get("description") or tool_def.get("display_name") or slug
    # input_parameters is already a JSON Schema {"type": "object", "properties": {...}}
    schema: dict[str, Any] = tool_def.get("input_parameters") or {"type": "object", "properties": {}}
    if not isinstance(schema, dict):
        schema = {"type": "object", "properties": {}}
    _relax_nested_required(schema)
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
