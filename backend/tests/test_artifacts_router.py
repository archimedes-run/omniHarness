import asyncio
import os
import zipfile
from pathlib import Path

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
    html_path.write_text("<!doctype html><script src='./assets/app.js'></script>", encoding="utf-8")

    with client:
        response = client.get("/api/threads/thread-1/artifacts/preview/mnt/user-data/outputs/site/index.html")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert response.headers.get("cache-control") == "no-store"
    assert "frame-ancestors 'self'" in response.headers.get("content-security-policy", "")
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("content-disposition", "").startswith("inline;")
    assert response.text.startswith("<!doctype html>")


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
