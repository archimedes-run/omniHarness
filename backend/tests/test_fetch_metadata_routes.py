"""Cookie-authenticated routes that can answer with model-authored HTML refuse a
navigation another site (or an opaque frame) starts, even with the session
cookie (Spec 012 S2 review): the thread file preview and the plain artifact view
when it answers HTML. The live preview has no cookie route any more (its frame
link carries a token and a sandbox header). A missing header keeps the old
behaviour; nested preview assets (the token route) are untouched."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.responses import Response
from fastapi.testclient import TestClient
from test_artifacts_router import _make_preview_test_app

import app.gateway.routers.artifacts as artifacts_router
import app.gateway.routers.previews as previews_router

CROSS_FRAME = {"Sec-Fetch-Dest": "iframe", "Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate"}
CROSS_PAGE = {"Sec-Fetch-Dest": "document", "Sec-Fetch-Site": "same-site", "Sec-Fetch-Mode": "navigate"}
OWN_FRAME = {"Sec-Fetch-Dest": "iframe", "Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "navigate"}
TYPED = {"Sec-Fetch-Dest": "document", "Sec-Fetch-Site": "none", "Sec-Fetch-Mode": "navigate"}


def _site(tmp_path, monkeypatch):
    client, outputs = _make_preview_test_app(tmp_path, monkeypatch)
    (outputs / "site").mkdir(parents=True, exist_ok=True)
    (outputs / "site" / "index.html").write_text("<!doctype html><html><head></head><body><p id=model>model page</p><a href='other.html'>next</a></body></html>")
    (outputs / "site" / "other.html").write_text("<!doctype html><p>other</p>")
    return client


@pytest.mark.parametrize("headers", [CROSS_FRAME, CROSS_PAGE])
def test_the_thread_preview_refuses_a_cross_site_navigation(tmp_path, monkeypatch, headers):
    client = _site(tmp_path, monkeypatch)
    with client:
        resp = client.get("/api/threads/thread-1/artifacts/preview/mnt/user-data/outputs/site/index.html", headers=headers)
    assert resp.status_code == 403 and b"model page" not in resp.content
    assert "sandbox" in resp.headers["content-security-policy"]


@pytest.mark.parametrize("headers", [OWN_FRAME, TYPED, {}, {"Sec-Fetch-Dest": "iframe"}])
def test_the_thread_preview_still_loads_for_this_app_and_old_clients(tmp_path, monkeypatch, headers):
    client = _site(tmp_path, monkeypatch)
    with client:
        resp = client.get("/api/threads/thread-1/artifacts/preview/mnt/user-data/outputs/site/index.html", headers=headers)
    assert resp.status_code == 200 and b"model page" in resp.content


def test_nested_navigation_inside_a_preview_goes_to_the_token_route_which_is_unchanged(tmp_path, monkeypatch):
    """A link inside a previewed page resolves against its <base>, the token
    route (no cookie needed): a navigation from the opaque preview frame
    (cross-site) still loads there."""
    client = _site(tmp_path, monkeypatch)
    with client:
        page = client.get("/api/threads/thread-1/artifacts/preview/mnt/user-data/outputs/site/index.html", headers=OWN_FRAME)
        base = page.text.split('<base href="', 1)[1].split('"', 1)[0]
        nested = client.get(base + "other.html", headers=CROSS_FRAME)
    assert "/artifacts/preview-token/" in base
    assert nested.status_code == 200 and b"other" in nested.content


def test_the_plain_view_refuses_a_cross_site_navigation_to_html(tmp_path, monkeypatch):
    client = _site(tmp_path, monkeypatch)
    target = next(tmp_path.rglob("site/index.html"))
    monkeypatch.setattr(artifacts_router, "resolve_thread_virtual_path", lambda thread_id, path: target)
    with client:
        refused = client.get("/api/threads/thread-1/artifacts/mnt/user-data/outputs/site/index.html", headers=CROSS_FRAME)
        own = client.get("/api/threads/thread-1/artifacts/mnt/user-data/outputs/site/index.html", headers=TYPED)
    assert refused.status_code == 403 and b"model page" not in refused.content
    assert own.status_code == 200 and own.headers["content-disposition"].startswith("attachment")


class _FakeManager:
    def frame_session(self, **kwargs):
        return SimpleNamespace(user_id="u1")

    async def proxy_request(self, **kwargs):
        return Response("<!doctype html><p id=model>preview page</p>", media_type="text/html", headers={"Content-Security-Policy": "sandbox allow-scripts allow-forms"})


def _proxy_client(monkeypatch):
    app = make_authed_test_app()
    app.include_router(previews_router.router)
    monkeypatch.setattr(previews_router, "get_preview_session_manager", lambda request: _FakeManager())
    return TestClient(app)


@pytest.mark.parametrize("path", ["/api/threads/thread-1/previews/p1/proxy", "/api/threads/thread-1/previews/p1/proxy/nested/page.html"])
def test_the_cookie_preview_proxy_is_gone(monkeypatch, path):
    """The live preview is served only on its frame link: the session cookie
    gets no preview document on any path, whatever the request says it is."""
    with _proxy_client(monkeypatch) as client:
        for headers in (CROSS_FRAME, OWN_FRAME, TYPED, {}):
            resp = client.get(path, headers=headers)
            assert resp.status_code in (404, 405) and b"preview page" not in resp.content, headers


def test_the_frame_link_serves_navigations_from_its_own_opaque_frame(monkeypatch):
    """A link inside the live preview navigates the sandboxed frame (an opaque
    origin, so cross-site): the frame link serves it, sandboxed by its header."""
    with _proxy_client(monkeypatch) as client:
        resp = client.get("/api/threads/thread-1/previews/p1/live/v1.1.x/next.html", headers=CROSS_FRAME)
    assert resp.status_code == 200 and b"preview page" in resp.content
    assert resp.headers["content-security-policy"].startswith("sandbox")


def test_the_helper_is_shared_with_the_frame_route():
    from app.gateway.routers import artifact_store

    assert artifact_store.own_frame_request.__module__ == "app.gateway.fetch_metadata"
    assert artifacts_router.cross_site_navigation.__module__ == "app.gateway.fetch_metadata"
