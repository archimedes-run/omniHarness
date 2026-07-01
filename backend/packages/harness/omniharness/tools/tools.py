import logging

from langchain.tools import BaseTool

from omniharness.config import get_app_config
from omniharness.config.app_config import AppConfig
from omniharness.reflection import resolve_variable
from omniharness.sandbox.security import is_host_bash_allowed
from omniharness.tools.builtins import ask_clarification_tool, mcp_build_tool, present_file_tool, preview_tool, task_tool, view_image_tool
from omniharness.tools.builtins.tool_search import reset_deferred_registry

logger = logging.getLogger(__name__)

BUILTIN_TOOLS = [
    present_file_tool,
    ask_clarification_tool,
]

# Sources are namespaced ids to avoid collisions between a local MCP server and
# a connector toolkit that share a name (e.g. local "github" vs connector
# "GITHUB"): local servers are ``local:<server>``, connectors ``connector:<SLUG>``.
# These two local sources are always available and non-removable in the UI.
PINNED_LOCAL_SERVERS: frozenset[str] = frozenset({"filesystem", "postgres"})
PINNED_LOCAL_SOURCES: frozenset[str] = frozenset(f"local:{s}" for s in PINNED_LOCAL_SERVERS)


class ToolCapExceededError(Exception):
    """Raised when the assembled tool array exceeds the provider's cap.

    Carries the structured counts so the API layer can surface "N / cap"
    to the UI instead of letting the provider return an opaque 400.
    """

    def __init__(self, count: int, cap: int) -> None:
        self.count = count
        self.cap = cap
        super().__init__(f"Selected tools ({count}) exceed the model's limit of {cap}. Deselect some tools for this conversation.")


def _tool_source(tool_name: str, server_names: list[str]) -> str | None:
    """Return which MCP server a prefixed tool came from (tool_name_prefix=True).

    langchain-mcp-adapters names tools ``<server>_<tool>``. We match against the
    known server names (longest first) rather than naively splitting on ``_``,
    since server names can themselves contain underscores.
    """
    for server in sorted(server_names, key=len, reverse=True):
        if tool_name.startswith(f"{server}_"):
            return server
    return None


SUBAGENT_TOOLS = [
    task_tool,
    # task_status_tool is no longer exposed to LLM (backend handles polling internally)
]


def _is_host_bash_tool(tool: object) -> bool:
    """Return True if the tool config represents a host-bash execution surface."""
    group = getattr(tool, "group", None)
    use = getattr(tool, "use", None)
    if group == "bash":
        return True
    if use == "omniharness.sandbox.tools:bash_tool":
        return True
    return False


def get_available_tools(
    groups: list[str] | None = None,
    include_mcp: bool = True,
    model_name: str | None = None,
    subagent_enabled: bool = False,
    *,
    app_config: AppConfig | None = None,
    selected_sources: set[str] | None = None,
    user_id: str | None = None,
    max_tools: int | None = None,
) -> list[BaseTool]:
    """Get all available tools from config.

    Note: MCP tools should be initialized at application startup using
    `initialize_mcp_tools()` from omniharness.mcp module.

    Args:
        groups: Optional list of tool groups to filter by.
        include_mcp: Whether to include tools from MCP servers (default: True).
        model_name: Optional model name to determine if vision tools should be included.
        subagent_enabled: Whether to include subagent tools (task, task_status).

    Returns:
        List of available tools.
    """
    config = app_config or get_app_config()
    tool_configs = [tool for tool in config.tools if groups is None or tool.group in groups]

    # Do not expose host bash by default when LocalSandboxProvider is active.
    if not is_host_bash_allowed(config):
        tool_configs = [tool for tool in tool_configs if not _is_host_bash_tool(tool)]

    loaded_tools_raw = [(cfg, resolve_variable(cfg.use, BaseTool)) for cfg in tool_configs]

    # Warn when the config ``name`` field and the tool object's ``.name``
    # attribute diverge — this mismatch is the root cause of issue #1803 where
    # the LLM receives one name in its tool schema but the runtime router
    # recognises a different name, producing "not a valid tool" errors.
    for cfg, loaded in loaded_tools_raw:
        if cfg.name != loaded.name:
            logger.warning(
                "Tool name mismatch: config name %r does not match tool .name %r (use: %s). The tool's own .name will be used for binding.",
                cfg.name,
                loaded.name,
                cfg.use,
            )

    loaded_tools = [t for _, t in loaded_tools_raw]

    # Conditionally add tools based on config
    builtin_tools = BUILTIN_TOOLS.copy()
    skill_evolution_config = getattr(config, "skill_evolution", None)
    if getattr(skill_evolution_config, "enabled", False):
        from omniharness.tools.skill_manage_tool import skill_manage_tool

        builtin_tools.append(skill_manage_tool)

    # Add preview tool only when a PreviewController is registered (gateway mode).
    from omniharness.preview.preview_controller import get_preview_controller

    if get_preview_controller() is not None:
        builtin_tools.append(preview_tool)

    # Add mcp_build tool only when an MCPBuildController is registered (gateway mode).
    from omniharness.runtime.mcp.controller import get_mcp_build_controller

    if get_mcp_build_controller() is not None:
        builtin_tools.append(mcp_build_tool)

    # Add subagent tools only if enabled via runtime parameter
    if subagent_enabled:
        builtin_tools.extend(SUBAGENT_TOOLS)
        logger.info("Including subagent tools (task)")

    # If no model_name specified, use the first model (default)
    if model_name is None and config.models:
        model_name = config.models[0].name

    # Add view_image_tool only if the model supports vision
    model_config = config.get_model_config(model_name) if model_name else None
    if model_config is not None and model_config.supports_vision:
        builtin_tools.append(view_image_tool)
        logger.info(f"Including view_image_tool for model '{model_name}' (supports_vision=True)")

    # Get cached MCP tools if enabled
    # NOTE: We use ExtensionsConfig.from_file() instead of config.extensions
    # to always read the latest configuration from disk. This ensures that changes
    # made through the Gateway API (which runs in a separate process) are immediately
    # reflected when loading MCP tools.
    mcp_tools = []
    # Reset deferred registry upfront to prevent stale state from previous calls
    reset_deferred_registry()
    if include_mcp:
        try:
            from omniharness.config.extensions_config import ExtensionsConfig
            from omniharness.mcp.cache import get_cached_mcp_tools

            extensions_config = ExtensionsConfig.from_file()
            enabled_servers = extensions_config.get_enabled_mcp_servers()
            if enabled_servers:
                mcp_tools = get_cached_mcp_tools()

                # Per-conversation selection: keep only tools from the pinned
                # local sources plus the sources this thread selected. Connector
                # servers are NEVER sourced from the file cache — they load live
                # per-user below — so they're excluded here regardless.
                if selected_sources is not None:
                    server_names = list(enabled_servers.keys())
                    # Allowed local server NAMES = pinned + any selected local:<server>.
                    allowed_servers = set(PINNED_LOCAL_SERVERS)
                    for sid in selected_sources:
                        if sid.startswith("local:"):
                            allowed_servers.add(sid.split(":", 1)[1])
                    filtered: list[BaseTool] = []
                    for t in mcp_tools:
                        src = _tool_source(t.name, server_names)
                        # Drop connector-* file entries (superseded by live loader)
                        # and any local server not pinned/selected.
                        if src is None:
                            filtered.append(t)  # unprefixed / unknown — keep
                        elif src.lower().startswith(("connector-", "composio-")):
                            continue
                        elif src in allowed_servers:
                            filtered.append(t)
                    mcp_tools = filtered

                if mcp_tools:
                    logger.info(f"Using {len(mcp_tools)} cached MCP tool(s)")

                    # When tool_search is enabled, register MCP tools in the
                    # deferred registry and add tool_search to builtin tools.
                    if config.tool_search.enabled:
                        from omniharness.tools.builtins.tool_search import DeferredToolRegistry, set_deferred_registry
                        from omniharness.tools.builtins.tool_search import tool_search as tool_search_tool

                        registry = DeferredToolRegistry()
                        for t in mcp_tools:
                            registry.register(t)
                        set_deferred_registry(registry)
                        builtin_tools.append(tool_search_tool)
                        logger.info(f"Tool search active: {len(mcp_tools)} tools deferred")
        except ImportError:
            logger.warning("MCP module not available. Install 'langchain-mcp-adapters' package to enable MCP tools.")
        except Exception as e:
            logger.error(f"Failed to get cached MCP tools: {e}")

    # Live per-user connector tools (resolved from the user's active
    # connections, never from the shared config). Only when this thread
    # selected connector toolkits and we know the user.
    connector_tools: list[BaseTool] = []
    if selected_sources and user_id:
        try:
            from omniharness.tools.connector_tools import CONNECTOR_SLUGS, load_connector_tools

            wanted_connectors = [sid.split(":", 1)[1].upper() for sid in selected_sources if sid.startswith("connector:") and sid.split(":", 1)[1].upper() in CONNECTOR_SLUGS]
            if wanted_connectors:
                connector_tools = load_connector_tools(user_id, wanted_connectors)
                logger.info(f"Loaded {len(connector_tools)} live connector tool(s) for {len(wanted_connectors)} toolkit(s)")
        except Exception as e:
            logger.error(f"Failed to load connector tools: {e}")

    # Add invoke_acp_agent tool if any ACP agents are configured
    acp_tools: list[BaseTool] = []
    try:
        from omniharness.tools.builtins.invoke_acp_agent_tool import build_invoke_acp_agent_tool

        if app_config is None:
            from omniharness.config.acp_config import get_acp_agents

            acp_agents = get_acp_agents()
        else:
            acp_agents = getattr(config, "acp_agents", {}) or {}
        if acp_agents:
            acp_tools.append(build_invoke_acp_agent_tool(acp_agents))
            logger.info(f"Including invoke_acp_agent tool ({len(acp_agents)} agent(s): {list(acp_agents.keys())})")
    except Exception as e:
        logger.warning(f"Failed to load ACP tool: {e}")

    logger.info(f"Total tools loaded: {len(loaded_tools)}, built-in tools: {len(builtin_tools)}, MCP tools: {len(mcp_tools)}, ACP tools: {len(acp_tools)}")

    # Deduplicate by tool name — config-loaded tools take priority, followed by
    # built-ins, MCP tools, connector tools, and ACP tools.  Duplicate names
    # cause the LLM to receive ambiguous schemas (issue #1803).
    all_tools = loaded_tools + builtin_tools + mcp_tools + connector_tools + acp_tools
    seen_names: set[str] = set()
    unique_tools: list[BaseTool] = []
    for t in all_tools:
        if t.name not in seen_names:
            unique_tools.append(t)
            seen_names.add(t.name)
        else:
            logger.warning(
                "Duplicate tool name %r detected and skipped — check your config.yaml and MCP server registrations (issue #1803).",
                t.name,
            )

    # Provider tool-array cap: fail with a structured error the API can turn
    # into "N / cap" rather than letting the provider return an opaque 400.
    if max_tools is not None and len(unique_tools) > max_tools:
        raise ToolCapExceededError(count=len(unique_tools), cap=max_tools)

    return unique_tools
