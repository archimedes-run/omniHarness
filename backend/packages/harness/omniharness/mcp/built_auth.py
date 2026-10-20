"""The endpoint token of a built MCP server, added at load time (Feature 006, #59).

A built server is reached only through its egress sidecar, whose endpoint
needs a per-server bearer token. The token lives in the gateway's vault and
is never written to extensions_config.json: the entry says
``"auth": "built-server-token"`` and carries its ``server_id``, and this module
asks the provider the gateway registered at startup for the value, adding it
to the in-memory connection settings only.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

TokenProvider = Callable[[str], Awaitable[str | None]]
_provider: TokenProvider | None = None


def set_built_token_provider(provider: TokenProvider | None) -> None:
    global _provider
    _provider = provider


async def inject_built_tokens(extensions_config, servers_config: dict) -> None:
    for name, params in servers_config.items():
        entry = extensions_config.mcp_servers.get(name)
        extra = (getattr(entry, "model_extra", None) or {}) if entry is not None else {}
        if extra.get("auth") != "built-server-token" or not extra.get("server_id"):
            continue
        token = await _provider(extra["server_id"]) if _provider is not None else None
        if not token:
            logger.warning("no endpoint token for built server %s; it will be refused by its sidecar", name)
            continue
        headers = dict(params.get("headers") or {})
        headers["Authorization"] = f"Bearer {token}"
        params["headers"] = headers
