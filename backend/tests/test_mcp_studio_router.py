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
