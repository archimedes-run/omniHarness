"""The run history through create_app() and its lifespan: opened under the
data dir at startup, read, retention set, and deleted only when confirmed."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

os.environ.setdefault("AUTH_JWT_SECRET", "test-secret-key-run-history-composition-32")
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
    config.setdefault("memory", {})["enabled"] = False
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config))
    ext = tmp_path / "extensions.json"
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
    with TestClient(create_app()) as client:
        client.post("/api/v1/auth/initialize", json={"email": "owner@example.com", "password": "Str0ng!Pass99"})
        if csrf := client.cookies.get("csrf_token"):
            client.headers["X-CSRF-Token"] = csrf
        yield client, home
    reset_app_config()
    reset_extensions_config()


def test_startup_opens_the_history_under_the_data_dir(gateway) -> None:
    client, home = gateway
    settings = client.get("/api/run-history/settings").json()
    assert settings == {"retention_days": 30, "runs": 0, "location": str((home / "run-history").resolve())}
    assert (home / "run-history" / "runs.sqlite3").exists()


def test_runs_are_read_and_retention_is_set(gateway) -> None:
    client, _ = gateway
    history = client.app.state.run_history
    old = history.record(kind="automation", source_id="brief", body={"reply": "old"}, status="completed", started_at=datetime.now(UTC) - timedelta(days=10))
    new = history.record(kind="automation", source_id="brief", body={"reply": "new"}, status="completed")

    listed = client.get("/api/run-history/runs", params={"kind": "automation", "source_id": "brief"}).json()
    assert [r["id"] for r in listed] == [new, old]
    assert client.get(f"/api/run-history/runs/{new}").json()["body"] == {"reply": "new"}

    resp = client.put("/api/run-history/settings", json={"retention_days": 7})
    assert resp.status_code == 200 and resp.json()["retention_days"] == 7
    assert resp.json()["runs"] == 1, "a shorter retention did not purge now"
    assert client.get(f"/api/run-history/runs/{old}").status_code == 404
    assert client.put("/api/run-history/settings", json={"retention_days": 0}).status_code == 422


def test_deleting_the_history_needs_confirmation(gateway) -> None:
    client, _ = gateway
    client.app.state.run_history.record(kind="automation", source_id="brief", body={}, status="completed")

    assert client.delete("/api/run-history/runs", params={"confirm": "yes"}).status_code == 422
    assert client.app.state.run_history.count() == 1
    resp = client.delete("/api/run-history/runs", params={"confirm": "delete-all"})
    assert resp.status_code == 200 and resp.json() == {"deleted": 1}
    assert client.get("/api/run-history/settings").json()["runs"] == 0


def test_the_routes_need_a_signed_in_user(gateway) -> None:
    client, _ = gateway
    client.cookies.clear()
    assert client.get("/api/run-history/settings").status_code == 401


@pytest.mark.asyncio
async def test_the_purge_job_purges_on_its_schedule(tmp_path) -> None:
    import asyncio

    from app.run_history.lifespan import purge_forever
    from app.run_history.store import RunHistory

    history = RunHistory(tmp_path)
    history.record(kind="automation", source_id="r", body={}, status="completed", started_at=datetime.now(UTC) - timedelta(days=40))
    task = asyncio.create_task(purge_forever(history, interval=0.01))
    for _ in range(100):
        await asyncio.sleep(0.02)
        if history.count() == 0:
            break
    task.cancel()
    assert history.count() == 0, "the scheduled purge never ran"
