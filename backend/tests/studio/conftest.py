"""The gateway built the way production builds it, for Agent and Skill Studio
(Feature 006 Phase 3).

`create_app()` with its real lifespan, on a temporary config, database, home
directory and skills directory, with the custom-agent API switched on (the live
gateway runs with it on). The model is never real: tests that need one install
a fake through the `fake_model` fixture, at the one factory every runtime path
uses (`omniharness.models.create_chat_model`, as imported by each consumer).
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient

os.environ.setdefault("AUTH_JWT_SECRET", "test-secret-key-studio-composition-min-32")
EXAMPLE = Path(__file__).resolve().parents[3] / "config.example.yaml"


@pytest.fixture
def studio(tmp_path, monkeypatch):
    from app.gateway.auth.config import AuthConfig, set_auth_config
    from omniharness.config.app_config import reset_app_config
    from omniharness.config.extensions_config import reset_extensions_config

    config = yaml.safe_load(EXAMPLE.read_text())
    config["database"] = {"backend": "sqlite", "sqlite_dir": str(tmp_path / "data")}
    config["policy"] = {"enabled": True, "state_dir": str(tmp_path / "policy")}
    config["trigger_engine"] = {"enabled": False, "rules_path": str(tmp_path / "rules.json"), "state_dir": str(tmp_path / "triggers")}
    config["agents_api"] = {"enabled": True}
    config.setdefault("memory", {})["enabled"] = False
    config.setdefault("skills", {})["path"] = str(tmp_path / "skills")
    (tmp_path / "skills" / "public").mkdir(parents=True)
    (tmp_path / "skills" / "custom").mkdir(parents=True)
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
        yield SimpleNamespace(client=client, user_id=str(me.get("id") or me.get("user", {}).get("id")), tmp=tmp_path)
    reset_app_config()
    reset_extensions_config()


@pytest.fixture
def allow_scans(monkeypatch):
    """The skill security scan calls a model; these tests have none. Allow."""
    import app.gateway.routers.skills as skills_router
    from omniharness.skills.security_scanner import ScanResult

    async def allow(content, *, executable=False, location="", app_config=None):
        return ScanResult("allow", "test")

    monkeypatch.setattr(skills_router, "scan_skill_content", allow)


@pytest.fixture
def fake_model(monkeypatch):
    """Replace the model factory the drafts router uses. `replies` is the list
    of texts it answers with, in order; `calls` records each model asked for."""
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage

    import app.gateway.routers.drafts as drafts

    state = SimpleNamespace(replies=[], calls=[])

    def factory(name=None, thinking_enabled=False, app_config=None, **kwargs):
        state.calls.append(name)
        return GenericFakeChatModel(messages=iter([AIMessage(content=state.replies.pop(0))]))

    monkeypatch.setattr(drafts, "create_chat_model", factory)
    return state
