"""Feature 006 app pages (MCP Suite, Settings): the gateway as production
builds it. `gateway` is the ledger suite's fixture; `builder_gateway` is the
same, with the MCP builder switched on (its vault, repo and manager wired by
the real lifespan)."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient
from ledger.conftest import gateway  # noqa: F401  (the fixture, re-exported)
from mcp_build_helpers import built  # noqa: F401  (the fixture, re-exported)

EXAMPLE = Path(__file__).resolve().parents[3] / "config.example.yaml"


@pytest.fixture
def builder_gateway(tmp_path, monkeypatch):
    from cryptography.fernet import Fernet

    from app.gateway.auth.config import AuthConfig, set_auth_config
    from omniharness.config.app_config import reset_app_config
    from omniharness.config.extensions_config import reset_extensions_config

    os.environ.setdefault("AUTH_JWT_SECRET", "test-secret-key-ledger-composition-min-32")
    config = yaml.safe_load(EXAMPLE.read_text())
    config["database"] = {"backend": "sqlite", "sqlite_dir": str(tmp_path / "data")}
    config["policy"] = {"enabled": True, "state_dir": str(tmp_path / "policy")}
    config["trigger_engine"] = {"enabled": False}
    config.setdefault("memory", {})["enabled"] = False
    config["mcp_builder"] = {"enabled": True, "vault_key": Fernet.generate_key().decode()}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config))
    extensions = tmp_path / "extensions.json"
    extensions.write_text('{"mcpServers": {}, "skills": {}}')
    monkeypatch.setenv("OMNI_HARNESS_CONFIG_PATH", str(path))
    monkeypatch.setenv("OMNI_HARNESS_EXTENSIONS_CONFIG_PATH", str(extensions))
    monkeypatch.chdir(tmp_path)
    reset_app_config()
    reset_extensions_config()
    set_auth_config(AuthConfig(jwt_secret=os.environ["AUTH_JWT_SECRET"]))

    import app.gateway.deps as deps
    from app.gateway.app import create_app

    monkeypatch.setattr(deps, "_cached_local_provider", None)
    monkeypatch.setattr(deps, "_cached_repo", None)

    app = create_app()
    with TestClient(app) as client:
        resp = client.post("/api/v1/auth/initialize", json={"email": "owner@example.com", "password": "Str0ng!Pass99"})
        assert resp.status_code in (200, 201), resp.text
        csrf = client.cookies.get("csrf_token")
        if csrf:
            client.headers["X-CSRF-Token"] = csrf
        me = client.get("/api/v1/auth/me").json()
        assert app.state.mcp_server_manager is not None, "the lifespan did not wire the MCP builder"
        yield SimpleNamespace(client=client, app=app, user_id=str(me.get("id") or me.get("user", {}).get("id")), tmp=tmp_path, extensions=extensions)
    from omniharness.runtime.mcp.controller import set_mcp_build_controller

    # The lifespan registers a process-wide controller; leave none behind.
    set_mcp_build_controller(None)
    reset_app_config()
    reset_extensions_config()
