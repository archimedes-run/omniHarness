"""Live, per-user connector (OAuth toolkit) tool resolution.

Connector tools are resolved PER TURN from the requesting user's active
connections — never baked into the shared extensions_config.json. For each
selected toolkit we look up that user's active connected account and spawn an
in-memory stdio MCP server (``composio_mcp_server.py``) scoped to it. This
gives per-user isolation, makes a toolkit connected mid-conversation usable on
the next turn with no file write or restart, and keeps only the selected
toolkits in the tool array (so the provider tool cap isn't blown).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
import sys
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)

# The OAuth connector catalog (branding-neutral; no vendor name in tool ids).
# icon is a slug the frontend IntegrationIcon registry understands.
CONNECTOR_TOOLKITS: list[dict[str, str]] = [
    {"slug": "GMAIL", "name": "Gmail", "category": "Productivity", "icon": "gmail"},
    {"slug": "GOOGLECALENDAR", "name": "Google Calendar", "category": "Productivity", "icon": "googlecalendar"},
    {"slug": "GOOGLEDRIVE", "name": "Google Drive", "category": "Productivity", "icon": "googledrive"},
    {"slug": "SLACK", "name": "Slack", "category": "Communication", "icon": "slack"},
    {"slug": "NOTION", "name": "Notion", "category": "Knowledge", "icon": "notion"},
    {"slug": "GITHUB", "name": "GitHub", "category": "Dev Tools", "icon": "github"},
    {"slug": "LINEAR", "name": "Linear", "category": "Project Mgmt", "icon": "linear"},
    {"slug": "OUTLOOK", "name": "Outlook", "category": "Productivity", "icon": "outlook"},
]

CONNECTOR_SLUGS: set[str] = {tk["slug"] for tk in CONNECTOR_TOOLKITS}


# Toolkit slug (server name) -> prefix the tool names carry after loading.
def _server_name(toolkit: str) -> str:
    return f"connector-{toolkit.lower()}"


def _composio_server_script() -> str:
    """Absolute path to the stdio proxy script (co-located in this package)."""
    return str(Path(__file__).resolve().parent / "composio_mcp_server.py")


def _api_key() -> str:
    return os.environ.get("COMPOSIO_API_KEY", "")


async def _active_accounts_for_user(user_id: str, toolkits: set[str]) -> dict[str, str]:
    """Return ``{TOOLKIT: connected_account_id}`` for the user's ACTIVE connections.

    Scoped to *user_id* (per-user isolation) and filtered to the requested
    *toolkits*. Best-effort: returns an empty mapping if the persistence layer
    is unavailable.
    """
    try:
        from omniharness.persistence.composio_connections import ComposioConnectionRepository
        from omniharness.persistence.engine import get_session_factory
    except Exception:
        return {}

    session_factory = get_session_factory()
    if session_factory is None:
        return {}

    repo = ComposioConnectionRepository(session_factory)
    rows = await repo.list_by_user(user_id=user_id)
    accounts: dict[str, str] = {}
    for row in rows:
        tk = str(row.get("toolkit", "")).upper()
        if tk in toolkits and row.get("status") == "active" and row.get("composio_connection_id"):
            accounts[tk] = row["composio_connection_id"]
    return accounts


def _build_stdio_spec(toolkit: str, connected_account_id: str, user_id: str, api_key: str) -> dict[str, Any]:
    """In-memory MultiServerMCPClient stdio spec for one connector toolkit."""
    return {
        "transport": "stdio",
        "command": sys.executable,
        "args": [_composio_server_script()],
        "env": {
            **os.environ,  # inherit PATH etc. for the subprocess
            "COMPOSIO_API_KEY": api_key,
            "COMPOSIO_TOOLKIT": toolkit.upper(),
            "COMPOSIO_CONNECTED_ACCOUNT_ID": connected_account_id,
            "COMPOSIO_USER_ID": user_id,
        },
    }


async def _load_connector_tools_async(user_id: str, toolkits: set[str]) -> list[BaseTool]:
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError:
        logger.warning("langchain-mcp-adapters not installed; connector tools unavailable")
        return []

    api_key = _api_key()
    if not api_key:
        logger.warning("COMPOSIO_API_KEY not set; skipping connector tools")
        return []

    wanted = {t.upper() for t in toolkits} & CONNECTOR_SLUGS
    if not wanted:
        return []

    accounts = await _active_accounts_for_user(user_id, wanted)
    if not accounts:
        return []

    from omniharness.mcp.tools import _make_sync_tool_wrapper

    tools: list[BaseTool] = []
    for toolkit, account_id in accounts.items():
        spec = _build_stdio_spec(toolkit, account_id, user_id, api_key)
        try:
            client = MultiServerMCPClient({_server_name(toolkit): spec}, tool_name_prefix=True)
            server_tools = await client.get_tools()
            for tool in server_tools:
                if getattr(tool, "func", None) is None and getattr(tool, "coroutine", None) is not None:
                    tool.func = _make_sync_tool_wrapper(tool.coroutine, tool.name)
            tools.extend(server_tools)
            logger.info("Loaded %d connector tool(s) for user=%s toolkit=%s", len(server_tools), user_id, toolkit)
        except Exception as exc:
            logger.warning("Skipping connector toolkit %s for user %s: %s", toolkit, user_id, exc)
    return tools


def load_connector_tools(user_id: str | None, toolkits: list[str] | set[str] | None) -> list[BaseTool]:
    """Synchronous entry point used by the (sync) tool-assembly path.

    Runs the async loader, bridging a running event loop via a worker thread
    (mirrors ``get_cached_mcp_tools``).
    """
    if not user_id or not toolkits:
        return []
    wanted = {t.upper() for t in toolkits}

    async def _runner() -> list[BaseTool]:
        return await _load_connector_tools_async(user_id, wanted)

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            with concurrent.futures.ThreadPoolExecutor() as executor:
                return executor.submit(asyncio.run, _runner()).result()
        return loop.run_until_complete(_runner())
    except RuntimeError:
        try:
            return asyncio.run(_runner())
        except Exception:
            logger.exception("Failed to load connector tools")
            return []
    except Exception:
        logger.exception("Failed to load connector tools")
        return []
