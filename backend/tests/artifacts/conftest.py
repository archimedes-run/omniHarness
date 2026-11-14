"""The Artifact store (Spec 012, Slice 1), through `create_app()` and its real lifespan.

Same composition as tests/omni_apps/conftest.py: the tracked example config
plus test overrides, a temporary database and runtime home, the owner signed
in. `store` is a bare ArtifactStore on a temporary SQLite database for the
unit-level tests.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient

os.environ.setdefault("AUTH_JWT_SECRET", "test-secret-key-artifacts-composition-min-32")
EXAMPLE = Path(__file__).resolve().parents[3] / "config.example.yaml"


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    from app.gateway.auth.config import AuthConfig, set_auth_config
    from omniharness.config.app_config import reset_app_config
    from omniharness.config.extensions_config import reset_extensions_config

    config = yaml.safe_load(EXAMPLE.read_text())
    config["database"] = {"backend": "sqlite", "sqlite_dir": str(tmp_path / "data")}
    config["policy"] = {"enabled": True, "state_dir": str(tmp_path / "policy")}
    config["trigger_engine"] = {"enabled": False}
    config["agents_api"] = {"enabled": True}
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

    import app.gateway.artifacts_store.service as service
    import app.gateway.deps as deps
    from app.gateway.app import create_app

    monkeypatch.setattr(deps, "_cached_local_provider", None)
    monkeypatch.setattr(deps, "_cached_repo", None)
    monkeypatch.setattr(service, "_LAST_FULL_IMPORT", {})

    with TestClient(create_app()) as client:
        resp = client.post("/api/v1/auth/initialize", json={"email": "owner@example.com", "password": "Str0ng!Pass99"})
        assert resp.status_code in (200, 201), resp.text
        csrf = client.cookies.get("csrf_token")
        if csrf:
            client.headers["X-CSRF-Token"] = csrf
        me = client.get("/api/v1/auth/me").json()
        app = client.app
        yield SimpleNamespace(client=client, app=app, store=app.state.artifact_store, tmp=tmp_path, user_id=str(me.get("id") or me.get("user", {}).get("id")))
    reset_app_config()
    reset_extensions_config()


@pytest.fixture
def store(tmp_path, monkeypatch):
    from sqlalchemy import create_engine

    import omniharness.persistence.models  # noqa: F401  (registers every table)
    from app.gateway.artifacts_store.store import ArtifactStore
    from omniharness.persistence.base import Base

    monkeypatch.setenv("OMNI_HARNESS_HOME", str(tmp_path / "home"))
    engine = create_engine(f"sqlite:///{tmp_path / 'artifacts.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    yield ArtifactStore(engine)
    engine.dispose()
