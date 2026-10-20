"""A gateway through create_app() and its lifespan, with an isolated home,
config, .env and credential files, so no test ever loads a real secret."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

os.environ.setdefault("AUTH_JWT_SECRET", "test-secret-key-run-history-composition-32")
EXAMPLE = Path(__file__).resolve().parents[3] / "config.example.yaml"


@pytest.fixture(autouse=True)
def _isolated_known_secrets(tmp_path, monkeypatch):
    """The process-wide registry starts empty, and its loaders see only this
    test's files: never the developer's .env or OAuth credential files."""
    from omniharness.utils import known_secrets

    known_secrets.KNOWN_SECRETS.clear()
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("CLAUDE_CODE_CREDENTIALS_PATH", raising=False)
    monkeypatch.setenv("CODEX_AUTH_PATH", str(fake_home / ".codex" / "auth.json"))
    monkeypatch.setattr(known_secrets, "_dotenv_paths", lambda: [p for p in [tmp_path / ".env"] if p.exists()])
    monkeypatch.setattr(known_secrets, "environ_secrets", lambda environ=None: [])
    yield
    known_secrets.KNOWN_SECRETS.clear()


@pytest.fixture
def make_gateway(tmp_path, monkeypatch) -> Callable:
    """`with make_gateway(tweak) as (client, home): ...`; `tweak(config)` edits
    the config dict before it is written."""
    from contextlib import contextmanager

    @contextmanager
    def _make(tweak: Callable[[dict], None] | None = None):
        from app.gateway.auth.config import AuthConfig, set_auth_config
        from omniharness.config.app_config import reset_app_config
        from omniharness.config.extensions_config import reset_extensions_config

        config = yaml.safe_load(EXAMPLE.read_text())
        config["database"] = {"backend": "sqlite", "sqlite_dir": str(tmp_path / "data")}
        config["policy"] = {"enabled": True, "state_dir": str(tmp_path / "policy")}
        config["trigger_engine"] = {"enabled": False}
        config.setdefault("memory", {})["enabled"] = False
        if tweak:
            tweak(config)
        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump(config))
        ext = tmp_path / "extensions.json"
        if not ext.exists():
            ext.write_text('{"mcpServers": {}, "skills": {}}')
        home = tmp_path / "home"
        monkeypatch.setenv("OMNI_HARNESS_HOME", str(home))
        monkeypatch.setenv("OMNI_HARNESS_CONFIG_PATH", str(path))
        monkeypatch.setenv("OMNI_HARNESS_EXTENSIONS_CONFIG_PATH", str(ext))
        monkeypatch.chdir(tmp_path)
        reset_app_config()
        reset_extensions_config()
        set_auth_config(AuthConfig(jwt_secret=os.environ["AUTH_JWT_SECRET"]))
        import app.gateway.deps as deps
        from app.gateway.app import create_app

        monkeypatch.setattr(deps, "_cached_local_provider", None)
        monkeypatch.setattr(deps, "_cached_repo", None)
        try:
            with TestClient(create_app()) as client:
                r = client.post("/api/v1/auth/initialize", json={"email": "owner@example.com", "password": "Str0ng!Pass99"})
                if r.status_code >= 400:
                    client.post("/api/v1/auth/login/local", data={"username": "owner@example.com", "password": "Str0ng!Pass99"})
                if csrf := client.cookies.get("csrf_token"):
                    client.headers["X-CSRF-Token"] = csrf
                yield client, home
        finally:
            reset_app_config()
            reset_extensions_config()

    return _make


@pytest.fixture
def gateway(make_gateway):
    with make_gateway() as pair:
        yield pair
