"""The gateway built the way production builds it, for Agent and Skill Studio
(Feature 006 Phase 3).

`create_app()` with its real lifespan, on a temporary config, database, home
directory and skills directory, with the custom-agent API switched on (the live
gateway runs with it on). The model is never real: tests that need one install
a fake through the `fake_model` fixture, at the one factory every runtime path
uses (`omniharness.models.create_chat_model`, as imported by each consumer).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from studio_app import configure_studio, fresh_app


@pytest.fixture
def studio(tmp_path, monkeypatch):
    import app.gateway.deps as deps
    from omniharness.config.app_config import reset_app_config
    from omniharness.config.extensions_config import reset_extensions_config

    configure_studio(tmp_path, monkeypatch)
    monkeypatch.setattr(deps, "_cached_local_provider", None)
    monkeypatch.setattr(deps, "_cached_repo", None)

    with TestClient(fresh_app()) as client:
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
