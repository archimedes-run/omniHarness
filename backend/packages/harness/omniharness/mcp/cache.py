"""Cache for MCP tools to avoid repeated loading."""

import asyncio
import concurrent.futures
import logging
import os
import threading

from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)

_mcp_tools_cache: list[BaseTool] | None = None
_cache_initialized = False
# A THREAD lock, and the load runs on its own loop: callers on any thread or
# loop wait here, and none waits for a coroutine parked on a loop it is
# blocking (two first requests after a restart deadlocked the gateway).
_initialization_lock = threading.Lock()
_config_mtime: float | None = None  # Track config file modification time

#: Told the loaded tool list each time the cache is (re)initialised. The
#: application registers the policy coverage check here (app.policy.coverage):
#: MCP tools load lazily, after startup, so "every registered tool has a policy
#: rule" can only be checked for them once they exist. A hook rather than an
#: import, for the same reason as agents/middlewares/policy_hook.py: the
#: harness must not import `app`.
_loaded_listeners: list = []


def add_tools_loaded_listener(listener) -> None:
    """Call `listener(tools)` after every MCP cache (re)initialisation."""
    if listener not in _loaded_listeners:
        _loaded_listeners.append(listener)


def loaded_mcp_tools() -> list[BaseTool] | None:
    """The cached MCP tools, or None when they have not been loaded yet.

    Never triggers a load (unlike get_cached_mcp_tools): a startup check must
    not spawn every configured MCP server just to read their names.
    """
    return list(_mcp_tools_cache or []) if _cache_initialized else None


def _get_config_mtime() -> float | None:
    """Get the modification time of the extensions config file.

    Returns:
        The modification time as a float, or None if the file doesn't exist.
    """
    from omniharness.config.extensions_config import ExtensionsConfig

    config_path = ExtensionsConfig.resolve_config_path()
    if config_path and config_path.exists():
        return os.path.getmtime(config_path)
    return None


def _is_cache_stale() -> bool:
    """Check if the cache is stale due to config file changes.

    Returns:
        True if the cache should be invalidated, False otherwise.
    """
    global _config_mtime

    if not _cache_initialized:
        return False  # Not initialized yet, not stale

    current_mtime = _get_config_mtime()

    # If we couldn't get mtime before or now, assume not stale
    if _config_mtime is None or current_mtime is None:
        return False

    # If the config file has been modified since we cached, it's stale
    if current_mtime > _config_mtime:
        logger.info(f"MCP config file has been modified (mtime: {_config_mtime} -> {current_mtime}), cache is stale")
        return True

    return False


def _run_on_own_loop(make_coro):
    """Run `make_coro()` to completion on a loop of its own."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(make_coro())
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(make_coro())).result()


def _load_once() -> list[BaseTool]:
    global _mcp_tools_cache, _cache_initialized, _config_mtime

    with _initialization_lock:
        if _cache_initialized:
            logger.info("MCP tools already initialized")
            return _mcp_tools_cache or []

        from omniharness.mcp.tools import get_mcp_tools

        logger.info("Initializing MCP tools...")
        _mcp_tools_cache = _run_on_own_loop(get_mcp_tools)
        _cache_initialized = True
        _config_mtime = _get_config_mtime()  # Record config file mtime
        logger.info(f"MCP tools initialized: {len(_mcp_tools_cache)} tool(s) loaded (config mtime: {_config_mtime})")
        for listener in list(_loaded_listeners):
            try:
                listener(list(_mcp_tools_cache))
            except Exception:  # noqa: BLE001 — a listener must not break tool loading
                logger.exception("an MCP tools-loaded listener failed")

        return _mcp_tools_cache


async def initialize_mcp_tools() -> list[BaseTool]:
    """Initialize and cache MCP tools (once; concurrent callers share the load).

    Returns:
        List of LangChain tools from all enabled MCP servers.
    """
    if _cache_initialized:
        return _mcp_tools_cache or []
    return await asyncio.to_thread(_load_once)


def get_cached_mcp_tools() -> list[BaseTool]:
    """Get cached MCP tools with lazy initialization.

    If tools are not initialized, automatically initializes them.
    This ensures MCP tools work in both FastAPI and LangGraph Studio contexts.

    Also checks if the config file has been modified since last initialization,
    and re-initializes if needed. This ensures that changes made through the
    Gateway API (which runs in a separate process) are reflected in the
    LangGraph Server.

    Returns:
        List of cached MCP tools.
    """
    global _cache_initialized

    # Check if cache is stale due to config file changes
    if _is_cache_stale():
        logger.info("MCP cache is stale, resetting for re-initialization...")
        reset_mcp_tools_cache()

    if not _cache_initialized:
        logger.info("MCP tools not initialized, performing lazy initialization...")
        try:
            return _load_once()
        except Exception:
            logger.exception("Failed to lazy-initialize MCP tools")
            return []

    return _mcp_tools_cache or []


def reset_mcp_tools_cache() -> None:
    """Reset the MCP tools cache.

    This is useful for testing or when you want to reload MCP tools.
    """
    global _mcp_tools_cache, _cache_initialized, _config_mtime
    _mcp_tools_cache = None
    _cache_initialized = False
    _config_mtime = None
    logger.info("MCP tools cache reset")
