"""Router-level tests for GET /api/mcp-studio/servers and /servers/{id}."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers import mcp_studio

_SERVER = {
    "id": "srv-1",
    "name": "My Server",
    "language": "Python",
    "description": "Test server",
    "status": "deployed",
    "detected_secrets": ["OPENAI_API_KEY"],
    "created_at": "2026-06-01T00:00:00+00:00",
    "updated_at": "2026-06-10T00:00:00+00:00",
}

_FLAG_ON = SimpleNamespace(mcp_builder=SimpleNamespace(enabled=True))
_FLAG_OFF = SimpleNamespace(mcp_builder=SimpleNamespace(enabled=False))


def _make_client(*, flag_enabled: bool = True, server: dict | None = _SERVER) -> TestClient:
    app = make_authed_test_app()
    app.state.config = SimpleNamespace(mcp_builder=SimpleNamespace(enabled=flag_enabled))
    repo = AsyncMock()
    repo.list_servers = AsyncMock(return_value=[server] if server else [])
    repo.get = AsyncMock(return_value=server)
    app.state.mcp_server_repo = repo
    app.include_router(mcp_studio.router)
    return TestClient(app)


def test_list_servers_returns_200():
    resp = _make_client().get("/api/mcp-studio/servers")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["servers"][0]["id"] == "srv-1"
    assert data["servers"][0]["name"] == "My Server"


def test_list_servers_passes_query_params():
    app = make_authed_test_app()
    app.state.config = _FLAG_ON
    repo = AsyncMock()
    repo.list_servers = AsyncMock(return_value=[])
    app.state.mcp_server_repo = repo
    app.include_router(mcp_studio.router)

    TestClient(app).get("/api/mcp-studio/servers?search=github&status=deployed&limit=10&offset=5")
    repo.list_servers.assert_awaited_once_with(search="github", status="deployed", limit=10, offset=5)


def test_list_servers_empty():
    resp = _make_client(server=None).get("/api/mcp-studio/servers")
    assert resp.status_code == 200
    assert resp.json() == {"servers": [], "total": 0}


def test_get_server_returns_200():
    resp = _make_client().get("/api/mcp-studio/servers/srv-1")
    assert resp.status_code == 200
    assert resp.json()["id"] == "srv-1"
    assert resp.json()["detected_secrets"] == ["OPENAI_API_KEY"]


def test_get_server_not_found():
    app = make_authed_test_app()
    app.state.config = _FLAG_ON
    repo = AsyncMock()
    repo.get = AsyncMock(return_value=None)
    app.state.mcp_server_repo = repo
    app.include_router(mcp_studio.router)

    resp = TestClient(app).get("/api/mcp-studio/servers/missing")
    assert resp.status_code == 404


def test_flag_disabled_returns_503():
    client = _make_client(flag_enabled=False)
    assert client.get("/api/mcp-studio/servers").status_code == 503
    assert client.get("/api/mcp-studio/servers/srv-1").status_code == 503


@pytest.mark.parametrize(
    "path",
    [
        "/api/mcp-studio/servers",
        "/api/mcp-studio/servers/srv-1",
    ],
)
def test_unauthenticated_returns_401(path: str):
    bare = FastAPI()
    bare.state.config = _FLAG_ON
    repo = AsyncMock()
    repo.list_servers = AsyncMock(return_value=[])
    repo.get = AsyncMock(return_value=_SERVER)
    bare.state.mcp_server_repo = repo
    bare.include_router(mcp_studio.router)

    resp = TestClient(bare, raise_server_exceptions=False).get(path)
    assert resp.status_code == 401


@pytest.mark.parametrize(
    "path",
    [
        "/api/mcp-studio/servers",
        "/api/mcp-studio/servers/srv-1",
    ],
)
def test_unauthenticated_with_flag_off_still_returns_401_not_503(path: str):
    # Auth check runs before the flag check (_check_flag is inside the handler
    # body, which only executes after @require_permission passes). This test
    # proves the order: unauthenticated callers never see 503.
    bare = FastAPI()
    bare.state.config = _FLAG_OFF
    repo = AsyncMock()
    repo.list_servers = AsyncMock(return_value=[])
    repo.get = AsyncMock(return_value=_SERVER)
    bare.state.mcp_server_repo = repo
    bare.include_router(mcp_studio.router)

    resp = TestClient(bare, raise_server_exceptions=False).get(path)
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Cross-user isolation
# ---------------------------------------------------------------------------
# These two tests prove the ownership contract at the router boundary.
# The invariant is: the router NEVER passes an explicit user_id to the repo.
# It calls repo.list_servers() / repo.get() with only the query-derived
# kwargs, so the repo always resolves ownership from user_id=AUTO
# (→ contextvar set by AuthMiddleware → per-request isolation).
# The SQL-level proof lives in test_mcp_server_repo.py.


def test_list_router_never_passes_user_id_to_repo():
    # Verify the router calls list_servers without a user_id kwarg, which
    # means the repo will use user_id=AUTO and read the contextvar.
    app = make_authed_test_app()
    app.state.config = _FLAG_ON
    repo = AsyncMock()
    repo.list_servers = AsyncMock(return_value=[])
    app.state.mcp_server_repo = repo
    app.include_router(mcp_studio.router)

    TestClient(app).get("/api/mcp-studio/servers?search=x&status=deployed")

    # If user_id were passed here, a rogue router could bypass owner isolation.
    call_kwargs = repo.list_servers.await_args.kwargs
    assert "user_id" not in call_kwargs, "Router must not pass user_id — isolation is the repo's job via AUTO"


def test_get_router_never_passes_user_id_to_repo():
    # Same invariant for the single-server endpoint.
    app = make_authed_test_app()
    app.state.config = _FLAG_ON
    repo = AsyncMock()
    repo.get = AsyncMock(return_value=_SERVER)
    app.state.mcp_server_repo = repo
    app.include_router(mcp_studio.router)

    TestClient(app).get("/api/mcp-studio/servers/srv-1")

    call_kwargs = repo.get.await_args.kwargs
    assert "user_id" not in call_kwargs, "Router must not pass user_id — isolation is the repo's job via AUTO"


def test_get_cross_user_returns_404():
    # The repo returns None when server_id exists but belongs to a different
    # owner (owner_id != resolved contextvar user). The router must surface
    # this as 404, not 403 or 200 with empty body — callers must not learn
    # whether the id exists at all.
    app = make_authed_test_app()
    app.state.config = _FLAG_ON
    repo = AsyncMock()
    repo.get = AsyncMock(return_value=None)  # simulates owner mismatch at SQL layer
    app.state.mcp_server_repo = repo
    app.include_router(mcp_studio.router)

    resp = TestClient(app).get("/api/mcp-studio/servers/belongs-to-another-user")
    assert resp.status_code == 404
