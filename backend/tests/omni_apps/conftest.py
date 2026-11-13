"""The Apps platform (Spec 011), through `create_app()` and its real lifespan.

Same composition as tests/home/conftest.py: a temporary config and database,
the tracked example config plus test overrides, and the owner signed in.
Composio's HTTP is stood in for (no real account is ever touched); the
runtime home is a temporary directory, so app versions and bundles land there.
"""

from __future__ import annotations

import os
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

os.environ.setdefault("AUTH_JWT_SECRET", "test-secret-key-apps-composition-min-32xx")
EXAMPLE = Path(__file__).resolve().parents[3] / "config.example.yaml"

from _apps_helpers import FILES, FakeComposio, manifest  # noqa: E402


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    from app.gateway.auth.config import AuthConfig, set_auth_config
    from omniharness.config.app_config import reset_app_config
    from omniharness.config.extensions_config import reset_extensions_config

    config = yaml.safe_load(EXAMPLE.read_text())
    config["database"] = {"backend": "sqlite", "sqlite_dir": str(tmp_path / "data")}
    config["policy"] = {"enabled": True, "state_dir": str(tmp_path / "policy")}
    config["trigger_engine"] = {"enabled": False}
    config.setdefault("memory", {})["enabled"] = False
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config))
    extensions = tmp_path / "extensions.json"
    extensions.write_text('{"mcpServers": {}, "skills": {}}')
    monkeypatch.setenv("OMNI_HARNESS_CONFIG_PATH", str(path))
    monkeypatch.setenv("OMNI_HARNESS_EXTENSIONS_CONFIG_PATH", str(extensions))
    monkeypatch.setenv("OMNI_HARNESS_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    reset_app_config()
    reset_extensions_config()
    set_auth_config(AuthConfig(jwt_secret=os.environ["AUTH_JWT_SECRET"]))

    import app.gateway.deps as deps
    from app.gateway.app import create_app

    monkeypatch.setattr(deps, "_cached_local_provider", None)
    monkeypatch.setattr(deps, "_cached_repo", None)

    with TestClient(create_app()) as client:
        resp = client.post("/api/v1/auth/initialize", json={"email": "owner@example.com", "password": "Str0ng!Pass99"})
        assert resp.status_code in (200, 201), resp.text
        csrf = client.cookies.get("csrf_token")
        if csrf:
            client.headers["X-CSRF-Token"] = csrf
        me = client.get("/api/v1/auth/me").json()
        yield SimpleNamespace(client=client, app=client.app, tmp=tmp_path, user_id=str(me.get("id") or me.get("user", {}).get("id")))
    reset_app_config()
    reset_extensions_config()


@pytest.fixture
def composio(gateway, monkeypatch):
    from app.gateway.composio_client import ComposioClient

    fake = FakeComposio()
    client = ComposioClient("test-key")
    client._transport = httpx.MockTransport(fake)
    monkeypatch.setattr(gateway.app.state, "composio_client", client)
    repo = gateway.app.state.composio_connection_repo

    def connect(toolkit: str, status: str = "active") -> None:
        gateway.client.portal.call(partial(repo.upsert, user_id=gateway.user_id, toolkit=toolkit, composio_connection_id=f"ca_{toolkit.lower()}", status=status))

    return SimpleNamespace(fake=fake, connect=connect)


@pytest.fixture
def apps(gateway):
    """Register (as the gateway does after a verified job) and approve (as the button does)."""
    from app.gateway.apps.registry import register_app

    repo = gateway.app.state.app_repo

    def register(m: dict | None = None, *, files: dict | None = None, app_id: str | None = None, owner: str | None = None, thread_id: str | None = "thread-1", origin=("user", None)):
        return gateway.client.portal.call(partial(register_app, gateway.app.state, owner_id=owner or gateway.user_id, manifest=m or manifest(), files=files or FILES, app_id=app_id, thread_id=thread_id, origin=origin))

    def approve(app_id: str):
        card = gateway.client.get(f"/api/apps/{app_id}/approval").json()
        resp = gateway.client.post(f"/api/apps/{app_id}/approve", json={"manifest_hash": card["manifest_hash"], "card_id": card["id"]})
        assert resp.status_code == 200, resp.text
        return card

    def call(fn, **kwargs):
        return gateway.client.portal.call(partial(fn, **kwargs))

    return SimpleNamespace(register=register, approve=approve, repo=repo, call=call)
