"""Composio 1-click OAuth connector router.

Exposes a catalog of supported toolkits, OAuth initiation/callback handling,
and connection management. On a successful connection the per-user MCP Tool
Router SSE URL is written into ``extensions_config.json`` so the agent runtime
hot-reloads the new toolkit's tools.

Security invariants
-------------------
* ``entity_id`` is always ``str(auth.user.id)`` — the stable DB UUID.
* The COMPOSIO_API_KEY is never logged or returned in responses.
* Every connect / disconnect is audit-logged.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission
from app.gateway.composio_client import ComposioError
from app.gateway.deps import get_composio_client, get_composio_connection_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/composio", tags=["composio"])


# ---------------------------------------------------------------------------
# Toolkit catalog
# ---------------------------------------------------------------------------

TOOLKIT_CATALOG = [
    {"slug": "GMAIL", "name": "Gmail", "icon": "📧", "category": "Productivity", "description": "Read, search, and send emails from your Gmail account."},
    {"slug": "GOOGLECALENDAR", "name": "Google Calendar", "icon": "📅", "category": "Productivity", "description": "List, create, and update calendar events and check availability."},
    {"slug": "GOOGLEDRIVE", "name": "Google Drive", "icon": "🗂️", "category": "Productivity", "description": "List, read, and manage files in Google Drive."},
    {"slug": "SLACK", "name": "Slack", "icon": "💬", "category": "Communication", "description": "List channels, send messages, and read conversation history."},
    {"slug": "NOTION", "name": "Notion", "icon": "📝", "category": "Knowledge", "description": "Search pages, read databases, and create or update Notion content."},
    {"slug": "GITHUB", "name": "GitHub", "icon": "🐙", "category": "Dev Tools", "description": "List repos, manage issues, PRs, and read repository content."},
    {"slug": "LINEAR", "name": "Linear", "icon": "⚡", "category": "Project Mgmt", "description": "View issues, projects, and cycles in your Linear workspace."},
    {"slug": "OUTLOOK", "name": "Outlook", "icon": "📮", "category": "Productivity", "description": "Read and send email and access calendar via Microsoft Outlook."},
]

_VALID_SLUGS = {tk["slug"] for tk in TOOLKIT_CATALOG}

# DB status -> frontend status vocabulary
_DB_TO_FRONTEND = {
    "active": "connected",
    "pending": "pending",
    "failed": "error",
    "revoked": "not_connected",
}


def _get_user_id(request: Request) -> str:
    auth = getattr(request.state, "auth", None)
    if auth and auth.user:
        return str(auth.user.id)
    raise HTTPException(status_code=401, detail="Authentication required")


def _frontend_status(db_status: str | None) -> str:
    if not db_status:
        return "not_connected"
    return _DB_TO_FRONTEND.get(db_status, "not_connected")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ToolkitItem(BaseModel):
    slug: str
    name: str
    icon: str
    category: str
    description: str
    status: str
    account_display: str | None = None


class CatalogResponse(BaseModel):
    toolkits: list[ToolkitItem]


class InitiateRequest(BaseModel):
    toolkit: str = Field(..., min_length=1)
    redirect_url: str = Field(..., min_length=1)


class ConnectionItem(BaseModel):
    toolkit: str
    status: str
    account_display: str | None = None
    composio_connection_id: str | None = None
    created_at: str | None = None


class ConnectionsResponse(BaseModel):
    connections: list[ConnectionItem]


# ---------------------------------------------------------------------------
# Pending-connection sync helper
# ---------------------------------------------------------------------------


async def _sync_if_pending(row, *, client, repo, user_id: str):
    """Check Composio's live status for a pending DB row and update if changed.

    Returns the (potentially updated) row. No-op for non-pending rows or when
    the Composio call fails — best-effort only.
    """
    if row.get("status") != "pending" or not row.get("composio_connection_id"):
        return row
    if client is None:
        return row
    try:
        real_status = await client.get_connection_status(composio_connection_id=row["composio_connection_id"])
        if real_status == "pending":
            return row
        account_display = None
        if real_status == "active":
            try:
                account_display = await client.get_account_display(composio_connection_id=row["composio_connection_id"])
            except ComposioError:
                pass
            try:
                mcp_url = client.get_mcp_url(toolkit=row["toolkit"], entity_id=user_id)
                _write_mcp_entry(
                    toolkit=row["toolkit"],
                    mcp_url=mcp_url,
                    description=f"Composio {row['toolkit']} tools (1-click connection)",
                )
            except Exception:
                pass
        return await repo.upsert(
            user_id=user_id,
            toolkit=row["toolkit"],
            composio_connection_id=row["composio_connection_id"],
            status=real_status,
            account_display=account_display,
        )
    except Exception:
        return row  # best-effort; keep stale row on any failure


# ---------------------------------------------------------------------------
# extensions_config.json helpers
# ---------------------------------------------------------------------------


def _server_name(toolkit: str) -> str:
    return f"composio-{toolkit.lower()}"


def _write_mcp_entry(*, toolkit: str, mcp_url: str, description: str) -> None:
    """Add/update the Composio MCP SSE entry in extensions_config.json."""
    from pathlib import Path

    from omniharness.config.extensions_config import ExtensionsConfig, get_extensions_config, reload_extensions_config

    config_path = ExtensionsConfig.resolve_config_path()
    if config_path is None:
        config_path = Path.cwd().parent / "extensions_config.json"

    current = get_extensions_config()
    data: dict = {
        "mcpServers": {n: s.model_dump() for n, s in current.mcp_servers.items()},
        "skills": {n: {"enabled": sk.enabled} for n, sk in current.skills.items()},
    }
    data["mcpServers"][_server_name(toolkit)] = {
        "enabled": True,
        "type": "sse",
        "url": mcp_url,
        "description": description,
    }
    with open(config_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    reload_extensions_config()


def _remove_mcp_entry(*, toolkit: str) -> None:
    """Remove the Composio MCP SSE entry from extensions_config.json (if present)."""
    from pathlib import Path

    from omniharness.config.extensions_config import ExtensionsConfig, get_extensions_config, reload_extensions_config

    config_path = ExtensionsConfig.resolve_config_path()
    if config_path is None:
        config_path = Path.cwd().parent / "extensions_config.json"

    current = get_extensions_config()
    servers = {n: s.model_dump() for n, s in current.mcp_servers.items()}
    if servers.pop(_server_name(toolkit), None) is None:
        return
    data: dict = {
        "mcpServers": servers,
        "skills": {n: {"enabled": sk.enabled} for n, sk in current.skills.items()},
    }
    with open(config_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    reload_extensions_config()


# ---------------------------------------------------------------------------
# GET /catalog
# ---------------------------------------------------------------------------


@router.get("/catalog", response_model=CatalogResponse)
@require_permission("threads", "read")
async def get_catalog(request: Request) -> CatalogResponse:
    user_id = _get_user_id(request)
    repo = get_composio_connection_repo(request)
    client = get_composio_client(request)

    connections = await repo.list_by_user(user_id=user_id)
    synced = []
    for row in connections:
        synced.append(await _sync_if_pending(row, client=client, repo=repo, user_id=user_id))
    by_toolkit = {c["toolkit"]: c for c in synced}

    items: list[ToolkitItem] = []
    for tk in TOOLKIT_CATALOG:
        conn = by_toolkit.get(tk["slug"])
        items.append(
            ToolkitItem(
                slug=tk["slug"],
                name=tk["name"],
                icon=tk["icon"],
                category=tk["category"],
                description=tk["description"],
                status=_frontend_status(conn["status"] if conn else None),
                account_display=conn.get("account_display") if conn else None,
            )
        )
    return CatalogResponse(toolkits=items)


# ---------------------------------------------------------------------------
# POST /connections/initiate
# ---------------------------------------------------------------------------


@router.post("/connections/initiate")
@require_permission("threads", "write")
async def initiate_connection(body: InitiateRequest, request: Request):
    user_id = _get_user_id(request)
    toolkit = body.toolkit.upper()
    if toolkit not in _VALID_SLUGS:
        raise HTTPException(status_code=400, detail=f"Unknown toolkit: {body.toolkit}")

    repo = get_composio_connection_repo(request)
    client = get_composio_client(request)

    # Idempotency: already-active connection short-circuits.
    existing = await repo.get_by_user_toolkit(user_id=user_id, toolkit=toolkit)
    if existing and existing.get("status") == "active":
        logger.info("composio.initiate user=%s toolkit=%s already_connected", user_id, toolkit)
        return {"status": "already_connected"}

    try:
        result = await client.initiate_connection(
            entity_id=user_id,
            toolkit=toolkit,
            redirect_url=body.redirect_url,
        )
    except ComposioError as exc:
        logger.warning("composio.initiate user=%s toolkit=%s failed: %s", user_id, toolkit, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    await repo.upsert(
        user_id=user_id,
        toolkit=toolkit,
        composio_connection_id=result.get("composio_connection_id"),
        status="pending",
    )

    logger.info("composio.connect user=%s toolkit=%s (pending)", user_id, toolkit)
    return {
        "composio_redirect_url": result.get("redirect_url"),
        "connection_id": result.get("composio_connection_id"),
    }


# ---------------------------------------------------------------------------
# GET /connections/callback
# ---------------------------------------------------------------------------


@router.get("/connections/callback")
@require_permission("threads", "read")
async def connection_callback(
    request: Request,
    connection_id: str = Query(...),
    toolkit: str = Query(...),
):
    user_id = _get_user_id(request)
    toolkit = toolkit.upper()
    if toolkit not in _VALID_SLUGS:
        raise HTTPException(status_code=400, detail=f"Unknown toolkit: {toolkit}")

    repo = get_composio_connection_repo(request)
    client = get_composio_client(request)

    try:
        status = await client.get_connection_status(composio_connection_id=connection_id)
    except ComposioError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    account_display: str | None = None
    if status == "active":
        try:
            account_display = await client.get_account_display(composio_connection_id=connection_id)
        except ComposioError:
            account_display = None
        await repo.upsert(
            user_id=user_id,
            toolkit=toolkit,
            composio_connection_id=connection_id,
            status="active",
            account_display=account_display,
        )
        # Write the per-user MCP Tool Router URL so the agent picks up the tools.
        try:
            mcp_url = client.get_mcp_url(toolkit=toolkit, entity_id=user_id)
            _write_mcp_entry(
                toolkit=toolkit,
                mcp_url=mcp_url,
                description=f"Composio {toolkit} tools (1-click connection)",
            )
        except Exception as exc:  # pragma: no cover - file IO best-effort
            logger.warning("composio.callback failed to write extensions_config: %s", exc)
        logger.info("composio.connect user=%s toolkit=%s active", user_id, toolkit)
    else:
        await repo.upsert(
            user_id=user_id,
            toolkit=toolkit,
            composio_connection_id=connection_id,
            status=status,
        )

    return {"status": status, "toolkit": toolkit, "account_display": account_display}


# ---------------------------------------------------------------------------
# GET /connections
# ---------------------------------------------------------------------------


@router.get("/connections", response_model=ConnectionsResponse)
@require_permission("threads", "read")
async def list_connections(request: Request) -> ConnectionsResponse:
    user_id = _get_user_id(request)
    repo = get_composio_connection_repo(request)
    client = get_composio_client(request)
    rows = await repo.list_by_user(user_id=user_id)
    synced = []
    for row in rows:
        synced.append(await _sync_if_pending(row, client=client, repo=repo, user_id=user_id))
    return ConnectionsResponse(
        connections=[
            ConnectionItem(
                toolkit=r["toolkit"],
                status=_frontend_status(r["status"]),
                account_display=r.get("account_display"),
                composio_connection_id=r.get("composio_connection_id"),
                created_at=r.get("created_at"),
            )
            for r in synced
        ]
    )


# ---------------------------------------------------------------------------
# GET /connections/{toolkit}
# ---------------------------------------------------------------------------


@router.get("/connections/{toolkit}")
@require_permission("threads", "read")
async def get_connection(toolkit: str, request: Request):
    user_id = _get_user_id(request)
    toolkit = toolkit.upper()
    repo = get_composio_connection_repo(request)
    client = get_composio_client(request)
    row = await repo.get_by_user_toolkit(user_id=user_id, toolkit=toolkit)
    if row is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    row = await _sync_if_pending(row, client=client, repo=repo, user_id=user_id)
    return {
        "status": row["status"],
        "toolkit": row["toolkit"],
        "account_display": row.get("account_display"),
        "composio_connection_id": row.get("composio_connection_id"),
        "created_at": row.get("created_at"),
    }


# ---------------------------------------------------------------------------
# DELETE /connections/{toolkit}
# ---------------------------------------------------------------------------


@router.delete("/connections/{toolkit}", status_code=204)
@require_permission("threads", "write")
async def disconnect(toolkit: str, request: Request) -> Response:
    user_id = _get_user_id(request)
    toolkit = toolkit.upper()
    repo = get_composio_connection_repo(request)

    row = await repo.get_by_user_toolkit(user_id=user_id, toolkit=toolkit)
    if row is None:
        raise HTTPException(status_code=404, detail="Connection not found")

    conn_id = row.get("composio_connection_id")
    if conn_id:
        client = get_composio_client(request)
        try:
            await client.revoke_connection(composio_connection_id=conn_id)
        except ComposioError as exc:
            logger.warning("composio.disconnect user=%s toolkit=%s revoke failed: %s", user_id, toolkit, exc)
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    await repo.mark_revoked(user_id=user_id, toolkit=toolkit)
    try:
        _remove_mcp_entry(toolkit=toolkit)
    except Exception as exc:  # pragma: no cover - file IO best-effort
        logger.warning("composio.disconnect failed to update extensions_config: %s", exc)

    logger.info("composio.disconnect user=%s toolkit=%s", user_id, toolkit)
    return Response(status_code=204)
