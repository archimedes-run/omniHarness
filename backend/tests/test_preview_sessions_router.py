import uuid
from typing import Any

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

import app.gateway.preview_sessions as preview_sessions
from app.gateway.auth.models import User
from app.gateway.preview_sessions import PreviewSessionManager
from app.gateway.routers import previews as previews_router
from omniharness.config.paths import Paths


class _FakeAioSandbox:
    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, Any]] = {}

    def create_shell_session(
        self,
        *,
        session_id: str,
        exec_dir: str,
        no_change_timeout: int = 0,
        preserve_symlinks: bool = True,
    ) -> str:
        self.sessions.setdefault(
            session_id,
            {
                "status": "terminated",
                "output": "",
                "exit_code": None,
                "exec_dir": exec_dir,
            },
        )
        return session_id

    def start_shell_command(
        self,
        *,
        session_id: str,
        command: str,
        exec_dir: str,
        no_change_timeout: int = 0,
        hard_timeout: float | None = None,
    ) -> dict[str, Any]:
        self.sessions[session_id] = {
            "status": "running",
            "output": (f"$ {command}\nready on http://127.0.0.1:3000\npreview server booted\n"),
            "exit_code": None,
            "exec_dir": exec_dir,
            "command": command,
        }
        return {
            "session_id": session_id,
            "status": "running",
            "output": self.sessions[session_id]["output"],
            "exit_code": None,
            "command": command,
        }

    def view_shell_session(self, session_id: str) -> dict[str, Any]:
        session = self.sessions[session_id]
        return {
            "session_id": session_id,
            "status": session["status"],
            "output": session["output"],
            "exit_code": session["exit_code"],
            "command": session.get("command"),
        }

    def kill_shell_session(self, session_id: str) -> None:
        session = self.sessions[session_id]
        session["status"] = "terminated"
        session["exit_code"] = 0
        session["output"] += "\npreview stopped\n"

    def cleanup_shell_session(self, session_id: str) -> None:
        self.sessions.pop(session_id, None)

    def fetch_local_url(
        self,
        *,
        port: int,
        path: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        timeout: int = 30,
    ) -> dict[str, Any]:
        if path.startswith("/assets/app.js"):
            return {
                "status": 200,
                "headers": {"content-type": "application/javascript"},
                "body": b"console.log('preview-js-ok');",
            }
        return {
            "status": 200,
            "headers": {"content-type": "text/html; charset=utf-8"},
            "body": (b'<!doctype html><html><head></head><body><script src="/assets/app.js"></script>preview-ok</body></html>'),
        }


class _FakeAioSandboxProvider:
    def __init__(self, sandbox: _FakeAioSandbox) -> None:
        self._sandbox = sandbox

    def acquire(self, thread_id: str | None = None) -> str:
        return "sandbox-1"

    def get(self, sandbox_id: str):
        return self._sandbox


def _make_user(email: str, raw_id: str) -> User:
    return User(
        email=email,
        password_hash="x",
        system_role="user",
        id=uuid.UUID(raw_id),
    )


def _make_preview_app(*, user: User, manager: PreviewSessionManager):
    app = make_authed_test_app(user_factory=lambda: user)
    app.state.preview_session_manager = manager
    app.include_router(previews_router.router)
    return app


@pytest.fixture()
def preview_test_context(tmp_path, monkeypatch):
    user = _make_user("preview@example.com", "00000000-0000-4000-8000-000000000001")
    thread_id = "thread-1"
    paths = Paths(tmp_path)
    paths.ensure_thread_dirs(thread_id, user_id=str(user.id))
    workspace_dir = paths.sandbox_work_dir(thread_id, user_id=str(user.id)) / "dynamic-app"
    workspace_dir.mkdir(parents=True, exist_ok=True)

    sandbox = _FakeAioSandbox()
    provider = _FakeAioSandboxProvider(sandbox)
    manager = PreviewSessionManager(idle_timeout_seconds=3600)

    monkeypatch.setattr(preview_sessions, "get_paths", lambda: paths)
    monkeypatch.setattr(preview_sessions, "get_sandbox_provider", lambda: provider)
    monkeypatch.setattr(preview_sessions, "AioSandboxProvider", _FakeAioSandboxProvider)
    monkeypatch.setattr(preview_sessions, "AioSandbox", _FakeAioSandbox)

    return {
        "user": user,
        "thread_id": thread_id,
        "paths": paths,
        "sandbox": sandbox,
        "provider": provider,
        "manager": manager,
    }


def test_create_preview_session(preview_test_context) -> None:
    app = _make_preview_app(
        user=preview_test_context["user"],
        manager=preview_test_context["manager"],
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/threads/thread-1/previews",
            json={
                "artifact_id": "dynamic-app",
                "root_path": "/mnt/user-data/workspace/dynamic-app",
                "command": "npm run dev -- --hostname 0.0.0.0",
                "port": 3000,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["artifact_id"] == "dynamic-app"
    assert body["status"] == "running"
    assert body["proxy_url"].endswith(f"/api/threads/thread-1/previews/{body['id']}/proxy")


def test_create_preview_session_rejects_root_outside_workspace(preview_test_context) -> None:
    app = _make_preview_app(
        user=preview_test_context["user"],
        manager=preview_test_context["manager"],
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/threads/thread-1/previews",
            json={
                "artifact_id": "dynamic-app",
                "root_path": "/mnt/user-data/outputs/dynamic-app",
                "command": "npm run dev -- --hostname 0.0.0.0",
                "port": 3000,
            },
        )

    assert response.status_code == 422
    assert "workspace" in response.json()["detail"]


def test_preview_proxy_reaches_live_app(preview_test_context) -> None:
    app = _make_preview_app(
        user=preview_test_context["user"],
        manager=preview_test_context["manager"],
    )

    with TestClient(app) as client:
        create_response = client.post(
            "/api/threads/thread-1/previews",
            json={
                "artifact_id": "dynamic-app",
                "root_path": "/mnt/user-data/workspace/dynamic-app",
                "command": "npm run dev -- --hostname 0.0.0.0",
                "port": 3000,
            },
        )
        preview_id = create_response.json()["id"]
        html_response = client.get(f"/api/threads/thread-1/previews/{preview_id}/proxy/")
        asset_response = client.get(f"/api/threads/thread-1/previews/{preview_id}/proxy/assets/app.js")

    assert html_response.status_code == 200
    assert "preview-ok" in html_response.text
    assert f"/api/threads/thread-1/previews/{preview_id}/proxy/" in html_response.text
    assert asset_response.status_code == 200
    assert asset_response.text == "console.log('preview-js-ok');"


def test_preview_session_logs_and_stop(preview_test_context) -> None:
    app = _make_preview_app(
        user=preview_test_context["user"],
        manager=preview_test_context["manager"],
    )

    with TestClient(app) as client:
        create_response = client.post(
            "/api/threads/thread-1/previews",
            json={
                "artifact_id": "dynamic-app",
                "root_path": "/mnt/user-data/workspace/dynamic-app",
                "command": "npm run dev -- --hostname 0.0.0.0",
                "port": 3000,
            },
        )
        preview_id = create_response.json()["id"]
        logs_response = client.get(f"/api/threads/thread-1/previews/{preview_id}/logs")
        stop_response = client.post(f"/api/threads/thread-1/previews/{preview_id}/stop")

    assert logs_response.status_code == 200
    assert "preview server booted" in logs_response.json()["logs"]
    assert stop_response.status_code == 200
    assert stop_response.json()["status"] == "stopped"


def test_preview_session_rejects_wrong_user(preview_test_context) -> None:
    owner_app = _make_preview_app(
        user=preview_test_context["user"],
        manager=preview_test_context["manager"],
    )

    other_user = _make_user("other@example.com", "00000000-0000-4000-8000-000000000002")
    other_app = _make_preview_app(
        user=other_user,
        manager=preview_test_context["manager"],
    )

    with TestClient(owner_app) as client:
        create_response = client.post(
            "/api/threads/thread-1/previews",
            json={
                "artifact_id": "dynamic-app",
                "root_path": "/mnt/user-data/workspace/dynamic-app",
                "command": "npm run dev -- --hostname 0.0.0.0",
                "port": 3000,
            },
        )
        preview_id = create_response.json()["id"]

    with TestClient(other_app) as client:
        response = client.get(f"/api/threads/thread-1/previews/{preview_id}")

    assert response.status_code == 404
