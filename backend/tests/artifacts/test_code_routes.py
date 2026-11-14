"""The locked frame's routes and the owner's code-kind actions (Spec 012 Slice 2),
through create_app() and its real lifespan, owner signed in."""

from __future__ import annotations

import pytest
from fake_sandbox import FakeSandbox, failing
from langchain_core.messages import AIMessage

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
    url = token(gateway, aid)["url"]
    ok = c.get(url, headers=IFRAME)
    assert ok.status_code == 200
    assert ok.headers["content-security-policy"] == frame.CSP
    for name, value in frame.HEADERS.items():
        assert ok.headers[name] == value, name
    assert ok.headers["content-type"] == "text/html; charset=utf-8"
    assert ok.text.index("<script>") < ok.text.index("secret-marker")
    assert frame.SHIM[:60] in ok.text
    # Anything else is inert: a top-level open, a fetch, another site, no or a bad token.
    for headers in ({}, {**IFRAME, "Sec-Fetch-Dest": "document"}, {**IFRAME, "Sec-Fetch-Dest": "empty"}, {**IFRAME, "Sec-Fetch-Site": "cross-site"}, {**IFRAME, "Sec-Fetch-Site": "same-site"}):
        resp = c.get(url, headers=headers)
        assert resp.status_code == 403 and "secret-marker" not in resp.text, headers
        assert resp.headers["content-security-policy"].startswith("default-src 'none'") and "sandbox" in resp.headers["content-security-policy"]
    bare = f"/api/artifacts/{aid}/versions/1/frame.html"
    assert "secret-marker" not in c.get(bare, headers=IFRAME).text
    assert "secret-marker" not in c.get(bare + "?t=forged", headers=IFRAME).text


def test_a_token_is_bound_to_owner_artifact_and_version(gateway, sandbox):
    a = make(gateway)
    b = make(gateway, content=PAGE.replace("Hello", "Other"))
    c = gateway.client
    t_a = token(gateway, a)["token"]
    assert "secret-marker" not in c.get(f"/api/artifacts/{b}/versions/1/frame.html?t={t_a}", headers=IFRAME).text
    gateway.store.add_version(gateway.user_id, a, base_version=1, canon=frame.canonical_html(PAGE + " ")[0], lineage="user", lineage_source=None, origin="owner_edit", code={})
    assert c.get(f"/api/artifacts/{a}/versions/2/frame.html?t={t_a}", headers=IFRAME).status_code == 403


def test_an_expired_token_is_refused(gateway, sandbox, monkeypatch):
    import app.gateway.routers.artifact_store as routes

    aid = make(gateway)
    monkeypatch.setattr(routes, "FRAME_TOKEN_SECONDS", -30)
    url = token(gateway, aid)["url"]
    assert gateway.client.get(url, headers=IFRAME).status_code == 403


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


# -- webapp (a stored file set) and downloads (owner update) -----------------------------

SITE = {
    "index.html": b'<!doctype html><html><head><link rel="stylesheet" href="css/site.css"></head><body><h1 id=home-marker>Home</h1><img src="img/dot.png"><a href="about.html">About</a><script src="js/app.js"></script></body></html>',
    "about.html": b"<!doctype html><html><head></head><body><h1 id=about-marker>About</h1></body></html>",
    "css/site.css": b"h1{color:var(--primary)}",
    "js/app.js": b"document.title='site'",
    "img/dot.png": b"\x89PNG\r\n\x1a\nxx",
}


def make_webapp(gateway, files=SITE):
    canon, findings = frame.canonical_webapp(files, "index.html")
    code = {"findings": findings, "recipe": {"tool": "none", "kind": "webapp"}}
    summary, _ = gateway.store.create(gateway.user_id, kind="webapp", title="My site", canon=canon, lineage="user", lineage_source=None, origin="tool", thread_id="thread-a", code=code)
    return summary["id"]


def test_webapp_pages_are_served_inlined_by_relative_path(gateway, sandbox):
    aid = make_webapp(gateway)
    c = gateway.client
    url = token(gateway, aid)["url"]
    home = c.get(url, headers=IFRAME)
    assert home.status_code == 200 and "home-marker" in home.text
    assert home.headers["content-security-policy"] == frame.CSP
    assert "h1{color:var(--primary)}" in home.text and "data:image/png;base64," in home.text and "document.title='site'" in home.text
    assert 'href="css/site.css"' not in home.text and 'src="js/app.js"' not in home.text
    about = c.get(url + "&path=about.html", headers=IFRAME)
    assert about.status_code == 200 and "about-marker" in about.text and about.headers["content-security-policy"] == frame.CSP
    for bad in ("../index.html", "/index.html", "css/site.css", "js/app.js", "missing.html", "a/../index.html", "about.html%00", ".hidden.html", "about.html/"):
        resp = c.get(url + "&path=" + bad, headers=IFRAME)
        assert resp.status_code in (403, 404) and "marker" not in resp.text, bad
    # Without the iframe headers a page is inert too.
    assert "about-marker" not in c.get(url + "&path=about.html").text
    v = c.get(f"/api/artifacts/{aid}/versions/1").json()
    assert v["webapp"]["entry"] == "index.html" and {f["path"] for f in v["webapp"]["files"]} == set(SITE)
    assert v["code"]["check"]["state"] in ("pending", "passed", "not_checked")


@pytest.mark.parametrize(
    "files, entry",
    [
        ({"../x.html": b"x"}, "../x.html"),
        ({"/abs.html": b"x"}, "/abs.html"),
        ({"a\\b.html": b"x"}, "a\\b.html"),
        ({"index.html": b"<iframe src=x></iframe>"}, "index.html"),
        ({"index.html": b"<img src='https://x/y.png'><script src='https://cdn/x.js'></script>"}, "index.html"),
        ({"style.css": b"x"}, "style.css"),
        ({"index.html": b"x"}, "other.html"),
    ],
)
def test_webapp_sets_are_refused_when_unsafe(files, entry):
    from app.gateway.artifacts_store.kinds import InvalidContent

    with pytest.raises(InvalidContent):
        frame.canonical_webapp(files, entry)


def test_webapp_size_cap():
    from app.gateway.artifacts_store import caps
    from app.gateway.artifacts_store.kinds import TooLarge

    with pytest.raises(TooLarge):
        frame.canonical_webapp({"index.html": b"<p>x</p>", "big.bin": b"x" * caps.WEBAPP_FILES_BYTES}, "index.html")


def test_download_page_and_source(gateway, sandbox):
    import io
    import zipfile

    aid = make(gateway, "react", REACT)
    page = gateway.client.get(f"/api/artifacts/{aid}/versions/1/download?form=page")
    assert page.status_code == 200 and page.headers["content-type"] == "application/octet-stream"
    assert page.headers["content-disposition"].startswith("attachment;") and page.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert page.text.index("Content-Security-Policy") < page.text.index("<script")
    src = gateway.client.get(f"/api/artifacts/{aid}/versions/1/download?form=source")
    zf = zipfile.ZipFile(io.BytesIO(src.content))
    assert zf.namelist() == ["App.tsx"] and zf.read("App.tsx").decode() == REACT["files"]["App.tsx"]
    site = make_webapp(gateway)
    names = zipfile.ZipFile(io.BytesIO(gateway.client.get(f"/api/artifacts/{site}/versions/1/download?form=source").content)).namelist()
    assert sorted(names) == sorted(SITE) and all(not n.startswith("/") and ".." not in n for n in names)
    sandbox["ops"].build = lambda files: (1, {}, "error")
    failed = make(gateway, "react", REACT)
    assert gateway.client.get(f"/api/artifacts/{failed}/versions/1/download?form=page").status_code == 409
    assert gateway.client.get(f"/api/artifacts/{failed}/versions/1/download?form=source").status_code == 200
