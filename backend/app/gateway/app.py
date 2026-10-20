import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.config import get_gateway_config
from app.gateway.csrf_middleware import CSRFMiddleware
from app.gateway.deps import langgraph_runtime
from app.gateway.log_files import install_log_file
from app.gateway.logging_filters import install_preview_token_log_filter
from app.gateway.preview_sessions import PreviewSessionManager
from app.gateway.routers import (
    agents,
    artifacts,
    assistants_compat,
    auth,
    automations,
    channels,
    composio,
    confirmations,
    feedback,
    home,
    inbox,
    ledger,
    mcp,
    mcp_studio,
    memory,
    models,
    openclaw_webhook,
    policy,
    preferences,
    previews,
    run_history,
    runs,
    sessions,
    skills,
    suggestions,
    thread_runs,
    thread_skills,
    thread_tools,
    threads,
    tool_sources,
    tool_sources_retry,
    triggers,
    uploads,
    workflows,
)
from omniharness.config import app_config as omniharness_app_config
from omniharness.config.app_config import apply_logging_level

AppConfig = omniharness_app_config.AppConfig
get_app_config = omniharness_app_config.get_app_config

# Default logging; lifespan overrides from config.yaml log_level.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
install_preview_token_log_filter()
# GATEWAY_LOG_FILE: append-only daily files, 30 days kept (app.gateway.log_files).
install_log_file()

logger = logging.getLogger(__name__)

# Upper bound (seconds) each lifespan shutdown hook is allowed to run.
# Bounds worker exit time so uvicorn's reload supervisor does not keep
# firing signals into a worker that is stuck waiting for shutdown cleanup.
_SHUTDOWN_HOOK_TIMEOUT_SECONDS = 5.0


async def _ensure_admin_user(app: FastAPI) -> None:
    """Startup hook: handle first boot and migrate orphan threads otherwise.

    After admin creation, migrate orphan threads from the LangGraph
    store (metadata.user_id unset) to the admin account. This is the
    "no-auth → with-auth" upgrade path: users who ran OmniHarness without
    authentication have existing LangGraph thread data that needs an
    owner assigned.
        First boot (no admin exists):
            - Does NOT create any user accounts automatically.
            - The operator must visit ``/setup`` to create the first admin.

    Subsequent boots (admin already exists):
      - Runs the one-time "no-auth → with-auth" orphan thread migration for
        existing LangGraph thread metadata that has no owner_id.

    No SQL persistence migration is needed: the four user_id columns
    (threads_meta, runs, run_events, feedback) only come into existence
    alongside the auth module via create_all, so freshly created tables
    never contain NULL-owner rows.
    """

    from app.gateway.deps import get_local_provider
    from omniharness.persistence.engine import get_session_factory

    try:
        provider = get_local_provider()
    except RuntimeError:
        # Auth persistence may not be initialized in some test/boot paths.
        # Skip admin migration work rather than failing gateway startup.
        logger.warning("Auth persistence not ready; skipping admin bootstrap check")
        return

    sf = get_session_factory()
    if sf is None:
        return

    # Security baseline: hand-disabled accounts move to disabled_at first, so
    # the owner is never resolved to one; then say who the owner is (id only).
    try:
        from app.gateway.ownership import log_owner_at_startup, migrate_prefix_disabled_accounts

        await migrate_prefix_disabled_accounts()
        await log_owner_at_startup()
    except Exception:
        logger.exception("Could not resolve the owner account at startup (non-fatal)")

    # Orphan migrations follow the OWNER (app.gateway.ownership), whether or not
    # an admin-role account exists: the owner is whoever is pinned, and the
    # role says nothing about whose data it is.
    from app.gateway.ownership import owner_user_id

    owner = await owner_user_id()
    if owner is None:
        if await provider.count_admin_users() == 0:
            logger.info("=" * 60)
            logger.info("  First boot detected — no account exists yet.")
            logger.info("  Visit /setup to create the owner account.")
            logger.info("=" * 60)
        return
    admin_id = owner

    # Security baseline: NULL-owner rows used to be readable by every account.
    # They become the owner's (app.gateway.ownership). Non-fatal.
    try:
        from app.gateway.ownership import assign_ownerless_rows_to_owner

        await assign_ownerless_rows_to_owner()
    except Exception:
        logger.exception("Owner-less row migration failed (non-fatal)")

    # LangGraph store orphan migration — non-fatal.
    # This covers the "no-auth → with-auth" upgrade path for users
    # whose existing LangGraph thread metadata has no user_id set.
    store = getattr(app.state, "store", None)
    if store is not None:
        try:
            migrated = await _migrate_orphaned_threads(store, admin_id)
            if migrated:
                logger.info("Migrated %d orphan LangGraph thread(s) to admin", migrated)
        except Exception:
            logger.exception("LangGraph thread migration failed (non-fatal)")


async def _iter_store_items(store, namespace, *, page_size: int = 500):
    """Paginated async iterator over a LangGraph store namespace.

    Replaces the old hardcoded ``limit=1000`` call with a cursor-style
    loop so that environments with more than one page of orphans do
    not silently lose data. Terminates when a page is empty OR when a
    short page arrives (indicating the last page).
    """
    offset = 0
    while True:
        batch = await store.asearch(namespace, limit=page_size, offset=offset)
        if not batch:
            return
        for item in batch:
            yield item
        if len(batch) < page_size:
            return
        offset += page_size


async def _migrate_orphaned_threads(store, admin_user_id: str) -> int:
    """Migrate LangGraph store threads with no user_id to the given admin.

    Uses cursor pagination so all orphans are migrated regardless of
    count. Returns the number of rows migrated.
    """
    migrated = 0
    async for item in _iter_store_items(store, ("threads",)):
        metadata = item.value.get("metadata", {})
        if not metadata.get("user_id"):
            metadata["user_id"] = admin_user_id
            item.value["metadata"] = metadata
            await store.aput(("threads",), item.key, item.value)
            migrated += 1
    return migrated


async def _start_trigger_engine(app: FastAPI):
    """Contend for leadership and, on winning, start the engine.

    Losing is the normal outcome for most workers and is logged as such, not as
    a failure: under `uvicorn --workers 4`, three are meant to lose.
    """
    from app.gateway import trigger_engine_wiring as wiring
    from app.trigger_engine import lifespan as engine_lifespan

    config = app.state.config
    if not config.trigger_engine.enabled:
        logger.info("Trigger engine disabled by configuration")
        return None

    lock = None
    try:
        lock = wiring.elect(config)
        if lock is None:
            return None

        handle = await engine_lifespan.start(
            # The SAME call the Article XI integration test makes
            # (tests/trigger_engine/test_production_wiring.py). Argument
            # construction lives in the wiring module so that a test cannot
            # exercise a different argument list from the one that ships.
            lambda: wiring.build_production_loop(config, run_store=app.state.run_store, run_history=getattr(app.state, "run_history", None)),
            enabled=True,
        )
        if handle.error:
            # Kept, not dropped: the handle carries WHY the engine is not
            # running (e.g. a rule whose feed is not connected), and
            # GET /api/triggers/status is where a person reads it.
            _release_engine_lock(lock)
            return handle
        handle.lock = lock
        logger.info("Trigger engine: %s", wiring.describe(config, lock))
        return handle
    except Exception:
        logger.exception("Trigger engine failed to start; the gateway continues without it")
        _release_engine_lock(lock)
        return None


def _release_engine_lock(lock) -> None:
    if lock is not None:
        try:
            lock.release()
        except Exception:
            logger.warning("releasing the trigger-engine lock failed", exc_info=True)


async def _stop_trigger_engine(app: FastAPI) -> None:
    handle = getattr(app.state, "trigger_engine", None)
    if handle is None:
        return
    from app.trigger_engine import lifespan as engine_lifespan

    try:
        await asyncio.wait_for(engine_lifespan.stop(handle), timeout=_SHUTDOWN_HOOK_TIMEOUT_SECONDS)
    except TimeoutError:
        logger.warning("Trigger engine shutdown exceeded %.1fs; proceeding with worker exit.", _SHUTDOWN_HOOK_TIMEOUT_SECONDS)
    except Exception:
        logger.exception("Trigger engine shutdown raised")
    finally:
        _release_engine_lock(getattr(handle, "lock", None))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler."""

    # Load config and check necessary environment variables at startup
    try:
        app.state.config = get_app_config()
        apply_logging_level(app.state.config.log_level)
        logger.info("Configuration loaded successfully")
    except Exception as e:
        error_msg = f"Failed to load configuration during gateway startup: {e}"
        logger.exception(error_msg)
        raise RuntimeError(error_msg) from e
    # Dead secrets: name (never show) any secret key nothing active uses.
    try:
        from app.gateway.secret_usage import log_unused_secrets

        log_unused_secrets()
    except Exception:
        logger.exception("Could not check for unused secret keys (non-fatal)")
    from app.gateway.config import actual_bind, published_address_warning

    warning = published_address_warning()
    if warning:
        logger.warning(warning)

    bind = actual_bind()
    if bind is None:
        logger.info("Starting API Gateway (bind address not set by a uvicorn command line in this process)")
    else:
        logger.info("Starting API Gateway; uvicorn binds %s:%s%s", bind[0], bind[1], "" if bind[0] in ("127.0.0.1", "::1", "localhost") else " (NOT loopback: reachable beyond this machine unless a container network isolates it)")

    # Initialize LangGraph runtime components (StreamBridge, RunManager, checkpointer, store)
    async with langgraph_runtime(app):
        logger.info("LangGraph runtime initialised")
        app.state.preview_session_manager = PreviewSessionManager()
        app.state.preview_session_manager.start()
        from app.gateway.preview_controller_adapter import GatewayPreviewController
        from omniharness.preview.preview_controller import set_preview_controller

        preview_ctrl = GatewayPreviewController(app.state.preview_session_manager)
        app.state.preview_controller = preview_ctrl
        set_preview_controller(preview_ctrl)

        # MCP build controller — only when mcp_server_manager was wired in langgraph_runtime
        mcp_mgr = getattr(app.state, "mcp_server_manager", None)
        if mcp_mgr is not None:
            await mcp_mgr.start()
            from app.gateway.mcp_build_controller_adapter import GatewayMCPBuildController
            from omniharness.runtime.mcp.controller import set_mcp_build_controller

            mcp_ctrl = GatewayMCPBuildController(mcp_mgr)
            app.state.mcp_build_controller = mcp_ctrl
            set_mcp_build_controller(mcp_ctrl)

        # Ensure admin user exists (auto-create on first boot)
        # Must run AFTER langgraph_runtime so app.state.store is available for thread migration
        await _ensure_admin_user(app)

        # Start IM channel service if any channels are configured
        try:
            from app.channels.service import start_channel_service

            channel_service = await start_channel_service(app.state.config)
            logger.info("Channel service started: %s", channel_service.get_status())
        except Exception:
            logger.exception("No IM channels configured or channel service failed to start")

        # Install the permission policy layer at the tool-dispatch chokepoint
        # (FR-002). Before anything can build an agent: an agent constructed
        # earlier would carry no policy middleware, and would look identical to
        # one that had been checked.
        from app.policy.registration import install as install_policy

        install_policy()

        # 007: every registered tool resolves to an explicit rule; any that do
        # not are refused, and listed here in the startup log. Never fatal: an
        # unruled tool is already refused at dispatch, so a failed check costs
        # the log line, not the gate.
        try:
            from app.policy.coverage import startup_check

            startup_check(app.state.config)
        except Exception:
            logger.exception("policy: the startup tool-coverage check failed")

        # The run history (Feature 006): every automation run's full content,
        # redacted, kept locally under the data dir, purged past retention.
        # Opened before the engine, which records into it. A failure here must
        # not stop the gateway: automations then run without history, and the
        # run-history routes say it is unavailable.
        purge_task = None
        try:
            from app.run_history.lifespan import load_known_secrets, open_history, purge_forever
            from omniharness.config.paths import get_paths

            await load_known_secrets(app)
            app.state.run_history = open_history(get_paths().base_dir)
            purge_task = asyncio.create_task(purge_forever(app.state.run_history))
        except Exception:
            logger.exception("Run history could not be opened; automations run without it")
            app.state.run_history = None

        # Start the trigger engine, in exactly one worker.
        #
        # This is the call site whose absence made Feature 002 ship inert: the
        # loop was fully built and nothing started it. Startup failure must not
        # prevent the gateway from starting — the engine is an addition to the
        # assistant, not a precondition for it.
        app.state.trigger_engine = await _start_trigger_engine(app)

        yield

        # Stop the trigger engine before the channel service, so a firing in
        # flight still has a destination to deliver to.
        await _stop_trigger_engine(app)
        if purge_task is not None:
            purge_task.cancel()

        # Stop channel service on shutdown (bounded to prevent worker hang)
        try:
            from app.channels.service import stop_channel_service

            await asyncio.wait_for(
                stop_channel_service(),
                timeout=_SHUTDOWN_HOOK_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            logger.warning(
                "Channel service shutdown exceeded %.1fs; proceeding with worker exit.",
                _SHUTDOWN_HOOK_TIMEOUT_SECONDS,
            )
        except Exception:
            logger.exception("Failed to stop channel service")

        mcp_server_manager = getattr(app.state, "mcp_server_manager", None)
        if mcp_server_manager is not None:
            try:
                await asyncio.wait_for(
                    mcp_server_manager.close(),
                    timeout=_SHUTDOWN_HOOK_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                logger.warning(
                    "MCP server manager shutdown exceeded %.1fs; proceeding with worker exit.",
                    _SHUTDOWN_HOOK_TIMEOUT_SECONDS,
                )
            except Exception:
                logger.exception("Failed to stop MCP server manager")

        preview_session_manager = getattr(app.state, "preview_session_manager", None)
        if preview_session_manager is not None:
            try:
                await asyncio.wait_for(
                    preview_session_manager.close(),
                    timeout=_SHUTDOWN_HOOK_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                logger.warning(
                    "Preview session manager shutdown exceeded %.1fs; proceeding with worker exit.",
                    _SHUTDOWN_HOOK_TIMEOUT_SECONDS,
                )
            except Exception:
                logger.exception("Failed to stop preview session manager")

    logger.info("Shutting down API Gateway")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        Configured FastAPI application instance.
    """
    # Before anything can make an outbound request: Telegram's bot token rides in
    # the URL path, and httpx logs every URL at INFO (app/gateway/log_redaction.py).
    from app.gateway import log_redaction

    log_redaction.install()

    config = get_gateway_config()
    docs_kwargs = {"docs_url": "/docs", "redoc_url": "/redoc", "openapi_url": "/openapi.json"} if config.enable_docs else {"docs_url": None, "redoc_url": None, "openapi_url": None}

    app = FastAPI(
        title="OmniHarness API Gateway",
        description="""
## OmniHarness API Gateway

API Gateway for OmniHarness - A LangGraph-based AI agent backend with sandbox execution capabilities.

### Features

- **Models Management**: Query and retrieve available AI models
- **MCP Configuration**: Manage Model Context Protocol (MCP) server configurations
- **Memory Management**: Access and manage global memory data for personalized conversations
- **Skills Management**: Query and manage skills and their enabled status
- **Artifacts**: Access thread artifacts and generated files
- **Health Monitoring**: System health check endpoints

### Architecture

LangGraph requests are handled by nginx reverse proxy.
This gateway provides custom endpoints for models, MCP configuration, skills, and artifacts.
        """,
        version="0.1.0",
        lifespan=lifespan,
        **docs_kwargs,
        openapi_tags=[
            {
                "name": "models",
                "description": "Operations for querying available AI models and their configurations",
            },
            {
                "name": "mcp",
                "description": "Manage Model Context Protocol (MCP) server configurations",
            },
            {
                "name": "memory",
                "description": "Access and manage global memory data for personalized conversations",
            },
            {
                "name": "skills",
                "description": "Manage skills and their configurations",
            },
            {
                "name": "artifacts",
                "description": "Access and download thread artifacts and generated files",
            },
            {
                "name": "uploads",
                "description": "Upload and manage user files for threads",
            },
            {
                "name": "threads",
                "description": "Manage OmniHarness thread-local filesystem data",
            },
            {
                "name": "agents",
                "description": "Create and manage custom agents with per-agent config and prompts",
            },
            {
                "name": "suggestions",
                "description": "Generate follow-up question suggestions for conversations",
            },
            {
                "name": "channels",
                "description": "Manage IM channel integrations (Feishu, Slack, Telegram)",
            },
            {
                "name": "assistants-compat",
                "description": "LangGraph Platform-compatible assistants API (stub)",
            },
            {
                "name": "runs",
                "description": "LangGraph Platform-compatible runs lifecycle (create, stream, cancel)",
            },
            {
                "name": "health",
                "description": "Health check and system status endpoints",
            },
        ],
    )

    # Auth: reject unauthenticated requests to non-public paths (fail-closed safety net)
    app.add_middleware(AuthMiddleware)

    # CSRF: Double Submit Cookie pattern for state-changing requests
    app.add_middleware(CSRFMiddleware)

    # CORS: when GATEWAY_CORS_ORIGINS is set (dev without nginx), add CORS middleware.
    # In production, nginx handles CORS and no middleware is needed.
    cors_origins_env = os.environ.get("GATEWAY_CORS_ORIGINS") or os.environ.get("CORS_ORIGINS", "")
    if cors_origins_env:
        cors_origins = [o.strip() for o in cors_origins_env.split(",") if o.strip()]
        # Validate: wildcard origin with credentials is a security misconfiguration
        for origin in cors_origins:
            if origin == "*":
                logger.error("GATEWAY_CORS_ORIGINS contains wildcard '*' with allow_credentials=True. This is a security misconfiguration — browsers will reject the response. Use explicit scheme://host:port origins instead.")
                cors_origins = [o for o in cors_origins if o != "*"]
                break
        if cors_origins:
            app.add_middleware(
                CORSMiddleware,
                allow_origins=cors_origins,
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            )

    # Real client IP (security baseline): X-Forwarded-For/-Proto are honoured
    # ONLY when the TCP peer is a trusted proxy (GATEWAY_TRUSTED_PROXIES: the
    # nginx container's fixed address, or 127.0.0.1 for the host nginx). From
    # any other peer they are ignored. Outermost, so the access log, the rate
    # limiter and every route see the same client address.
    # Host allowlist (DNS rebinding): outermost of all, 421 for a foreign Host.
    from app.gateway.config import HostGuardMiddleware, allowed_hosts

    app.add_middleware(HostGuardMiddleware, hosts=allowed_hosts())

    trusted_proxies = [p.strip() for p in os.environ.get("GATEWAY_TRUSTED_PROXIES", "").split(",") if p.strip()]
    if trusted_proxies:
        from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

        app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=trusted_proxies)

    # Include routers
    # Models API is mounted at /api/models
    app.include_router(models.router)

    # MCP API is mounted at /api/mcp
    app.include_router(mcp.router)

    # MCP Studio API is mounted at /api/mcp-studio
    app.include_router(mcp_studio.router)

    # Composio 1-click OAuth connector API is mounted at /api/composio
    app.include_router(composio.router)

    # Per-conversation tools (catalog + per-thread selection + count/cap)
    app.include_router(thread_tools.router)
    app.include_router(thread_skills.router)

    # Per-user preferences (appearance) are mounted at /api/preferences
    app.include_router(preferences.router)

    # Memory API is mounted at /api/memory
    app.include_router(memory.router)

    # Skills API is mounted at /api/skills
    app.include_router(skills.router)

    # Artifacts API is mounted at /api/threads/{thread_id}/artifacts
    app.include_router(artifacts.router)

    # Preview sessions API is mounted at /api/threads/{thread_id}/previews
    app.include_router(previews.router)

    # Uploads API is mounted at /api/threads/{thread_id}/uploads
    app.include_router(uploads.router)

    # Thread cleanup API is mounted at /api/threads/{thread_id}
    app.include_router(threads.router)
    # Surface 1: pending Tier 3 confirmations (Feature 004).
    app.include_router(confirmations.router)

    # Trigger engine status: why it is or is not running (Phase 1 wiring pass).
    app.include_router(triggers.router)
    app.include_router(run_history.router)

    # Automations: the one write path for trigger rules (Phase 2.5).
    app.include_router(automations.router)

    # Inbox: alerts the engine held, failed or delivered (Phase 2.5).
    app.include_router(inbox.router)

    # Home (Feature 006): alert dismissals, upcoming automation runs, today.
    app.include_router(home.router)

    # The Project Ledger: projects, goals, tasks, decisions, links (Feature 005).
    app.include_router(ledger.router)

    # Tool source status: configured, disabled, unreachable or live (FR-040).
    app.include_router(tool_sources.router)
    app.include_router(tool_sources_retry.router)

    # Coding sessions, and whether they can be seen (Feature 004, US3).
    app.include_router(sessions.router)

    # The policy inspector: rules in force, tier check, Tier 3 audit (Feature 004, US4).
    app.include_router(policy.router)

    # Agents API is mounted at /api/agents
    app.include_router(agents.router)

    # Suggestions API is mounted at /api/threads/{thread_id}/suggestions
    app.include_router(suggestions.router)

    # Channels API is mounted at /api/channels
    app.include_router(channels.router)

    # OpenClaw webhook receiver at /api/channels/openclaw/webhook
    app.include_router(openclaw_webhook.router)

    # Assistants compatibility API (LangGraph Platform stub)
    app.include_router(assistants_compat.router)

    # Auth API is mounted at /api/v1/auth
    app.include_router(auth.router)

    # Feedback API is mounted at /api/threads/{thread_id}/runs/{run_id}/feedback
    app.include_router(feedback.router)

    # Thread Runs API (LangGraph Platform-compatible runs lifecycle)
    app.include_router(thread_runs.router)

    # Stateless Runs API (stream/wait without a pre-existing thread)
    app.include_router(runs.router)

    # Workflows API is mounted at /api/workflows (feature-flagged, returns 404 when disabled)
    app.include_router(workflows.router)

    @app.get("/health", tags=["health"])
    async def health_check() -> dict:
        """Health check endpoint.

        Returns:
            Service health status information.
        """
        return {"status": "healthy", "service": "omni-harness-gateway"}

    return app


# Create app instance for uvicorn
app = create_app()
