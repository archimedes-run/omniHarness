import json
import uuid
from typing import Any

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

import app.gateway.preview_sessions as preview_sessions
import app.gateway.routers.artifacts as artifacts_router
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

    def execute_command(self, command: str) -> str:
        # Simulate the project directory always existing in the fake sandbox.
        if command.startswith("test -d"):
            return "__dir_ok__"
        return ""

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
        # Tracks whether the sandbox is "active" (acquired) vs "released" (warm pool).
        # Mimics the real provider: get() returns None when released, acquire() re-activates.
        self._active = True

    def acquire(self, thread_id: str | None = None) -> str:
        self._active = True
        return "sandbox-1"

    def get(self, sandbox_id: str):
        return self._sandbox if self._active else None

    def release(self) -> None:
        """Simulate the agent releasing the sandbox after a run."""
        self._active = False


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


def test_create_preview_from_manifest(preview_test_context, monkeypatch) -> None:
    user = preview_test_context["user"]
    paths = preview_test_context["paths"]
    thread_id = preview_test_context["thread_id"]

    # Write a valid web_app manifest in the outputs directory
    outputs_dir = paths.sandbox_outputs_dir(thread_id, user_id=str(user.id))
    app_dir = outputs_dir / "dynamic-app"
    app_dir.mkdir(parents=True, exist_ok=True)
    manifest_data = {
        "id": "dynamic-app",
        "title": "Dynamic App",
        "type": "web_app",
        "root": ".",
        "source_path": "/mnt/user-data/workspace/dynamic-app",
        "preview": {
            "mode": "dev_server",
            "command": "npm run dev -- --hostname 0.0.0.0",
            "port": 3000,
        },
        "created_by": "agent",
    }
    (app_dir / "artifact_manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")

    monkeypatch.setattr(artifacts_router, "get_paths", lambda: paths)

    app = _make_preview_app(
        user=user,
        manager=preview_test_context["manager"],
    )

    with TestClient(app) as client:
        response = client.post(f"/api/threads/{thread_id}/artifacts/manifests/dynamic-app/preview")

    assert response.status_code == 200
    body = response.json()
    assert body["artifact_id"] == "dynamic-app"
    assert body["status"] in ("starting", "running")
    assert body["command"] == "npm run dev -- --hostname 0.0.0.0"


def test_create_preview_from_manifest_accepts_outputs_path(preview_test_context, monkeypatch) -> None:
    """Manifest-based preview endpoint should accept source_path under outputs, not just workspace.

    Agents often place the project in /mnt/user-data/outputs instead of /mnt/user-data/workspace.
    The manifest endpoint must accept both locations since both are scoped to the user's thread.
    """
    user = preview_test_context["user"]
    paths = preview_test_context["paths"]
    thread_id = preview_test_context["thread_id"]

    outputs_dir = paths.sandbox_outputs_dir(thread_id, user_id=str(user.id))
    app_dir = outputs_dir / "my-next-app"
    app_dir.mkdir(parents=True, exist_ok=True)
    manifest_data = {
        "id": "my-next-app",
        "title": "My Next App",
        "type": "web_app",
        "root": ".",
        "source_path": "/mnt/user-data/outputs/my-next-app",
        "preview": {
            "mode": "dev_server",
            "command": "npm run dev -- --hostname 0.0.0.0",
            "port": 3000,
        },
        "created_by": "agent",
    }
    (app_dir / "artifact_manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")

    monkeypatch.setattr(artifacts_router, "get_paths", lambda: paths)

    app = _make_preview_app(
        user=user,
        manager=preview_test_context["manager"],
    )

    with TestClient(app) as client:
        response = client.post(f"/api/threads/{thread_id}/artifacts/manifests/my-next-app/preview")

    assert response.status_code == 200
    body = response.json()
    assert body["artifact_id"] == "my-next-app"
    assert body["status"] in ("starting", "running")
    assert body["command"] == "npm run dev -- --hostname 0.0.0.0"


def test_create_preview_from_manifest_rejects_static_site(preview_test_context, monkeypatch) -> None:
    user = preview_test_context["user"]
    paths = preview_test_context["paths"]
    thread_id = preview_test_context["thread_id"]

    # Write a static_site manifest (should be rejected)
    outputs_dir = paths.sandbox_outputs_dir(thread_id, user_id=str(user.id))
    site_dir = outputs_dir / "my-site"
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "index.html").write_text("<html></html>", encoding="utf-8")
    manifest_data = {
        "id": "my-site",
        "title": "Static Site",
        "type": "static_site",
        "entrypoint": "index.html",
        "root": ".",
        "preview": {"mode": "static"},
        "created_by": "agent",
    }
    (site_dir / "artifact_manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")

    monkeypatch.setattr(artifacts_router, "get_paths", lambda: paths)

    app = _make_preview_app(
        user=user,
        manager=preview_test_context["manager"],
    )

    with TestClient(app) as client:
        response = client.post(f"/api/threads/{thread_id}/artifacts/manifests/my-site/preview")

    assert response.status_code == 422
    assert "web_app" in response.json()["detail"]


def test_preview_session_survives_sandbox_release(preview_test_context) -> None:
    """Preview session polling must survive the agent releasing the sandbox after a run.

    The real provider's get() returns None once the sandbox is released to the warm pool.
    _get_sandbox_for_existing_session must call acquire() instead, which reclaims it.
    """
    user = preview_test_context["user"]
    provider = preview_test_context["provider"]
    manager = preview_test_context["manager"]

    app = _make_preview_app(user=user, manager=manager)

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
        assert create_response.status_code == 200
        preview_id = create_response.json()["id"]

        # Simulate the agent releasing the sandbox after its run ends
        provider.release()

        # Preview polling must still work (acquire() reclaims the sandbox)
        list_response = client.get("/api/threads/thread-1/previews")
        assert list_response.status_code == 200
        sessions = list_response.json()
        assert len(sessions) == 1
        assert sessions[0]["id"] == preview_id
        assert sessions[0]["status"] in ("starting", "running")

        # Logs must also work
        logs_response = client.get(f"/api/threads/thread-1/previews/{preview_id}/logs")
        assert logs_response.status_code == 200


def test_create_preview_recreates_session_when_sandbox_gone(preview_test_context, monkeypatch) -> None:
    """When the sandbox disappears (e.g. Docker restart), create_session_from_manifest must
    transparently replace the stale "starting" session with a fresh one instead of 404-ing."""
    user = preview_test_context["user"]
    paths = preview_test_context["paths"]
    thread_id = preview_test_context["thread_id"]
    sandbox = preview_test_context["sandbox"]
    manager = preview_test_context["manager"]

    outputs_dir = paths.sandbox_outputs_dir(thread_id, user_id=str(user.id))
    app_dir = outputs_dir / "dynamic-app"
    app_dir.mkdir(parents=True, exist_ok=True)
    manifest_data = {
        "id": "dynamic-app",
        "title": "Dynamic App",
        "type": "web_app",
        "root": ".",
        "source_path": "/mnt/user-data/workspace/dynamic-app",
        "preview": {"mode": "dev_server", "command": "npm run dev -- --hostname 0.0.0.0", "port": 3000},
        "created_by": "agent",
    }
    (app_dir / "artifact_manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")
    monkeypatch.setattr(artifacts_router, "get_paths", lambda: paths)

    app = _make_preview_app(user=user, manager=manager)

    with TestClient(app) as client:
        # First create — session starts normally
        r1 = client.post(f"/api/threads/{thread_id}/artifacts/manifests/dynamic-app/preview")
        assert r1.status_code == 200
        first_id = r1.json()["id"]

        # Simulate sandbox disappearing: old sandbox_id returns non-AioSandbox; new sandbox is available.
        # Must also patch AioSandboxProvider so isinstance() passes for the new provider.
        class _GoneSandboxProvider(_FakeAioSandboxProvider):
            def acquire(self, thread_id=None):
                return "sandbox-new"

            def get(self, sandbox_id: str):
                if sandbox_id == "sandbox-1":
                    return None  # old sandbox gone
                return self._sandbox  # new sandbox available

        gone_provider = _GoneSandboxProvider(sandbox)
        monkeypatch.setattr(preview_sessions, "get_sandbox_provider", lambda: gone_provider)
        monkeypatch.setattr(preview_sessions, "AioSandboxProvider", _GoneSandboxProvider)

        # Second create — must recreate instead of 404-ing
        r2 = client.post(f"/api/threads/{thread_id}/artifacts/manifests/dynamic-app/preview")

    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["artifact_id"] == "dynamic-app"
    assert body2["status"] in ("starting", "running")
    # Session record is reused (same ID) but restarted with new sandbox
    assert body2["id"] == first_id


def test_stop_session_succeeds_when_sandbox_gone(preview_test_context, monkeypatch) -> None:
    """Stopping a preview session whose sandbox has disappeared should return stopped, not 404."""
    user = preview_test_context["user"]
    sandbox = preview_test_context["sandbox"]
    manager = preview_test_context["manager"]

    app = _make_preview_app(user=user, manager=manager)

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
        assert create_response.status_code == 200
        preview_id = create_response.json()["id"]

        # Simulate sandbox disappearing
        class _GoneSandboxProvider(_FakeAioSandboxProvider):
            def get(self, sandbox_id: str):
                return None

        gone_provider = _GoneSandboxProvider(sandbox)
        monkeypatch.setattr(preview_sessions, "get_sandbox_provider", lambda: gone_provider)
        monkeypatch.setattr(preview_sessions, "AioSandboxProvider", _GoneSandboxProvider)

        stop_response = client.post(f"/api/threads/thread-1/previews/{preview_id}/stop")

    assert stop_response.status_code == 200
    assert stop_response.json()["status"] == "stopped"


def test_create_preview_from_manifest_missing(preview_test_context, monkeypatch) -> None:
    user = preview_test_context["user"]
    paths = preview_test_context["paths"]
    thread_id = preview_test_context["thread_id"]

    monkeypatch.setattr(artifacts_router, "get_paths", lambda: paths)

    app = _make_preview_app(
        user=user,
        manager=preview_test_context["manager"],
    )

    with TestClient(app) as client:
        response = client.post(f"/api/threads/{thread_id}/artifacts/manifests/nonexistent/preview")

    assert response.status_code == 404
