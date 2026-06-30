"""Router-level + repository tests for the Composio 1-click connector.

The composio-core SDK is never imported at module level here — the
``ComposioClient`` is always a ``MagicMock``/``AsyncMock`` so these tests pass
without composio-core installed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers import composio

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_repo(*, connections: list[dict] | None = None, by_toolkit: dict | None = None) -> AsyncMock:
    repo = AsyncMock()
    repo.list_by_user = AsyncMock(return_value=connections or [])
    repo.get_by_user_toolkit = AsyncMock(return_value=(by_toolkit or {}).get("value"))
    repo.upsert = AsyncMock(return_value={})
    repo.mark_active = AsyncMock(return_value={})
    repo.mark_revoked = AsyncMock(return_value={})
    return repo


def _make_client_app(*, repo: AsyncMock, client: MagicMock | None = None) -> TestClient:
    app = make_authed_test_app()
    app.state.composio_connection_repo = repo
    app.state.composio_client = client if client is not None else MagicMock()
    app.include_router(composio.router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1 + 2. Catalog
# ---------------------------------------------------------------------------


def test_catalog_returns_8_toolkits_with_not_connected_when_no_connections():
    repo = _make_repo(connections=[])
    resp = _make_client_app(repo=repo).get("/api/composio/catalog")
    assert resp.status_code == 200
    toolkits = resp.json()["toolkits"]
    assert len(toolkits) == 8
    assert {t["slug"] for t in toolkits} == {"GMAIL", "GOOGLECALENDAR", "GOOGLEDRIVE", "SLACK", "NOTION", "GITHUB", "LINEAR", "OUTLOOK"}
    assert all(t["status"] == "not_connected" for t in toolkits)


def test_catalog_merges_active_connection_into_status():
    repo = _make_repo(
        connections=[{"toolkit": "GMAIL", "status": "active", "account_display": "me@example.com"}],
    )
    resp = _make_client_app(repo=repo).get("/api/composio/catalog")
    assert resp.status_code == 200
    by_slug = {t["slug"]: t for t in resp.json()["toolkits"]}
    assert by_slug["GMAIL"]["status"] == "connected"
    assert by_slug["GMAIL"]["account_display"] == "me@example.com"
    assert by_slug["SLACK"]["status"] == "not_connected"


# ---------------------------------------------------------------------------
# 3 + 4. Initiate
# ---------------------------------------------------------------------------


def test_initiate_connection_creates_pending_row():
    repo = _make_repo(by_toolkit={"value": None})
    client = MagicMock()
    client.initiate_connection = AsyncMock(return_value={"redirect_url": "https://oauth.example/go", "composio_connection_id": "conn-1"})
    resp = _make_client_app(repo=repo, client=client).post(
        "/api/composio/connections/initiate",
        json={"toolkit": "GMAIL", "redirect_url": "http://localhost:3000/cb"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["composio_redirect_url"] == "https://oauth.example/go"
    assert body["connection_id"] == "conn-1"
    repo.upsert.assert_awaited_once()
    kwargs = repo.upsert.await_args.kwargs
    assert kwargs["toolkit"] == "GMAIL"
    assert kwargs["status"] == "pending"
    assert kwargs["composio_connection_id"] == "conn-1"


def test_initiate_connection_idempotent_when_already_active():
    repo = _make_repo(by_toolkit={"value": {"toolkit": "GMAIL", "status": "active"}})
    client = MagicMock()
    client.initiate_connection = AsyncMock()
    resp = _make_client_app(repo=repo, client=client).post(
        "/api/composio/connections/initiate",
        json={"toolkit": "GMAIL", "redirect_url": "http://localhost:3000/cb"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "already_connected"}
    client.initiate_connection.assert_not_called()
    repo.upsert.assert_not_called()


def test_initiate_rejects_unknown_toolkit():
    repo = _make_repo(by_toolkit={"value": None})
    resp = _make_client_app(repo=repo).post(
        "/api/composio/connections/initiate",
        json={"toolkit": "NOTREAL", "redirect_url": "http://localhost:3000/cb"},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 5 + 6. Callback
# ---------------------------------------------------------------------------


def test_callback_marks_active_when_composio_returns_active():
    repo = _make_repo()
    client = MagicMock()
    client.get_connection_status = AsyncMock(return_value="active")
    client.get_account_display = AsyncMock(return_value="me@example.com")
    client.get_mcp_url = MagicMock(return_value="https://mcp.composio.dev/gmail?apiKey=x&entityId=y")
    with patch.object(composio, "_write_mcp_entry") as write_entry:
        resp = _make_client_app(repo=repo, client=client).get("/api/composio/connections/callback?connection_id=conn-1&toolkit=GMAIL")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "active"
    assert body["toolkit"] == "GMAIL"
    assert body["account_display"] == "me@example.com"
    write_entry.assert_called_once()
    # upsert called with active status
    assert repo.upsert.await_args.kwargs["status"] == "active"


def test_callback_returns_pending_when_composio_returns_pending():
    repo = _make_repo()
    client = MagicMock()
    client.get_connection_status = AsyncMock(return_value="pending")
    with patch.object(composio, "_write_mcp_entry") as write_entry:
        resp = _make_client_app(repo=repo, client=client).get("/api/composio/connections/callback?connection_id=conn-1&toolkit=GMAIL")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    assert body["account_display"] is None
    write_entry.assert_not_called()


# ---------------------------------------------------------------------------
# 7 + 8. Disconnect
# ---------------------------------------------------------------------------


def test_disconnect_calls_revoke_and_marks_revoked():
    repo = _make_repo(by_toolkit={"value": {"toolkit": "GMAIL", "status": "active", "composio_connection_id": "conn-1"}})
    client = MagicMock()
    client.revoke_connection = AsyncMock()
    with patch.object(composio, "_remove_mcp_entry") as remove_entry:
        resp = _make_client_app(repo=repo, client=client).delete("/api/composio/connections/GMAIL")
    assert resp.status_code == 204
    client.revoke_connection.assert_awaited_once_with(composio_connection_id="conn-1")
    repo.mark_revoked.assert_awaited_once()
    assert repo.mark_revoked.await_args.kwargs["toolkit"] == "GMAIL"
    remove_entry.assert_called_once()


def test_disconnect_returns_404_when_no_connection():
    repo = _make_repo(by_toolkit={"value": None})
    resp = _make_client_app(repo=repo).delete("/api/composio/connections/GMAIL")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 9 + 10. Auth
# ---------------------------------------------------------------------------


def test_catalog_requires_auth():
    app = FastAPI()  # no stub auth middleware
    app.state.composio_connection_repo = _make_repo()
    app.state.composio_client = MagicMock()
    app.include_router(composio.router)
    resp = TestClient(app).get("/api/composio/catalog")
    assert resp.status_code == 401


def test_initiate_requires_auth():
    app = FastAPI()
    app.state.composio_connection_repo = _make_repo(by_toolkit={"value": None})
    app.state.composio_client = MagicMock()
    app.include_router(composio.router)
    resp = TestClient(app).post(
        "/api/composio/connections/initiate",
        json={"toolkit": "GMAIL", "redirect_url": "http://localhost:3000/cb"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 11. Repository upsert behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connection_repo_upsert_creates_and_updates():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from omniharness.persistence.composio_connections import ComposioConnectionRepository
    from omniharness.persistence.composio_connections.model import ComposioConnectionRow

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        # Create only this table to avoid cross-table FK resolution from other
        # ORM models that aren't imported in this isolated test.
        await conn.run_sync(ComposioConnectionRow.metadata.create_all, tables=[ComposioConnectionRow.__table__])
    sf = async_sessionmaker(engine, expire_on_commit=False)
    repo = ComposioConnectionRepository(sf)

    created = await repo.upsert(user_id="u1", toolkit="GMAIL", composio_connection_id="c1", status="pending")
    assert created["status"] == "pending"
    assert created["composio_connection_id"] == "c1"

    updated = await repo.mark_active(user_id="u1", toolkit="GMAIL", account_display="me@example.com")
    assert updated is not None
    assert updated["status"] == "active"
    assert updated["account_display"] == "me@example.com"
    assert updated["id"] == created["id"]  # same row

    # Second upsert with status only keeps existing connection id
    re_up = await repo.upsert(user_id="u1", toolkit="GMAIL", status="failed")
    assert re_up["status"] == "failed"
    assert re_up["composio_connection_id"] == "c1"

    listed = await repo.list_by_user(user_id="u1")
    assert len(listed) == 1

    revoked = await repo.mark_revoked(user_id="u1", toolkit="GMAIL")
    assert revoked["status"] == "revoked"

    await engine.dispose()


# ---------------------------------------------------------------------------
# 12. ComposioClient raises ComposioError on HTTP failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_composio_client_raises_on_http_error():
    from app.gateway.composio_client import ComposioClient, ComposioError

    client = ComposioClient(api_key="csk_test")

    empty_resp = MagicMock(status_code=200, is_success=True)
    empty_resp.json.return_value = {"items": []}

    error_resp = MagicMock(status_code=500, is_success=False, text="server error")

    mock_http_client = AsyncMock()
    mock_http_client.get.return_value = empty_resp
    mock_http_client.post.return_value = error_resp

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_http_client)
    cm.__aexit__ = AsyncMock(return_value=False)

    with patch.object(client, "_http", return_value=cm):
        with pytest.raises(ComposioError, match="Failed to create auth config"):
            await client.initiate_connection(entity_id="u1", toolkit="GMAIL", redirect_url="http://x")


@pytest.mark.asyncio
async def test_composio_client_get_mcp_url_format():
    from app.gateway.composio_client import ComposioClient

    client = ComposioClient(api_key="csk_test")
    url = client.get_mcp_url(toolkit="GMAIL", entity_id="user-123")
    assert url == "https://mcp.composio.dev/gmail?apiKey=csk_test&entityId=user-123"
