"""The gateway built the way production builds it, with a rule file of its own.

`create_app()` and its real lifespan (as tests/ledger/conftest.py), with
trigger_engine.rules_path pointing at a temporary rule file and state_dir at a
temporary audit log: the Automations panel's reads and writes go through the
routers startup mounts, behind auth and CSRF.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient

os.environ.setdefault("AUTH_JWT_SECRET", "test-secret-key-automations-composition-32")
EXAMPLE = Path(__file__).resolve().parents[3] / "config.example.yaml"

RULES = {
    "_comment": ["kept as written"],
    "quiet_hours": {"start": "22:00", "end": "07:00", "timezone": "America/New_York", "enabled": True},
    "rules": [
        {"id": "morning-brief", "name": "Morning brief", "type": "cron", "enabled": True, "match": {"schedule": "45 8 * * 1-5", "timezone": "America/New_York"}, "prompt": "Brief me as of {scheduled_at}.", "destination": "auto"},
        {"id": "blocked-session", "type": "watcher", "enabled": True, "match": {"event": "waiting-on-user"}, "prompt": "{project} is waiting: {last_message}", "destination": "auto"},
    ],
}


@pytest.fixture
def make_gateway(tmp_path, monkeypatch):
    from app.gateway.auth.config import AuthConfig, set_auth_config
    from omniharness.config.app_config import reset_app_config
    from omniharness.config.extensions_config import reset_extensions_config

    clients = []

    def build(*, engine_enabled: bool = False, audit: list[dict] | None = None):
        rules = tmp_path / "rules.json"
        rules.write_text(json.dumps(RULES, indent=2))
        state = tmp_path / "triggers"
        state.mkdir(exist_ok=True)
        if audit:
            (state / "audit.jsonl").write_text("".join(json.dumps(e) + "\n" for e in audit))
        config = yaml.safe_load(EXAMPLE.read_text())
        config["database"] = {"backend": "sqlite", "sqlite_dir": str(tmp_path / "data")}
        config["policy"] = {"enabled": True, "state_dir": str(tmp_path / "policy")}
        config["trigger_engine"] = {"enabled": engine_enabled, "rules_path": str(rules), "state_dir": str(state)}
        config.setdefault("memory", {})["enabled"] = False
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
        client = TestClient(create_app())
        client.__enter__()
        clients.append(client)
        resp = client.post("/api/v1/auth/initialize", json={"email": "owner@example.com", "password": "Str0ng!Pass99"})
        assert resp.status_code in (200, 201), resp.text
        csrf = client.cookies.get("csrf_token")
        if csrf:
            client.headers["X-CSRF-Token"] = csrf
        return SimpleNamespace(client=client, rules=rules, state=state)

    yield build
    for client in clients:
        client.__exit__(None, None, None)
    reset_app_config()
    reset_extensions_config()
