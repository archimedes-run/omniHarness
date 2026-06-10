import asyncio
import json
import os
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
from _router_auth_helpers import call_unwrapped, make_authed_test_app
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import FileResponse

import app.gateway.routers.artifacts as artifacts_router
from omniharness.config.paths import Paths

ACTIVE_ARTIFACT_CASES = [
    ("poc.html", "<html><body><script>alert('xss')</script></body></html>"),
    ("page.xhtml", '<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><body>hello</body></html>'),
    ("image.svg", '<svg xmlns="http://www.w3.org/2000/svg"><script>alert("xss")</script></svg>'),
]


def _make_request(query_string: bytes = b"") -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": query_string})


def _make_preview_test_app(tmp_path, monkeypatch, *, owner_check_passes: bool = True) -> tuple[TestClient, Path]:
    thread_id = "thread-1"
    user_id = "user-1"
    paths = Paths(tmp_path)
    paths.ensure_thread_dirs(thread_id, user_id=user_id)

    monkeypatch.setattr(artifacts_router, "get_paths", lambda: paths)
    monkeypatch.setattr(artifacts_router, "get_effective_user_id", lambda: user_id)

    app = make_authed_test_app(owner_check_passes=owner_check_passes)
    app.include_router(artifacts_router.router)
    return TestClient(app), paths.sandbox_outputs_dir(thread_id, user_id=user_id)


def _write_manifest(site_dir: Path, **overrides) -> None:
    site_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": site_dir.name,
        "title": "OmniHarness Next.js Marketing Site",
        "type": "static_site",
        "entrypoint": "index.html",
        "root": ".",
        "source_path": f"/mnt/user-data/workspace/{site_dir.name}",
        "preview": {"mode": "static"},
        "created_by": "agent",
    }
    manifest.update(overrides)
    (site_dir / "artifact_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_get_artifact_reads_utf8_text_file_on_windows_locale(tmp_path, monkeypatch) -> None:
    artifact_path = tmp_path / "note.txt"
    text = "Curly quotes: \u201cutf8\u201d"
    artifact_path.write_text(text, encoding="utf-8")

    original_read_text = Path.read_text

    def read_text_with_gbk_default(self, *args, **kwargs):
        kwargs.setdefault("encoding", "gbk")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text_with_gbk_default)
    monkeypatch.setattr(artifacts_router, "resolve_thread_virtual_path", lambda _thread_id, _path: artifact_path)

    request = _make_request()
    response = asyncio.run(call_unwrapped(artifacts_router.get_artifact, "thread-1", "mnt/user-data/outputs/note.txt", request))

    assert bytes(response.body).decode("utf-8") == text
    assert response.media_type == "text/plain"


@pytest.mark.parametrize(("filename", "content"), ACTIVE_ARTIFACT_CASES)
def test_get_artifact_forces_download_for_active_content(tmp_path, monkeypatch, filename: str, content: str) -> None:
    artifact_path = tmp_path / filename
    artifact_path.write_text(content, encoding="utf-8")

    monkeypatch.setattr(artifacts_router, "resolve_thread_virtual_path", lambda _thread_id, _path: artifact_path)

    response = asyncio.run(call_unwrapped(artifacts_router.get_artifact, "thread-1", f"mnt/user-data/outputs/{filename}", _make_request()))

    assert isinstance(response, FileResponse)
    assert response.headers.get("content-disposition", "").startswith("attachment;")


@pytest.mark.parametrize(("filename", "content"), ACTIVE_ARTIFACT_CASES)
def test_get_artifact_forces_download_for_active_content_in_skill_archive(tmp_path, monkeypatch, filename: str, content: str) -> None:
    skill_path = tmp_path / "sample.skill"
    with zipfile.ZipFile(skill_path, "w") as zip_ref:
        zip_ref.writestr(filename, content)

    monkeypatch.setattr(artifacts_router, "resolve_thread_virtual_path", lambda _thread_id, _path: skill_path)

    response = asyncio.run(call_unwrapped(artifacts_router.get_artifact, "thread-1", f"mnt/user-data/outputs/sample.skill/{filename}", _make_request()))

    assert response.headers.get("content-disposition", "").startswith("attachment;")
    assert bytes(response.body) == content.encode("utf-8")


def test_get_artifact_download_false_does_not_force_attachment(tmp_path, monkeypatch) -> None:
    artifact_path = tmp_path / "note.txt"
    artifact_path.write_text("hello", encoding="utf-8")

    monkeypatch.setattr(artifacts_router, "resolve_thread_virtual_path", lambda _thread_id, _path: artifact_path)

    app = make_authed_test_app()
    app.include_router(artifacts_router.router)

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/artifacts/mnt/user-data/outputs/note.txt?download=false")

    assert response.status_code == 200
    assert response.text == "hello"
    assert "content-disposition" not in response.headers


def test_get_artifact_download_true_forces_attachment_for_skill_archive(tmp_path, monkeypatch) -> None:
    skill_path = tmp_path / "sample.skill"
    with zipfile.ZipFile(skill_path, "w") as zip_ref:
        zip_ref.writestr("notes.txt", "hello")

    monkeypatch.setattr(artifacts_router, "resolve_thread_virtual_path", lambda _thread_id, _path: skill_path)

    app = make_authed_test_app()
    app.include_router(artifacts_router.router)

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/artifacts/mnt/user-data/outputs/sample.skill/notes.txt?download=true")

    assert response.status_code == 200
    assert response.text == "hello"
    assert response.headers.get("content-disposition", "").startswith("attachment;")


def test_preview_artifact_serves_html_inline_with_security_headers(tmp_path, monkeypatch) -> None:
    client, outputs_dir = _make_preview_test_app(tmp_path, monkeypatch)
    html_path = outputs_dir / "site" / "index.html"
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text("<!doctype html><html><head></head><body><script src='./assets/app.js'></script></body></html>", encoding="utf-8")

    with client:
        response = client.get("/api/threads/thread-1/artifacts/preview/mnt/user-data/outputs/site/index.html")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert response.headers.get("cache-control") == "no-store"
    assert "frame-ancestors 'self'" in response.headers.get("content-security-policy", "")
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("content-disposition", "").startswith("inline;")
    assert response.text.startswith("<!doctype html>")
    assert '<base href="/api/threads/thread-1/artifacts/preview-token/' in response.text
    assert "/mnt/user-data/outputs/site/" in response.text


def test_artifact_manifests_lists_valid_static_site_manifest(tmp_path, monkeypatch) -> None:
    client, outputs_dir = _make_preview_test_app(tmp_path, monkeypatch)
    site_dir = outputs_dir / "omniharness-next-site"
    (site_dir / "index.html").parent.mkdir(parents=True, exist_ok=True)
    (site_dir / "index.html").write_text("<html>site</html>", encoding="utf-8")
    _write_manifest(site_dir, id="omniharness-next-site")

    with client:
        response = client.get("/api/threads/thread-1/artifacts/manifests")

    assert response.status_code == 200
    body = response.json()
    assert len(body["manifests"]) == 1
    manifest = body["manifests"][0]
    assert manifest["id"] == "omniharness-next-site"
    assert manifest["title"] == "OmniHarness Next.js Marketing Site"
    assert manifest["type"] == "static_site"
    assert manifest["entrypoint_path"] == "/mnt/user-data/outputs/omniharness-next-site/index.html"
    assert manifest["manifest_path"] == "/mnt/user-data/outputs/omniharness-next-site/artifact_manifest.json"


def test_artifact_manifests_lists_valid_dynamic_web_app_manifest(tmp_path, monkeypatch) -> None:
    client, outputs_dir = _make_preview_test_app(tmp_path, monkeypatch)
    app_dir = outputs_dir / "omniharness-dynamic-next-app"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "artifact_manifest.json").write_text(
        json.dumps(
            {
                "id": "omniharness-dynamic-next-app",
                "title": "OmniHarness Dynamic Next App",
                "type": "web_app",
                "root": ".",
                "source_path": "/mnt/user-data/workspace/omniharness-dynamic-next-app",
                "preview": {
                    "mode": "dev_server",
                    "command": "npm run dev -- --hostname 0.0.0.0",
                    "port": 3000,
                },
                "created_by": "agent",
            }
        ),
        encoding="utf-8",
    )

    with client:
        response = client.get("/api/threads/thread-1/artifacts/manifests")

    assert response.status_code == 200
    body = response.json()
    assert len(body["manifests"]) == 1
    manifest = body["manifests"][0]
    assert manifest["id"] == "omniharness-dynamic-next-app"
    assert manifest["type"] == "web_app"
    assert manifest["preview"]["mode"] == "dev_server"
    assert manifest["entrypoint_path"] is None
    assert manifest["root_path"] == "/mnt/user-data/outputs/omniharness-dynamic-next-app"


def test_artifact_manifest_invalid_manifest_is_rejected(tmp_path, monkeypatch) -> None:
    client, outputs_dir = _make_preview_test_app(tmp_path, monkeypatch)
    site_dir = outputs_dir / "invalid-site"
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "index.html").write_text("<html>site</html>", encoding="utf-8")
    (site_dir / "artifact_manifest.json").write_text(
        json.dumps({"id": "invalid-site", "type": "static_site", "entrypoint": "index.html", "root": "."}),
        encoding="utf-8",
    )

    with client:
        response = client.get("/api/threads/thread-1/artifacts/manifests/invalid-site")

    assert response.status_code == 422
    assert "title" in response.json()["detail"]


def test_artifact_manifest_rejects_traversal_in_root(tmp_path, monkeypatch) -> None:
    client, outputs_dir = _make_preview_test_app(tmp_path, monkeypatch)
    site_dir = outputs_dir / "bad-root"
    (site_dir / "index.html").parent.mkdir(parents=True, exist_ok=True)
    (site_dir / "index.html").write_text("<html>site</html>", encoding="utf-8")
    _write_manifest(site_dir, id="bad-root", root="../bad-root")

    with client:
        response = client.get("/api/threads/thread-1/artifacts/manifests/bad-root")

    assert response.status_code == 422
    assert "root" in response.json()["detail"]


def test_artifact_manifest_rejects_traversal_in_entrypoint(tmp_path, monkeypatch) -> None:
    client, outputs_dir = _make_preview_test_app(tmp_path, monkeypatch)
    site_dir = outputs_dir / "bad-entrypoint"
    (site_dir / "index.html").parent.mkdir(parents=True, exist_ok=True)
    (site_dir / "index.html").write_text("<html>site</html>", encoding="utf-8")
    _write_manifest(site_dir, id="bad-entrypoint", entrypoint="../index.html")

    with client:
        response = client.get("/api/threads/thread-1/artifacts/manifests/bad-entrypoint")

    assert response.status_code == 422
    assert "entrypoint" in response.json()["detail"]


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink not supported on this platform")
def test_artifact_manifest_rejects_symlink_root_escape(tmp_path, monkeypatch) -> None:
    client, outputs_dir = _make_preview_test_app(tmp_path, monkeypatch)
    outside_dir = tmp_path / "outside-site"
    outside_dir.mkdir(parents=True)
    (outside_dir / "index.html").write_text("<html>outside</html>", encoding="utf-8")

    site_dir = outputs_dir / "symlink-site"
    site_dir.mkdir(parents=True, exist_ok=True)
    symlink = site_dir / "dist"
    try:
        symlink.symlink_to(outside_dir, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation failed: {exc}")
    _write_manifest(site_dir, id="symlink-site", root="dist")

    with client:
        response = client.get("/api/threads/thread-1/artifacts/manifests/symlink-site")

    assert response.status_code == 403


def test_artifact_manifest_entrypoint_path_opens_preview(tmp_path, monkeypatch) -> None:
    client, outputs_dir = _make_preview_test_app(tmp_path, monkeypatch)
    site_dir = outputs_dir / "nested-site"
    entrypoint = site_dir / "dist" / "nested" / "index.html"
    entrypoint.parent.mkdir(parents=True, exist_ok=True)
    entrypoint.write_text("<html><body>manifest-preview-ok</body></html>", encoding="utf-8")
    _write_manifest(site_dir, id="nested-site", root="dist", entrypoint="nested/index.html")

    with client:
        manifest_response = client.get("/api/threads/thread-1/artifacts/manifests/nested-site")
        preview_response = client.get(f"/api/threads/thread-1/artifacts/preview{manifest_response.json()['entrypoint_path']}")

    assert manifest_response.status_code == 200
    assert preview_response.status_code == 200
    assert "manifest-preview-ok" in preview_response.text


@pytest.mark.parametrize(
    ("asset_path", "content", "expected_content_type"),
    [
        ("_next/static/chunks/app.js", "console.log('next-ok')", "javascript"),
        ("_next/static/css/app.css", "body { color: rebeccapurple; }", "text/css"),
    ],
)
def test_preview_artifact_token_route_serves_static_assets_without_session_cookie(
    tmp_path,
    monkeypatch,
    asset_path: str,
    content: str,
    expected_content_type: str,
) -> None:
    thread_id = "thread-1"
    user_id = "user-1"
    paths = Paths(tmp_path)
    paths.ensure_thread_dirs(thread_id, user_id=user_id)
    target = paths.sandbox_outputs_dir(thread_id, user_id=user_id) / "site" / asset_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")

    monkeypatch.setattr(artifacts_router, "get_paths", lambda: paths)
    token = artifacts_router._create_preview_token(thread_id, user_id, "/mnt/user-data/outputs/site")

    from fastapi import FastAPI

    from app.gateway.auth_middleware import AuthMiddleware

    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.include_router(artifacts_router.router)

    with TestClient(app) as client:
        response = client.get(f"/api/threads/{thread_id}/artifacts/preview-token/{token}/mnt/user-data/outputs/site/{asset_path}")

    assert response.status_code == 200
    assert expected_content_type in response.headers["content-type"]
    assert response.headers.get("cross-origin-resource-policy") == "cross-origin"
    assert "cross-origin-embedder-policy" not in response.headers
    assert "content-security-policy" not in response.headers
    assert "x-frame-options" not in response.headers
    assert response.text == content


def test_preview_artifact_token_route_stays_inside_token_root(tmp_path, monkeypatch) -> None:
    thread_id = "thread-1"
    user_id = "user-1"
    paths = Paths(tmp_path)
    paths.ensure_thread_dirs(thread_id, user_id=user_id)
    outside_path = paths.sandbox_outputs_dir(thread_id, user_id=user_id) / "other" / "app.js"
    outside_path.parent.mkdir(parents=True, exist_ok=True)
    outside_path.write_text("console.log('outside')", encoding="utf-8")

    monkeypatch.setattr(artifacts_router, "get_paths", lambda: paths)
    token = artifacts_router._create_preview_token(thread_id, user_id, "/mnt/user-data/outputs/site")

    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(artifacts_router.router)

    with TestClient(app) as client:
        response = client.get(f"/api/threads/{thread_id}/artifacts/preview-token/{token}/mnt/user-data/outputs/other/app.js")

    assert response.status_code == 403


def test_preview_artifact_token_route_rejects_expired_token(tmp_path, monkeypatch) -> None:
    thread_id = "thread-1"
    user_id = "user-1"
    paths = Paths(tmp_path)
    paths.ensure_thread_dirs(thread_id, user_id=user_id)
    target = paths.sandbox_outputs_dir(thread_id, user_id=user_id) / "site" / "app.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("console.log('expired')", encoding="utf-8")

    monkeypatch.setattr(artifacts_router, "get_paths", lambda: paths)

    from app.gateway.auth.config import get_auth_config

    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "typ": artifacts_router.PREVIEW_TOKEN_TYPE,
            "sub": user_id,
            "tid": thread_id,
            "root": "/mnt/user-data/outputs/site",
            "iat": now - timedelta(minutes=20),
            "exp": now - timedelta(minutes=10),
        },
        get_auth_config().jwt_secret,
        algorithm="HS256",
    )

    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(artifacts_router.router)

    with TestClient(app) as client:
        response = client.get(f"/api/threads/{thread_id}/artifacts/preview-token/{token}/mnt/user-data/outputs/site/app.js")

    assert response.status_code == 401
    assert response.json()["detail"] == "Preview token expired"


@pytest.mark.parametrize(
    ("asset_path", "content", "expected_content_type"),
    [
        ("assets/app.js", "console.log('ok')", "javascript"),
        ("assets/style.css", "body { color: red; }", "text/css"),
    ],
)
def test_preview_artifact_serves_relative_static_assets(tmp_path, monkeypatch, asset_path: str, content: str, expected_content_type: str) -> None:
    client, outputs_dir = _make_preview_test_app(tmp_path, monkeypatch)
    target = outputs_dir / "site" / asset_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")

    with client:
        response = client.get(f"/api/threads/thread-1/artifacts/preview/mnt/user-data/outputs/site/{asset_path}")

    assert response.status_code == 200
    assert expected_content_type in response.headers["content-type"]
    assert response.text == content


def test_preview_artifact_rejects_path_traversal(tmp_path, monkeypatch) -> None:
    client, outputs_dir = _make_preview_test_app(tmp_path, monkeypatch)
    workspace_secret = outputs_dir.parent / "workspace" / "secret.txt"
    workspace_secret.write_text("secret", encoding="utf-8")

    with client:
        response = client.get("/api/threads/thread-1/artifacts/preview/mnt/user-data/outputs/%2E%2E/workspace/secret.txt")

    assert response.status_code == 403


def test_preview_artifact_rejects_files_outside_outputs(tmp_path, monkeypatch) -> None:
    client, outputs_dir = _make_preview_test_app(tmp_path, monkeypatch)
    upload_file = outputs_dir.parent / "uploads" / "upload.html"
    upload_file.write_text("<html>nope</html>", encoding="utf-8")

    with client:
        response = client.get("/api/threads/thread-1/artifacts/preview/mnt/user-data/uploads/upload.html")

    assert response.status_code == 403


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink not supported on this platform")
def test_preview_artifact_rejects_symlink_that_leaves_outputs(tmp_path, monkeypatch) -> None:
    client, outputs_dir = _make_preview_test_app(tmp_path, monkeypatch)
    outside_file = tmp_path / "outside.html"
    outside_file.write_text("<html>outside</html>", encoding="utf-8")
    symlink = outputs_dir / "leak.html"
    try:
        symlink.symlink_to(outside_file)
    except OSError as exc:
        pytest.skip(f"symlink creation failed: {exc}")

    with client:
        response = client.get("/api/threads/thread-1/artifacts/preview/mnt/user-data/outputs/leak.html")

    assert response.status_code == 403


def test_preview_artifact_requires_authentication(tmp_path, monkeypatch) -> None:
    thread_id = "thread-1"
    user_id = "user-1"
    paths = Paths(tmp_path)
    paths.ensure_thread_dirs(thread_id, user_id=user_id)
    target = paths.sandbox_outputs_dir(thread_id, user_id=user_id) / "index.html"
    target.write_text("<html>secret</html>", encoding="utf-8")

    monkeypatch.setattr(artifacts_router, "get_paths", lambda: paths)
    monkeypatch.setattr(artifacts_router, "get_effective_user_id", lambda: user_id)

    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(artifacts_router.router)

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/artifacts/preview/mnt/user-data/outputs/index.html")

    assert response.status_code == 401


def test_preview_artifact_rejects_wrong_user(tmp_path, monkeypatch) -> None:
    client, outputs_dir = _make_preview_test_app(tmp_path, monkeypatch, owner_check_passes=False)
    target = outputs_dir / "index.html"
    target.write_text("<html>secret</html>", encoding="utf-8")

    with client:
        response = client.get("/api/threads/thread-1/artifacts/preview/mnt/user-data/outputs/index.html")

    assert response.status_code == 404


# --- Manifest field normalization tests ---


def test_artifact_manifest_normalizes_name_to_title(tmp_path, monkeypatch) -> None:
    """Agents sometimes write 'name' instead of 'title'; backend should accept both."""
    client, outputs_dir = _make_preview_test_app(tmp_path, monkeypatch)
    site_dir = outputs_dir / "my-site"
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "index.html").write_text("<html>site</html>", encoding="utf-8")
    (site_dir / "artifact_manifest.json").write_text(
        json.dumps(
            {
                "id": "my-site",
                "name": "My Awesome Site",  # agent wrote "name" instead of "title"
                "type": "static_site",
                "entrypoint": "index.html",
                "root": ".",
                "preview": {"mode": "static"},
            }
        ),
        encoding="utf-8",
    )

    with client:
        response = client.get("/api/threads/thread-1/artifacts/manifests/my-site")

    assert response.status_code == 200
    assert response.json()["title"] == "My Awesome Site"


def test_artifact_manifest_normalizes_preview_cwd_to_source_path(tmp_path, monkeypatch) -> None:
    """Agents sometimes put the workspace path as preview.cwd instead of top-level source_path."""
    client, outputs_dir = _make_preview_test_app(tmp_path, monkeypatch)
    app_dir = outputs_dir / "dynamic-app"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "artifact_manifest.json").write_text(
        json.dumps(
            {
                "id": "dynamic-app",
                "title": "Dynamic App",
                "type": "web_app",
                "root": ".",
                # source_path absent; cwd nested inside preview instead
                "preview": {
                    "mode": "dev_server",
                    "command": "npm run dev -- --hostname 0.0.0.0",
                    "port": 3000,
                    "cwd": "/mnt/user-data/workspace/dynamic-app",
                },
            }
        ),
        encoding="utf-8",
    )

    with client:
        response = client.get("/api/threads/thread-1/artifacts/manifests/dynamic-app")

    assert response.status_code == 200
    manifest = response.json()
    assert manifest["type"] == "web_app"
    assert manifest["source_path"] == "/mnt/user-data/workspace/dynamic-app"


def test_artifact_manifest_normalizes_name_and_cwd_combined(tmp_path, monkeypatch) -> None:
    """All agent-generated field aliases can be normalized in a single manifest."""
    client, outputs_dir = _make_preview_test_app(tmp_path, monkeypatch)
    app_dir = outputs_dir / "my-dynamic-app"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "artifact_manifest.json").write_text(
        json.dumps(
            {
                "id": "my-dynamic-app",
                "name": "My Dynamic App",  # alias for title
                "type": "web_app",
                "root": ".",
                "preview": {
                    "mode": "dev_server",
                    "command": "npm run dev -- --hostname 0.0.0.0",
                    "port": 3000,
                    "cwd": "/mnt/user-data/workspace/my-dynamic-app",  # alias for source_path
                },
            }
        ),
        encoding="utf-8",
    )

    with client:
        response = client.get("/api/threads/thread-1/artifacts/manifests/my-dynamic-app")

    assert response.status_code == 200
    manifest = response.json()
    assert manifest["title"] == "My Dynamic App"
    assert manifest["source_path"] == "/mnt/user-data/workspace/my-dynamic-app"


def test_artifact_manifest_infers_source_path_from_workspace_convention(tmp_path, monkeypatch) -> None:
    """When source_path and preview.cwd are both absent, infer /mnt/user-data/workspace/<id>."""
    client, outputs_dir = _make_preview_test_app(tmp_path, monkeypatch)
    app_dir = outputs_dir / "my-app"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "artifact_manifest.json").write_text(
        json.dumps(
            {
                "id": "my-app",
                "title": "My App",
                "type": "web_app",
                "root": ".",
                # source_path completely absent, no preview.cwd either
                "preview": {
                    "mode": "dev_server",
                    "command": "npm run dev -- --hostname 0.0.0.0",
                    "port": 3000,
                },
            }
        ),
        encoding="utf-8",
    )

    with client:
        response = client.get("/api/threads/thread-1/artifacts/manifests/my-app")

    assert response.status_code == 200
    assert response.json()["source_path"] == "/mnt/user-data/workspace/my-app"


def test_artifact_manifest_explicit_title_takes_precedence_over_name(tmp_path, monkeypatch) -> None:
    """When both 'title' and 'name' are present, 'title' wins."""
    client, outputs_dir = _make_preview_test_app(tmp_path, monkeypatch)
    site_dir = outputs_dir / "titled-site"
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "index.html").write_text("<html>site</html>", encoding="utf-8")
    (site_dir / "artifact_manifest.json").write_text(
        json.dumps(
            {
                "id": "titled-site",
                "title": "Correct Title",
                "name": "Wrong Name",
                "type": "static_site",
                "entrypoint": "index.html",
                "root": ".",
                "preview": {"mode": "static"},
            }
        ),
        encoding="utf-8",
    )

    with client:
        response = client.get("/api/threads/thread-1/artifacts/manifests/titled-site")

    assert response.status_code == 200
    assert response.json()["title"] == "Correct Title"


# --- Project workspace file tree tests ---


def _make_project_test_app(tmp_path, monkeypatch, *, owner_check_passes: bool = True):
    thread_id = "thread-1"
    user_id = "user-1"
    paths = Paths(tmp_path)
    paths.ensure_thread_dirs(thread_id, user_id=user_id)
    monkeypatch.setattr(artifacts_router, "get_paths", lambda: paths)
    monkeypatch.setattr(artifacts_router, "get_effective_user_id", lambda: user_id)
    app = make_authed_test_app(owner_check_passes=owner_check_passes)
    app.include_router(artifacts_router.router)
    return TestClient(app), paths, thread_id, user_id


def _write_web_app_manifest(outputs_dir: Path, app_id: str) -> None:
    app_dir = outputs_dir / app_id
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "artifact_manifest.json").write_text(
        json.dumps(
            {
                "id": app_id,
                "title": "Test Web App",
                "type": "web_app",
                "root": ".",
                "source_path": f"/mnt/user-data/workspace/{app_id}",
                "preview": {"mode": "dev_server", "command": "npm run dev", "port": 3000},
            }
        ),
        encoding="utf-8",
    )


def test_project_files_lists_workspace_source_files(tmp_path, monkeypatch) -> None:
    client, paths, thread_id, user_id = _make_project_test_app(tmp_path, monkeypatch)
    outputs_dir = paths.sandbox_outputs_dir(thread_id, user_id=user_id)
    _write_web_app_manifest(outputs_dir, "test-app")

    source_dir = paths.resolve_virtual_path(thread_id, "/mnt/user-data/workspace/test-app", user_id=user_id)
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "src").mkdir()
    (source_dir / "src" / "App.tsx").write_text("export default function App() {}", encoding="utf-8")
    (source_dir / "package.json").write_text('{"name":"test-app"}', encoding="utf-8")
    # node_modules should be excluded
    (source_dir / "node_modules").mkdir()
    (source_dir / "node_modules" / "react").mkdir()
    (source_dir / "node_modules" / "react" / "index.js").write_text("module.exports = {};", encoding="utf-8")

    with client:
        response = client.get("/api/threads/thread-1/projects/test-app/files")

    assert response.status_code == 200
    body = response.json()
    listed = [f["path"] for f in body["files"]]
    assert "src/App.tsx" in listed
    assert "package.json" in listed
    assert not any("node_modules" in p for p in listed)


def test_project_files_manifest_hidden_from_listing(tmp_path, monkeypatch) -> None:
    client, paths, thread_id, user_id = _make_project_test_app(tmp_path, monkeypatch)
    outputs_dir = paths.sandbox_outputs_dir(thread_id, user_id=user_id)
    _write_web_app_manifest(outputs_dir, "test-app")

    source_dir = paths.resolve_virtual_path(thread_id, "/mnt/user-data/workspace/test-app", user_id=user_id)
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "index.ts").write_text("export {};", encoding="utf-8")
    # Put a manifest file at root to verify it's hidden
    (source_dir / "artifact_manifest.json").write_text("{}", encoding="utf-8")

    with client:
        response = client.get("/api/threads/thread-1/projects/test-app/files")

    assert response.status_code == 200
    listed = [f["path"] for f in response.json()["files"]]
    assert "artifact_manifest.json" not in listed
    assert "index.ts" in listed


def test_project_files_falls_back_to_outputs_when_no_workspace(tmp_path, monkeypatch) -> None:
    client, paths, thread_id, user_id = _make_project_test_app(tmp_path, monkeypatch)
    outputs_dir = paths.sandbox_outputs_dir(thread_id, user_id=user_id)
    # source_path points to workspace which doesn't exist → should fall back to outputs root_path
    _write_web_app_manifest(outputs_dir, "test-app")
    (outputs_dir / "test-app" / "main.ts").write_text("console.log('hello');", encoding="utf-8")

    with client:
        response = client.get("/api/threads/thread-1/projects/test-app/files")

    assert response.status_code == 200
    listed = [f["path"] for f in response.json()["files"]]
    assert "main.ts" in listed


def test_project_files_content_reads_file(tmp_path, monkeypatch) -> None:
    client, paths, thread_id, user_id = _make_project_test_app(tmp_path, monkeypatch)
    outputs_dir = paths.sandbox_outputs_dir(thread_id, user_id=user_id)
    _write_web_app_manifest(outputs_dir, "test-app")

    source_dir = paths.resolve_virtual_path(thread_id, "/mnt/user-data/workspace/test-app", user_id=user_id)
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "src").mkdir()
    (source_dir / "src" / "App.tsx").write_text("export default function App() { return null; }", encoding="utf-8")

    with client:
        response = client.get("/api/threads/thread-1/projects/test-app/files/content?path=src/App.tsx")

    assert response.status_code == 200
    assert "App()" in response.text


def test_project_files_content_rejects_traversal(tmp_path, monkeypatch) -> None:
    client, paths, thread_id, user_id = _make_project_test_app(tmp_path, monkeypatch)
    outputs_dir = paths.sandbox_outputs_dir(thread_id, user_id=user_id)
    _write_web_app_manifest(outputs_dir, "test-app")
    source_dir = paths.resolve_virtual_path(thread_id, "/mnt/user-data/workspace/test-app", user_id=user_id)
    source_dir.mkdir(parents=True, exist_ok=True)

    with client:
        response = client.get("/api/threads/thread-1/projects/test-app/files/content?path=../secret.txt")

    assert response.status_code == 400


def test_project_files_content_rejects_absolute_path(tmp_path, monkeypatch) -> None:
    client, paths, thread_id, user_id = _make_project_test_app(tmp_path, monkeypatch)
    outputs_dir = paths.sandbox_outputs_dir(thread_id, user_id=user_id)
    _write_web_app_manifest(outputs_dir, "test-app")
    source_dir = paths.resolve_virtual_path(thread_id, "/mnt/user-data/workspace/test-app", user_id=user_id)
    source_dir.mkdir(parents=True, exist_ok=True)

    with client:
        response = client.get("/api/threads/thread-1/projects/test-app/files/content?path=/etc/passwd")

    assert response.status_code == 400


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink not supported on this platform")
def test_project_files_content_rejects_symlink_escape(tmp_path, monkeypatch) -> None:
    client, paths, thread_id, user_id = _make_project_test_app(tmp_path, monkeypatch)
    outputs_dir = paths.sandbox_outputs_dir(thread_id, user_id=user_id)
    _write_web_app_manifest(outputs_dir, "test-app")
    source_dir = paths.resolve_virtual_path(thread_id, "/mnt/user-data/workspace/test-app", user_id=user_id)
    source_dir.mkdir(parents=True, exist_ok=True)

    outside_file = tmp_path / "secret.txt"
    outside_file.write_text("secret", encoding="utf-8")
    symlink = source_dir / "evil.txt"
    try:
        symlink.symlink_to(outside_file)
    except OSError as exc:
        pytest.skip(f"symlink creation failed: {exc}")

    with client:
        response = client.get("/api/threads/thread-1/projects/test-app/files/content?path=evil.txt")

    assert response.status_code == 403
