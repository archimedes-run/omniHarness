"""Thin async wrapper around the composio-core SDK.

All blocking SDK calls are dispatched to a worker thread via
``asyncio.to_thread`` so they never block the event loop. SDK exceptions are
re-raised as :class:`ComposioError` so routers can map them to HTTP 502.

The COMPOSIO_API_KEY is read by the caller from ``os.environ`` and passed in;
it is never logged or returned in any API response.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Module-level SDK symbols. Imported lazily-at-import so unit tests can run
# without composio-core installed (the names fall back to ``None``) and so
# tests can ``patch("app.gateway.composio_client.ComposioToolSet", ...)``.
try:  # pragma: no cover - exercised only when composio-core is present
    from composio import App, ComposioToolSet
except Exception:  # pragma: no cover
    App = None  # type: ignore[assignment]
    ComposioToolSet = None  # type: ignore[assignment]

# Map of toolkit slug (uppercase, as stored in DB / config) → composio App enum
# attribute name. Using getattr(App, name) keeps the import lazy so unit tests
# can run without composio-core installed.
_APP_ATTR_BY_SLUG: dict[str, str] = {
    "GMAIL": "GMAIL",
    "GOOGLECALENDAR": "GOOGLECALENDAR",
    "GOOGLEDRIVE": "GOOGLEDRIVE",
    "SLACK": "SLACK",
    "NOTION": "NOTION",
    "GITHUB": "GITHUB",
    "LINEAR": "LINEAR",
    "OUTLOOK": "OUTLOOK",
}


class ComposioError(RuntimeError):
    """Raised when the underlying Composio SDK call fails."""


def _normalize_status(raw: Any) -> str:
    """Normalize a Composio status value to our lowercase vocabulary.

    Composio returns values like ``"ACTIVE"``, ``"PENDING"``, ``"FAILED"``,
    ``"INITIATED"``, ``"EXPIRED"``. We collapse them to one of
    ``active | pending | failed | revoked``.
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
    # failed, error, expired, etc.
    return "failed"


class ComposioClient:
    """Async facade over :class:`composio.ComposioToolSet`."""

    def __init__(self, api_key: str):
        if not api_key:
            raise RuntimeError("COMPOSIO_API_KEY is required to construct ComposioClient. Set it in the environment (see .env.example).")
        self._api_key = api_key

    # -- internal helpers ---------------------------------------------------

    def _toolset(self, entity_id: str | None = None):
        """Construct a ComposioToolSet bound to *entity_id*."""
        if ComposioToolSet is None:
            raise ComposioError("composio-core is not installed. Run `uv add composio-core` in the harness package.")
        kwargs: dict[str, Any] = {"api_key": self._api_key}
        if entity_id is not None:
            kwargs["entity_id"] = entity_id
        return ComposioToolSet(**kwargs)

    @staticmethod
    def _app_enum(toolkit: str):
        """Return the composio ``App`` enum member for *toolkit*."""
        if App is None:
            raise ComposioError("composio-core is not installed.")
        attr = _APP_ATTR_BY_SLUG.get(toolkit.upper())
        if attr is None:
            raise ComposioError(f"Unsupported toolkit: {toolkit}")
        try:
            return getattr(App, attr)
        except AttributeError as exc:
            raise ComposioError(f"composio App enum has no member {attr!r}") from exc

    # -- public API ---------------------------------------------------------

    async def initiate_connection(self, *, entity_id: str, toolkit: str, redirect_url: str) -> dict[str, Any]:
        """Start an OAuth flow. Returns ``{"redirect_url", "composio_connection_id"}``."""

        def _call() -> dict[str, Any]:
            toolset = self._toolset(entity_id=entity_id)
            app = self._app_enum(toolkit)
            req = toolset.initiate_connection(app=app, redirect_url=redirect_url)
            redirect = getattr(req, "redirectUrl", None) or getattr(req, "redirect_url", None)
            conn_id = getattr(req, "connectedAccountId", None) or getattr(req, "connected_account_id", None)
            return {"redirect_url": redirect, "composio_connection_id": conn_id}

        try:
            return await _to_thread(_call)
        except ComposioError:
            raise
        except Exception as exc:
            raise ComposioError(f"Failed to initiate connection for {toolkit}: {exc}") from exc

    async def get_connection_status(self, *, composio_connection_id: str) -> str:
        """Return normalized status: ``active | pending | failed | revoked``."""

        def _call() -> str:
            toolset = self._toolset()
            account = toolset.get_connected_account(connected_account_id=composio_connection_id)
            return _normalize_status(getattr(account, "status", None))

        try:
            return await _to_thread(_call)
        except Exception as exc:
            raise ComposioError(f"Failed to fetch connection status: {exc}") from exc

    async def get_account_display(self, *, composio_connection_id: str) -> str | None:
        """Best-effort email / display name from the connected-account metadata."""

        def _call() -> str | None:
            toolset = self._toolset()
            account = toolset.get_connected_account(connected_account_id=composio_connection_id)
            return _extract_display(account)

        try:
            return await _to_thread(_call)
        except Exception as exc:
            raise ComposioError(f"Failed to fetch account display: {exc}") from exc

    async def list_connections(self, *, entity_id: str) -> list[dict[str, Any]]:
        """List connections for *entity_id*. Each: ``{toolkit, composio_connection_id, status}``."""

        def _call() -> list[dict[str, Any]]:
            toolset = self._toolset(entity_id=entity_id)
            accounts = toolset.get_connected_accounts(entity_id=entity_id)
            result: list[dict[str, Any]] = []
            for acc in accounts or []:
                toolkit = getattr(acc, "appName", None) or getattr(acc, "appUniqueId", None) or getattr(acc, "app_name", None) or ""
                conn_id = getattr(acc, "id", None) or getattr(acc, "connectedAccountId", None)
                result.append(
                    {
                        "toolkit": str(toolkit).upper(),
                        "composio_connection_id": conn_id,
                        "status": _normalize_status(getattr(acc, "status", None)),
                    }
                )
            return result

        try:
            return await _to_thread(_call)
        except Exception as exc:
            raise ComposioError(f"Failed to list connections: {exc}") from exc

    async def revoke_connection(self, *, composio_connection_id: str) -> None:
        """Revoke / delete the connected account."""

        def _call() -> None:
            toolset = self._toolset()
            toolset.delete_connected_account(connected_account_id=composio_connection_id)

        try:
            await _to_thread(_call)
        except Exception as exc:
            raise ComposioError(f"Failed to revoke connection: {exc}") from exc

    def get_mcp_url(self, *, toolkit: str, entity_id: str) -> str:
        """Return the Composio MCP Tool Router SSE URL for *toolkit* + *entity_id*."""
        return f"https://mcp.composio.dev/{toolkit.lower()}?apiKey={self._api_key}&entityId={entity_id}"


def _extract_display(account: Any) -> str | None:
    """Pull an email / display name out of a connected-account object."""
    if account is None:
        return None
    # Direct attributes first.
    for attr in ("email", "account_display", "displayName", "name"):
        val = getattr(account, attr, None)
        if val:
            return str(val)
    # Then nested metadata / connectionParams.
    for attr in ("connectionParams", "connection_params", "meta", "metadata"):
        params = getattr(account, attr, None)
        if isinstance(params, dict):
            for key in ("email", "user_email", "login", "name", "account"):
                if params.get(key):
                    return str(params[key])
    return None


async def _to_thread(fn):
    """Run a blocking callable in a worker thread."""
    return await asyncio.to_thread(fn)
