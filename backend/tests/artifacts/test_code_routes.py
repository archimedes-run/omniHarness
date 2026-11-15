"""The locked frame's routes and the owner's code-kind actions (Spec 012 Slice 2),
through create_app() and its real lifespan, owner signed in."""

from __future__ import annotations

import pytest
from fake_sandbox import FakeSandbox, failing
from langchain_core.messages import AIMessage

from app.gateway.apps import bundle
from app.gateway.artifacts_store import code_service, frame
from app.gateway.artifacts_store.service import GatewayArtifactController
from app.gateway.internal_auth import create_internal_auth_headers
from app.policy.lineage import user_turn
from omniharness.runtime.artifacts.controller import MESSAGES_KEY, TOOL_CALL_KEY

PAGE = "<!doctype html><html><head></head><body><h1 id=secret-marker>Hello</h1></body></html>"
REACT = {"entry": "App.tsx", "files": {"App.tsx": "export default function App(){ return <h1>Hi</h1>; }"}}
IFRAME = {"Sec-Fetch-Dest": "iframe", "Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "navigate"}


@pytest.fixture
def sandbox(monkeypatch):
    box = {"ops": FakeSandbox()}
    monkeypatch.setattr(code_service, "sandbox_factory", lambda thread_id, owner_id: box["ops"])
    return box


def make(gateway, kind="html", content=PAGE):
    tools = GatewayArtifactController(lambda: gateway.store)
    context = {"user_id": gateway.user_id, "thread_id": "thread-a", "run_id": "run-1", MESSAGES_KEY: [user_turn("make it"), AIMessage(content="", tool_calls=[{"name": "artifact_create", "args": {}, "id": "c1"}])], TOOL_CALL_KEY: "c1"}
    text, card = tools.create(context, kind=kind, title="Page", content=content, language=None, source_path=None, note=None)
    assert card is not None, text
    return card["artifact_id"]


def token(gateway, aid, n=1):
    resp = gateway.client.get(f"/api/artifacts/{aid}/versions/{n}/frame-token")
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_frame_is_served_only_to_this_apps_iframe_with_a_view_token(gateway, sandbox):
    aid = make(gateway)
    c = gateway.client
    # Anything else is inert: a top-level open, a fetch, another site (each with a fresh token).
    for headers in ({}, {**IFRAME, "Sec-Fetch-Dest": "document"}, {**IFRAME, "Sec-Fetch-Dest": "empty"}, {**IFRAME, "Sec-Fetch-Site": "cross-site"}, {**IFRAME, "Sec-Fetch-Site": "same-site"}):
        resp = c.get(token(gateway, aid)["url"], headers=headers)
        assert resp.status_code == 403 and "secret-marker" not in resp.text, headers
        assert resp.headers["content-security-policy"].startswith("default-src 'none'") and "sandbox" in resp.headers["content-security-policy"]
    url = token(gateway, aid)["url"]
    ok = c.get(url, headers=IFRAME)
    assert ok.status_code == 200
    doc, hashes = frame.frame_document(PAGE.encode())
    assert ok.content == doc and ok.headers["content-security-policy"] == bundle.csp(hashes)
    for name, value in frame.HEADERS.items():
        assert ok.headers[name] == value, name
    assert ok.headers["content-type"] == "text/html; charset=utf-8"
    assert ok.text.startswith("<!doctype html><script>")
    # ONE document per token: the same URL again (a reload, or the frame's
    # own code reading location.href) gets nothing.
    again = c.get(url, headers=IFRAME)
    assert again.status_code == 403 and "secret-marker" not in again.text
    bare = f"/api/artifacts/{aid}/versions/1/frame.html"
    assert "secret-marker" not in c.get(bare, headers=IFRAME).text
    assert "secret-marker" not in c.get(bare + "?t=forged.x", headers=IFRAME).text


def test_a_token_is_bound_to_owner_artifact_and_version_and_cannot_be_altered(gateway, sandbox):
    import base64
    import json as _json

    a = make(gateway)
    b = make(gateway, content=PAGE.replace("Hello", "Other"))
    c = gateway.client
    t_a = token(gateway, a)["token"]
    assert "secret-marker" not in c.get(f"/api/artifacts/{b}/versions/1/frame.html?t={t_a}", headers=IFRAME).text
    gateway.store.add_version(gateway.user_id, a, base_version=1, canon=frame.canonical_html(PAGE + " ")[0], lineage="user", lineage_source=None, origin="owner_edit", code={})
    assert c.get(f"/api/artifacts/{a}/versions/2/frame.html?t={token(gateway, a)['token']}", headers=IFRAME).status_code == 403
    body, mac = token(gateway, a, 2)["token"].split(".")
    payload = _json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    payload["a"] = b
    payload["n"] = 1
    forged = base64.urlsafe_b64encode(_json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()).decode().rstrip("=") + "." + mac
    assert c.get(f"/api/artifacts/{b}/versions/1/frame.html?t={forged}", headers=IFRAME).status_code == 403


def test_an_expired_token_is_refused(gateway, sandbox, monkeypatch):
    from app.gateway.artifacts_store import frame_token

    aid = make(gateway)
    monkeypatch.setattr(frame_token, "SECONDS", -30)
    url = token(gateway, aid)["url"]
    assert gateway.client.get(url, headers=IFRAME).status_code == 403


def test_a_frame_token_is_not_a_session(gateway, sandbox):
    """Purpose-bound key, not the session secret: as a session cookie it is nothing."""
    from fastapi.testclient import TestClient

    aid = make(gateway)
    t = token(gateway, aid)["token"]
    stranger = TestClient(gateway.app)
    stranger.cookies.set("access_token", t)
    assert stranger.get("/api/v1/auth/me").status_code == 401
    assert stranger.get("/api/artifacts").status_code == 401


def test_the_frame_query_never_reaches_the_access_log():
    import logging

    from app.gateway.routers.artifact_store import _RedactFrameQuery

    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d', ("1.2.3.4:5", "GET", "/api/artifacts/a/versions/1/frame.html?t=secret.token&path=x", "1.1", 200), None)
    _RedactFrameQuery().filter(record)
    assert "secret" not in record.getMessage() and "frame.html?[redacted]" in record.getMessage()


def test_the_internal_token_is_refused_on_frame_routes(gateway, sandbox):
    aid = make(gateway)
    headers = {**create_internal_auth_headers(), **IFRAME}
    assert gateway.client.get(f"/api/artifacts/{aid}/versions/1/frame-token", headers=headers).status_code == 403
    assert gateway.client.get(token(gateway, aid)["url"], headers=headers).status_code == 403


def test_content_route_serves_code_as_text_never_as_a_page(gateway, sandbox):
    aid = make(gateway)
    resp = gateway.client.get(f"/api/artifacts/{aid}/versions/1/content")
    assert resp.headers["content-type"].startswith("text/plain") and resp.headers["content-security-policy"] == "default-src 'none'; sandbox"


def test_version_shows_build_and_checks(gateway, sandbox):
    aid = make(gateway, "react", REACT)
    v = gateway.client.get(f"/api/artifacts/{aid}/versions/1").json()
    assert v["source"] == REACT and v["code"]["build_state"] == "ok" and v["code"]["check"]["state"] == "passed"
    assert v["code"]["recipe"]["tool"] == "esbuild"
    shot = gateway.client.get(f"/api/artifacts/{aid}/versions/1/shots/dark.png")
    assert shot.status_code == 200 and shot.headers["content-type"] == "image/png"
    assert gateway.client.get(f"/api/artifacts/{aid}/versions/1/shots/x.png").status_code == 404


def test_a_failed_build_has_no_frame(gateway, sandbox):
    sandbox["ops"].build = lambda files: (1, {}, "error")
    aid = make(gateway, "react", REACT)
    assert gateway.client.get(f"/api/artifacts/{aid}/versions/1/frame-token").status_code == 409


def test_owner_edit_of_html_makes_a_checked_version(gateway, sandbox):
    aid = make(gateway)
    resp = gateway.client.post(f"/api/artifacts/{aid}/versions", json={"base_version": 1, "content": PAGE.replace("Hello", "Edited")})
    assert resp.status_code == 201, resp.text
    v = gateway.store.versions(gateway.user_id, aid)[0]
    assert v["n"] == 2 and v["origin"] == "owner_edit" and v["lineage"] == "user"
    assert v["code"]["check"]["state"] == "passed"  # the background check ran after the response
    bad = gateway.client.post(f"/api/artifacts/{aid}/versions", json={"base_version": 2, "content": "<iframe src=x></iframe>"})
    assert bad.status_code == 422 and gateway.store.get(gateway.user_id, aid)["latest_version"] == 2


def test_rebuild_builds_in_the_background_and_stores_an_owner_version(gateway, sandbox):
    aid = make(gateway, "react", REACT)
    edited = {"entry": "App.tsx", "files": {"App.tsx": "export default () => <p>New</p>;"}}
    resp = gateway.client.post(f"/api/artifacts/{aid}/rebuild", json={"base_version": 1, "content": edited})
    assert resp.status_code == 202, resp.text
    summary = gateway.client.get(f"/api/artifacts/{aid}").json()
    assert summary["latest_version"] == 2 and summary["code"]["build"]["state"] == "done" and summary["code"]["build"]["result_version"] == 2
    v = gateway.client.get(f"/api/artifacts/{aid}/versions/2").json()
    assert v["origin"] == "owner_edit" and v["lineage"] == "user" and v["source"] == edited and v["code"]["check"]["state"] == "passed"
    assert gateway.client.post(f"/api/artifacts/{aid}/rebuild", json={"base_version": 1, "content": edited}).status_code == 409
    assert gateway.client.post(f"/api/artifacts/{aid}/rebuild", json={"base_version": 2, "content": {"entry": "x"}}).status_code == 422


def test_a_live_build_refuses_a_second_one(gateway, sandbox):
    aid = make(gateway, "react", REACT)
    gateway.store.start_build(gateway.user_id, aid, 1)
    resp = gateway.client.post(f"/api/artifacts/{aid}/rebuild", json={"base_version": 1, "content": REACT})
    assert resp.status_code == 409 and resp.json()["detail"]["code"] == "build_running"


def test_check_again_only_for_versions_without_an_answer(gateway, sandbox, monkeypatch):
    monkeypatch.setattr(code_service, "sandbox_factory", lambda t, o: None)
    aid = make(gateway)
    assert gateway.store.get(gateway.user_id, aid)["code"]["check_state"] == "not_checked"
    monkeypatch.setattr(code_service, "sandbox_factory", lambda t, o: sandbox["ops"])
    assert gateway.client.post(f"/api/artifacts/{aid}/versions/1/check").status_code == 202
    assert gateway.store.get(gateway.user_id, aid)["code"]["check_state"] == "passed"
    assert gateway.client.post(f"/api/artifacts/{aid}/versions/1/check").status_code == 409


def test_failing_check_label_and_refusal_log(gateway, sandbox, caplog):
    sandbox["ops"].probe = failing(violations=["connect-src"])
    aid = make(gateway)
    check = gateway.client.get(f"/api/artifacts/{aid}/versions/1").json()["code"]["check"]
    assert check["state"] == "failed" and any("network" in s for s in check["summary"])
    caplog.set_level("INFO")
    assert gateway.client.post(f"/api/artifacts/{aid}/refused", json={"reason": "unknown_type", "type": "fetch"}).status_code == 204
    assert "artifact_message_refused" in caplog.text
    assert gateway.client.post(f"/api/artifacts/{aid}/refused", json={"reason": "Free text here"}).status_code == 422


# -- webapp (the save model's file set) and downloads ----------------------------------

SITE = {
    "index.html": b'<!doctype html><html><head><link rel="stylesheet" href="css/site.css"></head><body><h1 id=home-marker>Home</h1><img src="img/dot.png"><a href="about.html">About</a><script src="js/app.js"></script></body></html>',
    "about.html": b"<!doctype html><html><head></head><body><h1 id=about-marker>About</h1></body></html>",
    "broken.html": b'<!doctype html><script src="https://cdn.example/x.js"></script>',
    "css/site.css": b"h1{color:var(--primary)}",
    "js/app.js": b"document.title='site'",
    "img/dot.png": b"\x89PNG\r\n\x1a\nxx",
    "big/blob.bin": b"x" * (3 * 1024 * 1024),  # in the set, referenced by no page
}


def make_webapp(gateway, files=SITE):
    """Through the save model's own storage (store.create with the bundle)."""
    from app.gateway.artifacts_store import kinds
    from app.gateway.artifacts_store.kinds import Canonical
    from app.gateway.artifacts_store.service import webapp_media_type

    bundle_files = {p: (d, webapp_media_type(p)) for p, d in files.items()}
    manifest = kinds.dumps({"entry": "index.html", "files": {p: {"size": len(d)} for p, (d, _) in sorted(bundle_files.items())}})
    summary, _ = gateway.store.create(
        gateway.user_id,
        kind="webapp",
        title="My site",
        canon=Canonical(manifest, kinds.MEDIA_TYPES["webapp"]),
        bundle=bundle_files,
        lineage="import",
        lineage_source="a file from this chat",
        origin="import",
        thread_id="thread-a",
        saved=True,
    )
    return summary["id"]


def test_webapp_pages_are_inlined_once_at_save_and_served_by_relative_path(gateway, sandbox, monkeypatch):
    aid = make_webapp(gateway)
    c = gateway.client
    pages = {p["path"]: p for p in c.get(f"/api/artifacts/{aid}/versions/1").json()["pages"]}
    assert pages["index.html"]["ok"] and pages["about.html"]["ok"] and not pages["broken.html"]["ok"]
    # The request path never inlines: the stored page is served.
    from app.gateway.apps import bundle as bundle_mod

    def boom(*a, **k):
        raise AssertionError("inlined on the request path")

    monkeypatch.setattr(bundle_mod, "inline", boom)
    home = c.get(token(gateway, aid)["url"], headers=IFRAME)
    assert home.status_code == 200 and "home-marker" in home.text
    doc, hashes = frame.frame_document(gateway.store.page_document(gateway.user_id, aid, 1))
    assert home.content == doc and home.headers["content-security-policy"] == bundle.csp(hashes)
    assert "h1{color:var(--primary)}" in home.text and "data:image/png;base64," in home.text and 'src="js/app.js"' not in home.text
    about = c.get(token(gateway, aid)["url"] + "&path=about.html", headers=IFRAME)
    assert about.status_code == 200 and "about-marker" in about.text
    for bad in ("../index.html", "/index.html", "css/site.css", "js/app.js", "broken.html", "missing.html", "a/../index.html", "about.html%00", "./about.html", "big/blob.bin"):
        resp = c.get(token(gateway, aid)["url"] + "&path=" + bad, headers=IFRAME)
        assert resp.status_code in (403, 404) and "marker" not in resp.text, bad


def test_a_webapp_whose_entry_cannot_be_shown_is_a_failed_build(gateway, sandbox):
    aid = make_webapp(gateway, {"index.html": b'<!doctype html><script src="https://cdn.example/x.js"></script>'})
    v = gateway.client.get(f"/api/artifacts/{aid}/versions/1").json()
    assert v["code"]["build_state"] == "build_failed" and gateway.client.get(f"/api/artifacts/{aid}/versions/1/frame-token").status_code == 409


def test_webapp_page_bound_comes_from_the_page_not_the_set():
    files = {"index.html": b"<p>ok</p>", "huge.html": b'<img src="a.png">', "a.png": b"\x89PNG" + b"x" * (3 * 1024 * 1024)}
    done, failed, _ = frame.webapp_pages(files, "index.html")
    assert "index.html" in done and "huge.html" in failed


def test_download_follows_the_save_model_names(gateway, sandbox):
    import io
    import zipfile

    aid = make(gateway, "react", REACT)
    page = gateway.client.get(f"/api/artifacts/{aid}/versions/1/download")
    assert page.status_code == 200 and page.headers["content-type"] == "application/octet-stream"
    assert page.headers["content-disposition"].startswith('attachment; filename="Page.html"')
    assert page.text.startswith("<!doctype html>" + frame.DOWNLOAD_META)
    src = gateway.client.get(f"/api/artifacts/{aid}/versions/1/download?source=zip")
    zf = zipfile.ZipFile(io.BytesIO(src.content))
    assert zf.namelist() == ["App.tsx"] and zf.read("App.tsx").decode() == REACT["files"]["App.tsx"]
    assert "Page-source.zip" in src.headers["content-disposition"]
    html = make(gateway)
    assert gateway.client.get(f"/api/artifacts/{html}/versions/1/download").text.startswith("<!doctype html>" + frame.DOWNLOAD_META)
    sandbox["ops"].build = lambda files: (1, {}, "error")
    failed = make(gateway, "react", REACT)
    assert gateway.client.get(f"/api/artifacts/{failed}/versions/1/download").status_code == 409
    assert gateway.client.get(f"/api/artifacts/{failed}/versions/1/download?source=zip").status_code == 200
