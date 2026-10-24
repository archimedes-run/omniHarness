import logging

from langchain.tools import BaseTool

from omniharness.config import get_app_config
from omniharness.config.app_config import AppConfig
from omniharness.persistence.thread_tool_selection.sql import PINNED_SOURCES
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
# Always available in every conversation, no per-thread selection needed.
# session-watcher earns its place because "what are my sessions doing?" is a
# question you ask from anywhere, and ceremony defeats the point. It costs two
# read-only Tier-1 tools against the schema budget.
#
# DERIVED, not duplicated. The canonical list is PINNED_SOURCES in
# omniharness/persistence/thread_tool_selection/sql.py, which is what actually
# enforces pinning on save. Keeping a second hand-maintained copy here is how
# the two drifted: session-watcher was added to one and not the other, the
# runtime kept working, and the picker showed a `pinned` list that was false.
PINNED_LOCAL_SERVERS: frozenset[str] = frozenset(src.removeprefix("local:") for src in PINNED_SOURCES)


# Default provider tool-array caps by model-provider class-path fragment.
# OpenAI hard-limits the tools array to 128. Others are effectively unbounded
# here; we use a generous sentinel so the cap only bites where it must.
_PROVIDER_TOOL_CAPS: dict[str, int] = {"openai": 128}
_DEFAULT_TOOL_CAP = 512


def resolve_model_tool_cap(model_config: object | None) -> int:
    """Resolve the tool-array cap for a model.

    Priority: explicit ``model_config.max_tools`` → provider default (matched
    against the ``use`` class path) → generous fallback.
    """
    if model_config is None:
        return _DEFAULT_TOOL_CAP
    explicit = getattr(model_config, "max_tools", None)
    if explicit:
        return int(explicit)
    use_path = str(getattr(model_config, "use", "") or "").lower()
    for fragment, cap in _PROVIDER_TOOL_CAPS.items():
        if fragment in use_path:
            return cap
    return _DEFAULT_TOOL_CAP


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


def builtin_tool_registry(config: AppConfig | None = None) -> dict[str, object]:
    """Every built-in tool this process can offer, by canonical name
    (tools.names.canonical_tool_name): the in-process tools, whether or not
    this agent gets them, and the tools config.yaml loads. The registry
    decides built-in identity; a tool's NAME never does (review round 3)."""
    from omniharness.tools.builtins.ledger_tool import ledger_apply_tool, ledger_read_tool
    from omniharness.tools.builtins.tool_search import tool_search
    from omniharness.tools.names import canonical_tool_name
    from omniharness.tools.skill_manage_tool import skill_manage_tool

    objects: list[object] = [*BUILTIN_TOOLS, *SUBAGENT_TOOLS, skill_manage_tool, preview_tool, mcp_build_tool, view_image_tool, ledger_read_tool, ledger_apply_tool, tool_search]
    registry: dict[str, object] = {canonical_tool_name(getattr(t, "name", "")): t for t in objects}
    cfg = config
    if cfg is None:
        try:
            cfg = get_app_config()
        except Exception:  # noqa: BLE001 — no config: the in-process tools alone
            cfg = None
    for tool_cfg in getattr(cfg, "tools", None) or []:
        registry.setdefault(canonical_tool_name(tool_cfg.name), f"config:{tool_cfg.use}")
    return registry


def refuse_builtin_collisions(tools: list[BaseTool], source: str, config: AppConfig | None = None) -> list[BaseTool]:
    """Refuse, at load, any MCP / connector / built tool whose name (in any
    spelling: case, hyphen or underscore) is a built-in's. It is dropped and
    logged, never offered: it can neither shadow the built-in nor pass as it
    (a built-in's output may be trusted; an outside tool's never is)."""
    from omniharness.tools.names import canonical_tool_name

    builtins = builtin_tool_registry(config)
    kept: list[BaseTool] = []
    for tool in tools:
        if canonical_tool_name(tool.name) in builtins:
            logger.error("refused %s tool %r: its name collides with the built-in tool %r", source, tool.name, canonical_tool_name(tool.name))
            continue
        kept.append(tool)
    return kept


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
    tool_access: object | None = None,
) -> list[BaseTool]:
    """Get all available tools from config.

    Note: MCP tools should be initialized at application startup using
    `initialize_mcp_tools()` from omniharness.mcp module.

    Args:
        groups: Optional list of tool groups to filter by.
        include_mcp: Whether to include tools from MCP servers (default: True).
        model_name: Optional model name to determine if vision tools should be included.
        subagent_enabled: Whether to include subagent tools (task, task_status).
        tool_access: An agent's per-tool allowlist (006-G, AgentConfig.tools),
            or None. When given it REPLACES `groups` and `selected_sources`:
            the agent's own integrations are loaded (its MCP servers, its
            connector toolkits for `user_id`), and the final list keeps the
            core tools plus only the tools it names
            (omniharness.tools.agent_access.apply_tool_access).

    Returns:
        List of available tools.
    """
    from omniharness.tools.agent_access import access_of, apply_tool_access, connector_toolkits, local_servers

    config = app_config or get_app_config()
    access = access_of(tool_access)
    if access is not None:
        # The allowlist decides, per tool; the broad groups and the chat's
        # source picker do not widen (or narrow) what the owner assigned.
        groups = None
        selected_sources = None
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

    # Add the Project Ledger tools only when a LedgerController is registered
    # (gateway mode, Feature 005).
    from omniharness.runtime.ledger.controller import get_ledger_controller

    if get_ledger_controller() is not None:
        from omniharness.tools.builtins.ledger_tool import ledger_apply_tool, ledger_read_tool

        builtin_tools.extend([ledger_read_tool, ledger_apply_tool])

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

                # 006-G: an agent with an allowlist gets tools only from the
                # MCP servers it names, attributed by server NAME (a tool whose
                # server cannot be told is never attributable, so never kept).
                allowed_local = local_servers(tool_access) if access is not None else None
                if allowed_local is not None:
                    server_names = list(enabled_servers.keys())
                    mcp_tools = [t for t in mcp_tools if (src := _tool_source(t.name, server_names)) is not None and not src.lower().startswith(("connector-", "composio-")) and src in allowed_local]

                # Feature 006: each tool carries its source, so the tool-call
                # chokepoint can record when that source last worked.
                from omniharness.tools.source_tags import tag_source

                all_server_names = list(enabled_servers.keys())
                for t in mcp_tools:
                    server = _tool_source(t.name, all_server_names)
                    if server and not server.lower().startswith(("connector-", "composio-")):
                        tag_source(t, f"local:{server}")

                mcp_tools = refuse_builtin_collisions(mcp_tools, "MCP", config)
                if access is not None:
                    # Before the deferred registry: tool_search only ever
                    # finds the agent's OWN tools.
                    mcp_tools = apply_tool_access(mcp_tools, tool_access, config=config)
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
    if (selected_sources or access is not None) and user_id:
        try:
            from omniharness.tools.connector_tools import CONNECTOR_SLUGS, load_connector_tools

            if access is not None:
                # 006-G: the agent's own toolkits, whatever the chat picked.
                wanted_connectors = [slug for slug in connector_toolkits(tool_access) if slug in CONNECTOR_SLUGS]
            else:
                wanted_connectors = [sid.split(":", 1)[1].upper() for sid in selected_sources if sid.startswith("connector:") and sid.split(":", 1)[1].upper() in CONNECTOR_SLUGS]
            if wanted_connectors:
                connector_tools = assemble_connector_tools(config, user_id, wanted_connectors, loader=load_connector_tools)
                logger.info(f"Loaded {len(connector_tools)} live connector tool(s) for {len(wanted_connectors)} toolkit(s)")
        except Exception as e:
            logger.error(f"Failed to load connector tools: {e}")

    logger.info(f"Total tools loaded: {len(loaded_tools)}, built-in tools: {len(builtin_tools)}, MCP tools: {len(mcp_tools)}")

    # Deduplicate by tool name — config-loaded tools take priority, followed by
    # built-ins, MCP tools and connector tools.  Duplicate names
    # cause the LLM to receive ambiguous schemas (issue #1803).
    all_tools = loaded_tools + builtin_tools + mcp_tools + connector_tools
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

    # 006-G: THE enforcement point for an agent's allowlist. Every run path
    # (chat, @-call, delegation, a scheduled firing, a confirmation's rebuild)
    # assembles its tools here; what the allowlist does not name is not offered.
    if access is not None:
        config_groups = {loaded.name: cfg.group for cfg, loaded in loaded_tools_raw if getattr(cfg, "group", None)}
        unique_tools = apply_tool_access(unique_tools, tool_access, config=config, config_groups=config_groups)

    # Provider tool-array cap: fail with a structured error the API can turn
    # into "N / cap" rather than letting the provider return an opaque 400.
    if max_tools is not None and len(unique_tools) > max_tools:
        raise ToolCapExceededError(count=len(unique_tools), cap=max_tools)

    return unique_tools


def assemble_connector_tools(config, user_id: str, toolkits: list[str], *, loader=None) -> list[BaseTool]:
    """A user's live connector tools for `toolkits`, as a run gets them: loaded
    per user, the configured tool surface applied, built-in collisions refused.
    One function, two callers: get_available_tools and the Studio's tool
    catalog (006-G), so the catalog never lists a tool a run would not get."""
    if loader is None:
        from omniharness.tools.connector_tools import load_connector_tools as loader
    tools = loader(user_id, toolkits)
    # FR-012/FR-013: the SECOND assembly point. Gmail and Google
    # Calendar exist as connector toolkits, and this path never
    # touches mcp/tools.py — a deny applied only there would leave
    # connector:GMAIL and its send tool fully exposed.
    tools = apply_connector_tool_surface(config, tools)
    return refuse_builtin_collisions(tools, "connector", config)


def apply_connector_tool_surface(config, connector_tools: list[BaseTool]) -> list[BaseTool]:
    """Drop denied tools from the connector surface (FR-012, FR-013).

    Connector toolkits are configured under the same ``mcpServers`` key by their
    lowercased slug, so ``GMAIL`` reads its surface from a ``gmail`` entry. That
    keeps one place to express "this tool must not exist", regardless of which
    route the tool arrives by — which is what makes the tool-surface gate
    assertable on the FINAL assembled list rather than per path.
    """
    from omniharness.config.extensions_config import ExtensionsConfig

    try:
        extensions = ExtensionsConfig.from_file()
    except Exception:  # noqa: BLE001 — a config read must not break tool loading
        return connector_tools

    kept: list[BaseTool] = []
    for tool in connector_tools:
        server = None
        server_name = ""
        unprefixed = tool.name
        for name, entry in extensions.mcp_servers.items():
            # BOTH PREFIXES. Connector tools arrive as
            # `connector-gmail_GMAIL_SEND_EMAIL`, not `gmail_send_email`, so
            # matching only `f"{name}_"` found no server, left `surface` None,
            # and KEPT every tool — including the send capability FR-012
            # requires to be absent. Measured 2026-09-23: the deny list was
            # correct and matched nothing.
            for prefix in (f"{name}_", f"connector-{name}_"):
                if tool.name.startswith(prefix):
                    server, server_name, unprefixed = entry, name, tool.name[len(prefix) :]
                    break
            if server is not None:
                break
        surface = getattr(server, "tools", None)
        # Case-insensitively (via `permits`): the deny list is written
        # `send_email` and the connector names the same capability
        # `GMAIL_SEND_EMAIL`. A guarantee that depends on matching case is not
        # a guarantee.
        # `server_name`, not the loop variable `name`: when no MCP servers are
        # configured the loop never runs and `name` is unbound. That passed on a
        # machine with an extensions_config.json and raised UnboundLocalError in
        # CI, which has none — a test inheriting ambient state, one day after
        # Article XIV was extended to say exactly that.
        # `permits` compares in canonical form (omniharness.tools.names), so
        # only the toolkit's own repeated prefix (`GMAIL_`) is stripped here.
        from omniharness.tools.names import canonical_tool_name

        candidates = {unprefixed}
        if server_name and canonical_tool_name(unprefixed).startswith(f"{canonical_tool_name(server_name)}_"):
            candidates.add(unprefixed[len(server_name) + 1 :])
        if surface is None or all(surface.permits(c) for c in candidates):
            kept.append(tool)
        else:
            logger.info("Tool surface: connector tool '%s' is denied and will not be exposed", tool.name)
    return kept


def registrable_tool_names(app_config: AppConfig) -> list[str]:
    """EVERY tool name this process can offer an agent, whatever the conditions.

    `get_available_tools` decides per agent: a vision model gets view_image,
    gateway mode gets preview and mcp_build, plan mode gets write_todos, a
    custom agent gets update_agent. A policy coverage check (007: every tool
    resolves to an explicit rule) needs the UNION, because a tool reachable
    under any condition must already have a rule when that condition arises.

    MCP tools are included only when they have ALREADY been loaded: reading
    their names must not spawn every configured server. They are checked again
    when they load (omniharness.mcp.cache.add_tools_loaded_listener). Connector
    tools are per user and per turn, and are checked where they are offered.

    Kept beside get_available_tools on purpose: a built-in added there and not
    here is caught by tests/policy/test_tool_coverage.py, which asserts that
    every tool get_available_tools returns (all conditions on) is listed here.
    """
    from omniharness.agents.middlewares.todo_middleware import TodoMiddleware
    from omniharness.mcp.cache import loaded_mcp_tools
    from omniharness.tools.builtins import setup_agent, update_agent
    from omniharness.tools.builtins.ledger_tool import ledger_apply_tool, ledger_read_tool
    from omniharness.tools.builtins.tool_search import tool_search
    from omniharness.tools.skill_manage_tool import skill_manage_tool

    names: list[str] = []
    for cfg in app_config.tools:
        try:
            names.append(resolve_variable(cfg.use, BaseTool).name)
        except Exception:  # noqa: BLE001 — a config tool that cannot load is never offered
            logger.warning("tool %r (%s) could not be loaded, so it is not offered", cfg.name, cfg.use)
    names += [t.name for t in (*BUILTIN_TOOLS, preview_tool, mcp_build_tool, ledger_read_tool, ledger_apply_tool, *SUBAGENT_TOOLS, view_image_tool, tool_search, skill_manage_tool, setup_agent, update_agent)]
    names += [t.name for t in TodoMiddleware().tools]
    names += [t.name for t in (loaded_mcp_tools() or [])]
    return list(dict.fromkeys(names))
