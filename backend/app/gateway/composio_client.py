"""Async client for Composio's v3 REST API.

Uses httpx directly — the composio-core SDK's v1 endpoints return HTTP 410
Gone because Composio deprecated them in favour of their v3 API.

Flow for OAuth connection initiation:
  1. _get_auth_config_id(toolkit) — lazy-create and cache a composio-managed
     auth config for the toolkit (one per API key, persists server-side).
  2. POST /v3/connected_accounts/link — get a redirect_url for the user.
  3. User authenticates; we poll /v3/connected_accounts/{id} for status.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://backend.composio.dev/api"


class ComposioError(RuntimeError):
    """Raised when a Composio REST call fails."""


def _normalize_status(raw: Any) -> str:
    """Map Composio v3 status strings to our internal vocabulary.

    v3 statuses are uppercase: INITIALIZING, ACTIVE, FAILED, EXPIRED, etc.
    We normalize to: active | pending | failed | revoked.
    """
    value = str(raw or "").strip().lower()
    if value in ("active", "connected", "success", "successful"):
        return "active"
    if value in ("pending", "initiated", "initializing", "in_progress"):
        return "pending"
    if value in ("revoked", "deleted", "disconnected"):
        return "revoked"
    if not value:
        return "pending"
    return "failed"


class ComposioClient:
    """Async client over Composio's v3 REST API."""

    def __init__(self, api_key: str):
        if not api_key:
            raise RuntimeError("COMPOSIO_API_KEY is required to construct ComposioClient. Set it in the environment (see .env.example).")
        self._api_key = api_key
        self._headers = {"x-api-key": api_key, "Content-Type": "application/json"}
        # In-memory cache: toolkit_slug (lowercase) → auth_config_id
        # Auth configs are stable server-side per API key, so this is safe.
        self._auth_config_ids: dict[str, str] = {}

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(headers=self._headers, base_url=_BASE, timeout=30.0)

    # -- auth config helpers (v3: one composio-managed config per toolkit) ---

    async def _get_auth_config_id(self, toolkit: str) -> str:
        """Return a composio-managed auth config ID for *toolkit*.

        Looks up an existing config first; creates one if none exists.
        """
        slug = toolkit.lower()
        if slug in self._auth_config_ids:
            return self._auth_config_ids[slug]

        async with self._http() as client:
            r = await client.get("/v3/auth_configs", params={"toolkit_slug": slug})
            if r.status_code == 200:
                items = r.json().get("items", [])
                if items:
                    auth_config_id = items[0]["id"]
                    self._auth_config_ids[slug] = auth_config_id
                    return auth_config_id

            r = await client.post(
                "/v3/auth_configs",
                json={"toolkit": {"slug": slug}, "use_composio_managed_auth": True},
            )
            if not r.is_success:
                raise ComposioError(f"Failed to create auth config for {toolkit}: HTTP {r.status_code} — {r.text[:300]}")
            data = r.json()
            auth_config_id = data.get("auth_config", {}).get("id") or data.get("id")
            if not auth_config_id:
                raise ComposioError(f"Composio auth_config response missing id for {toolkit}: {data}")
            self._auth_config_ids[slug] = auth_config_id
            return auth_config_id

    # -- public API ---------------------------------------------------------

    async def initiate_connection(self, *, entity_id: str, toolkit: str, redirect_url: str) -> dict[str, Any]:
        """Start an OAuth flow. Returns ``{"redirect_url", "composio_connection_id"}``."""
        auth_config_id = await self._get_auth_config_id(toolkit)
        async with self._http() as client:
            r = await client.post(
                "/v3/connected_accounts/link",
                json={
                    "auth_config_id": auth_config_id,
                    "user_id": entity_id,
                    "redirect_uri": redirect_url,
                },
            )
            if not r.is_success:
                raise ComposioError(f"Failed to initiate connection for {toolkit}: HTTP {r.status_code} — {r.text[:300]}")
            data = r.json()
            return {
                "redirect_url": data.get("redirect_url"),
                "composio_connection_id": data.get("connected_account_id"),
            }

    async def get_connection_status(self, *, composio_connection_id: str) -> str:
        """Return normalized status: ``active | pending | failed | revoked``."""
        async with self._http() as client:
            r = await client.get(f"/v3/connected_accounts/{composio_connection_id}")
            if not r.is_success:
                raise ComposioError(f"Failed to fetch connection status for {composio_connection_id}: HTTP {r.status_code} — {r.text[:300]}")
            return _normalize_status(r.json().get("status"))

    async def get_account_display(self, *, composio_connection_id: str) -> str | None:
        """Best-effort email / display name from the connected-account metadata."""
        async with self._http() as client:
            r = await client.get(f"/v3/connected_accounts/{composio_connection_id}")
            if not r.is_success:
                return None
            return _extract_display(r.json())

    async def list_connections(self, *, entity_id: str) -> list[dict[str, Any]]:
        """List connections for *entity_id*. Each item: ``{toolkit, composio_connection_id, status}``."""
        async with self._http() as client:
            r = await client.get("/v3/connected_accounts", params={"user_id": entity_id})
            if not r.is_success:
                raise ComposioError(f"Failed to list connections for {entity_id}: HTTP {r.status_code} — {r.text[:300]}")
            result: list[dict[str, Any]] = []
            for item in r.json().get("items", []):
                slug = item.get("toolkit", {}).get("slug") or ""
                result.append(
                    {
                        "toolkit": slug.upper(),
                        "composio_connection_id": item.get("id"),
                        "status": _normalize_status(item.get("status")),
                    }
                )
            return result

    async def revoke_connection(self, *, composio_connection_id: str) -> None:
        """Delete the connected account on Composio's side."""
        async with self._http() as client:
            r = await client.delete(f"/v3/connected_accounts/{composio_connection_id}")
            if not r.is_success:
                raise ComposioError(f"Failed to revoke connection {composio_connection_id}: HTTP {r.status_code} — {r.text[:300]}")

    def get_mcp_url(self, *, toolkit: str, entity_id: str) -> str:
        """Return the Composio MCP Tool Router SSE URL for *toolkit* + *entity_id*."""
        return f"https://mcp.composio.dev/{toolkit.lower()}?apiKey={self._api_key}&entityId={entity_id}"


def _extract_display(data: dict[str, Any]) -> str | None:
    """Pull an email / display name out of a v3 connected-account response."""
    if not data:
        return None
    for key in ("data", "state", "metadata", "connection_params"):
        nested = data.get(key)
        if isinstance(nested, dict):
            for field in ("email", "user_email", "login", "name", "account"):
                if nested.get(field):
                    return str(nested[field])
    for field in ("email", "displayName", "name"):
        if data.get(field):
            return str(data[field])
    return None
