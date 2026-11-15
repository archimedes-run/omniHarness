"""The live preview's frame link (app/gateway/preview_frame.py).

The live preview runs in a sandboxed frame (an opaque origin). Its link
carries a short-lived token bound to one owner, thread and preview; every
response on it carries the frame's sandbox as a header; the token opens that
preview and nothing else, and is never a session. Real HTTP through the
previews router, a fake sandbox standing in for the dev server.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_preview_sessions_router import _FakeAioSandbox, _make_preview_app, _make_user, preview_test_context  # noqa: F401

from app.gateway import preview_frame
from app.gateway.preview_frame import LIVE_PATH_RE, mint_token, token_valid

os.environ.setdefault("AUTH_JWT_SECRET", "test-secret-key-live-preview-frame-min-32")

ROOT = Path(__file__).resolve().parents[2]
OWNER = "00000000-0000-4000-8000-000000000001"


class _DevServer(_FakeAioSandbox):
    """The dev server: a Vite-style page, its module, a stylesheet, its own
    API, a redirect, and a record of every request it saw."""

    def __init__(self) -> None:
        super().__init__()
        self.seen: list[dict[str, Any]] = []

    def fetch_local_url(self, *, port, path, method="GET", headers=None, body=None, timeout=30):
        self.seen.append({"path": path, "method": method, "headers": dict(headers or {}), "body": body})
        if path.startswith("/src/main.js"):
            return {"status": 200, "headers": {"content-type": "text/javascript"}, "body": b'import "/src/app.js";\nimport("/src/lazy.js");'}
        if path.startswith("/src/style.css"):
            return {"status": 200, "headers": {"content-type": "text/css", "content-security-policy": "img-src 'self'"}, "body": b"body{background:url(/src/bg.png)}"}
        if path.startswith("/api/items"):
            return {"status": 200, "headers": {"content-type": "application/json", "access-control-allow-origin": "https://elsewhere.example", "x-content-type-options": "sniff-please"}, "body": b'{"items":[1]}'}
        if path.startswith("/old"):
            return {"status": 302, "headers": {"location": "http://127.0.0.1:3000/new"}, "body": b""}
        return {
            "status": 200,
            "headers": {"content-type": "text/html; charset=utf-8", "set-cookie": "dev=1"},
            "body": (
                b'<!doctype html><html><head><script type="module" src="/@vite/client"></script><link rel="stylesheet" href="/src/style.css"></head>'
                b'<body><div id="app">preview-ok</div><script type="module" src="/src/main.js"></script></body></html>'
            ),
        }


@pytest.fixture()
def ctx(preview_test_context, monkeypatch):  # noqa: F811
    dev = _DevServer()
    preview_test_context["provider"]._sandbox = dev
    app = _make_preview_app(user=preview_test_context["user"], manager=preview_test_context["manager"])
    client = TestClient(app)
    client.__enter__()
    preview_id = client.post(
        "/api/threads/thread-1/previews",
        json={"artifact_id": "dynamic-app", "root_path": "/mnt/user-data/workspace/dynamic-app", "command": "npm run dev", "port": 3000},
    ).json()["id"]
    link = client.post(f"/api/threads/thread-1/previews/{preview_id}/frame").json()
    yield {"client": client, "dev": dev, "preview_id": preview_id, "link": link, "root": link["frame_url"], "manager": preview_test_context["manager"], "context": preview_test_context}
    client.__exit__(None, None, None)


def _token(root: str) -> str:
    return root.rsplit("/", 1)[1]


# ── the token ──────────────────────────────────────────────────────────────


def test_a_token_opens_exactly_its_owner_thread_and_preview():
    token, expires = mint_token(owner_id="u1", thread_id="t1", preview_id="p1")
    assert re.fullmatch(r"v1\.\d+\.[A-Za-z0-9_-]{43}", token)
    assert expires - time.time() == pytest.approx(preview_frame.TOKEN_TTL_SECONDS, abs=2)
    assert token_valid(token, owner_id="u1", thread_id="t1", preview_id="p1") is True
    assert token_valid(token, owner_id="u2", thread_id="t1", preview_id="p1") is False
    assert token_valid(token, owner_id="u1", thread_id="t2", preview_id="p1") is False
    assert token_valid(token, owner_id="u1", thread_id="t1", preview_id="p2") is False


def test_a_token_lapses_and_cannot_be_stretched_or_forged():
    token, expires = mint_token(owner_id="u1", thread_id="t1", preview_id="p1", now=1_000)
    assert token_valid(token, owner_id="u1", thread_id="t1", preview_id="p1", now=expires - 1) is True
    assert token_valid(token, owner_id="u1", thread_id="t1", preview_id="p1", now=expires) is None
    version, exp, sig = token.split(".")
    stretched = f"{version}.{int(exp) + 3600}.{sig}"
    flipped = f"{version}.{exp}.{'A' if sig[0] != 'A' else 'B'}{sig[1:]}"
    for bad in (stretched, flipped, f"v2.{exp}.{sig}", token + "x", "", "v1..", "../../x", f"{version}.{exp}"):
        assert token_valid(bad, owner_id="u1", thread_id="t1", preview_id="p1", now=1_001) is False, bad


def test_the_signature_is_compared_in_constant_time(monkeypatch):
    calls = []
    real = preview_frame.hmac.compare_digest
    monkeypatch.setattr(preview_frame.hmac, "compare_digest", lambda a, b: calls.append((a, b)) or real(a, b))
    token, _ = mint_token(owner_id="u1", thread_id="t1", preview_id="p1")
    token_valid(token, owner_id="u1", thread_id="t1", preview_id="p1")
    assert len(calls) == 1


def test_the_key_is_derived_for_this_purpose_never_the_session_secret():
    import base64
    import hashlib
    import hmac

    from app.gateway.auth.config import get_auth_config
    from app.gateway.auth.derived import derived_key

    token, expires = mint_token(owner_id="u1", thread_id="t1", preview_id="p1")
    message = f"v1|u1|t1|p1|{expires}".encode()
    sig = token.rsplit(".", 1)[1]
    by_session_secret = base64.urlsafe_b64encode(hmac.new(get_auth_config().jwt_secret.encode(), message, hashlib.sha256).digest()).decode().rstrip("=")
    by_other_purpose = base64.urlsafe_b64encode(hmac.new(derived_key("artifact_preview"), message, hashlib.sha256).digest()).decode().rstrip("=")
    assert sig not in (by_session_secret, by_other_purpose)
    assert preview_frame.TOKEN_PURPOSE == "live_preview_frame"


def test_a_token_is_not_a_session():
    from app.gateway.auth.errors import TokenError
    from app.gateway.auth.jwt import decode_token

    token, _ = mint_token(owner_id="u1", thread_id="t1", preview_id="p1")
    assert decode_token(token) == TokenError.MALFORMED


def test_the_session_cookie_set_to_a_token_is_refused_by_the_gateway():
    """Presented as the access cookie on any other route, the token is refused
    (the production auth middleware, real JWT decoding)."""
    from fastapi import FastAPI

    from app.gateway.auth_middleware import AuthMiddleware

    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.get("/api/memory")
    async def memory():
        return {"secret": "owner"}

    token, _ = mint_token(owner_id=OWNER, thread_id="thread-1", preview_id="p1")
    with TestClient(app) as client:
        client.cookies.set("access_token", token)
        resp = client.get("/api/memory")
    assert resp.status_code == 401 and b"owner" not in resp.content


# ── what the token opens ───────────────────────────────────────────────────


def test_the_link_path_is_the_only_public_and_csrf_free_preview_path():
    from starlette.requests import Request

    from app.gateway.auth_middleware import _is_public
    from app.gateway.csrf_middleware import should_check_csrf

    def post(path: str) -> Request:
        return Request({"type": "http", "method": "POST", "path": path, "headers": [], "query_string": b""})

    for path in ("/api/threads/t-1/previews/preview_t-1_app.v2_1/live/v1.9.sig", "/api/threads/t-1/previews/p/live/v1.9.sig/src/main.js"):
        assert _is_public(path) and not should_check_csrf(post(path)), path
    for path in (
        "/api/threads/t-1/previews",
        "/api/threads/t-1/previews/p",
        "/api/threads/t-1/previews/p/frame",
        "/api/threads/t-1/previews/p/logs",
        "/api/threads/t-1/previews/p/proxy/x",
        "/api/threads/t-1/previews/p/live",
        "/api/threads/t-1/previews/p/live/",
        "/api/threads/t-1/runs/live/v1.9.sig",
        "/api/threads/t/1/previews/p/live/x",
    ):
        assert not _is_public(path) and should_check_csrf(post(path)), path


def test_in_the_real_app_the_link_path_reaches_only_the_preview_frame_route():
    """Every route of the production app that matches a frame-link path is the
    frame route itself: the token cannot be aimed at any other handler."""
    from starlette.routing import Match

    from app.gateway.app import create_app

    app = create_app()
    for path in ("/api/threads/t1/previews/p1/live/v1.1.x", "/api/threads/t1/previews/p1/live/v1.1.x/api/memory", "/api/threads/t1/previews/p1/live/v1.1.x/../../logs"):
        assert LIVE_PATH_RE.match(path)
        for method in ("GET", "POST", "DELETE"):
            scope = {"type": "http", "method": method, "path": path, "root_path": "", "query_string": b"", "headers": []}
            names = [getattr(route, "name", "") for route in app.routes if route.matches(scope)[0] == Match.FULL]
            assert names and set(names) == {"proxy_preview_frame"}, (path, method, names)


def test_the_link_is_refused_for_another_preview_thread_or_owner(ctx):
    client, manager, token = ctx["client"], ctx["manager"], _token(ctx["root"])
    other_owner = _make_user("other@example.com", "00000000-0000-4000-8000-000000000002")
    session = manager._sessions[ctx["preview_id"]]
    # A second preview of the same owner and thread.
    twin = type(session)(**{**session.__dict__, "id": "preview_twin", "client_errors": []})
    manager._sessions[twin.id] = twin
    assert client.get(f"/api/threads/thread-1/previews/preview_twin/live/{token}/").status_code == 404
    assert client.get(f"/api/threads/thread-2/previews/{ctx['preview_id']}/live/{token}/").status_code == 404
    session.user_id = str(other_owner.id)  # the same preview id, another owner
    assert client.get(f"/api/threads/thread-1/previews/{ctx['preview_id']}/live/{token}/").status_code == 404
    session.user_id = OWNER
    assert client.get(f"{ctx['root']}/").status_code == 200  # positive control
    assert not any(b"preview-ok" in client.get(f"/api/threads/thread-1/previews/preview_twin/live/{token}/{p}").content for p in ("", "index.html"))


def test_an_expired_link_gets_an_inert_page(ctx, monkeypatch):
    client = ctx["client"]
    seen_before = len(ctx["dev"].seen)
    real = time.time
    monkeypatch.setattr(preview_frame.time, "time", lambda: real() + preview_frame.TOKEN_TTL_SECONDS + 5)
    resp = client.get(f"{ctx['root']}/")
    assert resp.status_code == 401 and b"preview-ok" not in resp.content
    assert "sandbox" in resp.headers["content-security-policy"] and "default-src 'none'" in resp.headers["content-security-policy"]
    assert len(ctx["dev"].seen) == seen_before  # never forwarded


def test_only_the_owner_mints_a_link_for_an_existing_preview(ctx):
    other = _make_user("other@example.com", "00000000-0000-4000-8000-000000000002")
    app = _make_preview_app(user=other, manager=ctx["manager"])
    with TestClient(app) as stranger:
        assert stranger.post(f"/api/threads/thread-1/previews/{ctx['preview_id']}/frame").status_code == 404
    assert ctx["client"].post("/api/threads/thread-1/previews/preview_nope/frame").status_code == 404
    link = ctx["link"]
    assert link["expires_at"].endswith("Z") or "+" in link["expires_at"]


def test_a_fresh_link_is_another_token_for_the_same_preview(ctx, monkeypatch):
    real = time.time
    monkeypatch.setattr(preview_frame.time, "time", lambda: real() + 5)
    again = ctx["client"].post(f"/api/threads/thread-1/previews/{ctx['preview_id']}/frame").json()["frame_url"]
    assert again != ctx["root"] and again.rsplit("/", 1)[0] == ctx["root"].rsplit("/", 1)[0]
    assert ctx["client"].get(f"{again}/").status_code == 200


# ── what the link serves ───────────────────────────────────────────────────


def _assert_frame_headers(resp, *, origin_null: bool = False) -> None:
    assert resp.headers["content-security-policy"].startswith("sandbox allow-scripts allow-forms")
    assert "allow-same-origin" not in resp.headers["content-security-policy"]
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert resp.headers["cross-origin-resource-policy"] == "cross-origin"
    assert resp.headers["access-control-allow-origin"] == ("null" if origin_null else "*")


def test_the_profile_sandbox_is_the_header_sandbox_and_never_same_origin():
    profile = json.loads((ROOT / "backend/app/gateway/preview_frame_profile.json").read_text())
    assert profile["headers"] == preview_frame.FRAME_HEADERS
    assert profile["headers"]["Content-Security-Policy"] == f"sandbox {profile['sandbox']}"
    flags = set(profile["sandbox"].split())
    assert flags == {"allow-scripts", "allow-forms"}
    assert not flags & {"allow-same-origin", "allow-top-navigation", "allow-popups-to-escape-sandbox"}


def test_every_response_carries_the_frame_headers(ctx):
    client, root = ctx["client"], ctx["root"]
    html = client.get(f"{root}/")
    script = client.get(f"{root}/src/main.js", headers={"Origin": "null"})
    css = client.get(f"{root}/src/style.css")
    api = client.get(f"{root}/api/items", headers={"Origin": "null"})
    redirect = client.get(f"{root}/old", follow_redirects=False)
    report = client.post(f"{root}/__omni_preview__/client-error", content=b'{"type":"error","message":"x"}', headers={"Origin": "null", "Content-Type": "text/plain"})
    preflight = client.options(f"{root}/api/items", headers={"Origin": "null", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type, x-app"})
    for resp, null in ((html, False), (script, True), (css, False), (api, True), (redirect, False), (report, True), (preflight, True)):
        _assert_frame_headers(resp, origin_null=null)
    assert html.status_code == 200 and "set-cookie" not in html.headers
    assert css.headers["content-security-policy"] == "sandbox allow-scripts allow-forms, img-src 'self'"  # the server's own kept beside it
    assert api.headers["access-control-allow-credentials"] == "true" and "Origin" in api.headers["vary"]
    assert redirect.status_code == 302 and redirect.headers["location"] == f"{root}/new"
    assert report.status_code == 204
    assert preflight.status_code == 204 and preflight.headers["access-control-allow-methods"] == "POST"
    assert preflight.headers["access-control-allow-headers"] == "content-type, x-app"
    assert not any(seen["method"] == "OPTIONS" for seen in ctx["dev"].seen)  # answered here


def test_the_page_is_rewritten_onto_the_link_with_its_shims(ctx):
    client, root = ctx["client"], ctx["root"]
    html = client.get(f"{root}/").text
    assert f'<base href="{root}/" data-omni-preview>' in html
    assert f'src="{root}/@vite/client"' in html and f'href="{root}/src/style.css"' in html and f'src="{root}/src/main.js"' in html
    # The storage stand-in, then the proxy shim with this link's root, before
    # any script of the app's own.
    head = html.split("<head>", 1)[1]
    assert head.index("<base") < head.index("memoryStorage") < head.index(json.dumps(root)) < head.index("/@vite/client")
    assert "omniharness:preview-root" in html
    script = client.get(f"{root}/src/main.js").text
    assert f'import "{root}/src/app.js"' in script and f'import("{root}/src/lazy.js")' in script
    assert f"url({root}/src/bg.png)" in client.get(f"{root}/src/style.css").text


def test_the_dev_server_sees_no_cookie_no_origin_and_no_link(ctx):
    client, root, dev = ctx["client"], ctx["root"], ctx["dev"]
    client.cookies.set("access_token", "owner-session")
    client.get(f"{root}/src/main.js", headers={"Origin": "null", "Referer": f"http://testserver{root}/", "Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "script"})
    seen = dev.seen[-1]
    assert seen["path"] == "/src/main.js"
    lowered = {k.lower(): v for k, v in seen["headers"].items()}
    for name in ("cookie", "origin", "referer", "sec-fetch-site", "sec-fetch-mode", "sec-fetch-dest", "host"):
        assert name not in lowered, name
    assert _token(root) not in json.dumps(seen)


def test_the_sandbox_is_reached_as_the_previews_owner(ctx, monkeypatch):
    """No session on the link, so the route stands in the preview's owner for
    the request: the sandbox provider resolves the thread's data by it."""
    from omniharness.runtime.user_context import get_effective_user_id

    seen = []
    real = ctx["manager"]._get_sandbox_for_existing_session_sync

    def spy(session):
        seen.append(get_effective_user_id())
        return real(session)

    monkeypatch.setattr(ctx["manager"], "_get_sandbox_for_existing_session_sync", spy)
    assert ctx["client"].get(f"{ctx['root']}/src/main.js").status_code == 200
    assert seen == [OWNER]
    assert get_effective_user_id() != OWNER  # and only for that request


def test_the_app_can_post_to_its_own_server_through_the_link(ctx):
    resp = ctx["client"].post(f"{ctx['root']}/api/items", content=b'{"a":1}', headers={"Origin": "null", "Content-Type": "application/json"})
    assert resp.status_code == 200 and ctx["dev"].seen[-1]["method"] == "POST" and ctx["dev"].seen[-1]["body"] == b'{"a":1}'


def test_client_errors_from_the_frame_reach_the_preview_record(ctx):
    resp = ctx["client"].post(f"{ctx['root']}/__omni_preview__/client-error", content=b'{"type":"error","message":"boom"}', headers={"Content-Type": "text/plain"})
    assert resp.status_code == 204
    assert ctx["manager"]._sessions[ctx["preview_id"]].client_errors[-1]["message"] == "boom"


# ── the token in logs ──────────────────────────────────────────────────────


def test_the_gateway_log_filter_redacts_the_link_token():
    from app.gateway.logging_filters import PreviewTokenRedactionFilter, mask_preview_token_urls

    token, _ = mint_token(owner_id="u1", thread_id="t1", preview_id="p1")
    for raw, kept in (
        (f'"GET /api/threads/t1/previews/preview_t1_app_1/live/{token}/src/main.js?v=1 HTTP/1.1" 200', "/live/[redacted]/src/main.js?v=1 HTTP/1.1"),
        (f'"GET /api/threads/t1/previews/p1/live/{token} HTTP/1.1" 200', "/live/[redacted] HTTP/1.1"),
        (f'"GET /api/threads/t1/previews/p1/live/{token}/page/frame.html?x=1 HTTP/1.1" 200', "/live/[redacted]/page/frame.html"),
    ):
        out = mask_preview_token_urls(raw)
        assert token not in out and token.split(".")[2] not in out and kept in out, out
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d', ("1.2.3.4", "GET", f"/api/threads/t1/previews/p1/live/{token}/", "1.1", 200), None)
    PreviewTokenRedactionFilter().filter(record)
    assert token not in record.getMessage()


@pytest.mark.parametrize("conf", ["docker/nginx/nginx.conf", "docker/nginx/nginx.local.conf"])
def test_nginx_logs_the_link_without_its_token(conf):
    """Replays the access log's map with Python's engine (PCRE agrees on these
    patterns): the first matching line wins, as in nginx."""
    text = (ROOT / conf).read_text()
    block = re.search(r"map \$request_uri \$safe_request_uri \{(.*?)\n    \}", text, re.S).group(1)
    rules = [ln.strip().rstrip(";") for ln in block.splitlines() if ln.strip().startswith("~")]

    def logged(uri: str) -> str:
        for rule in rules:
            pattern, repl = rule[1:].split(" ", 1)
            m = re.match(pattern.replace("(?<", "(?P<"), uri)
            if m:
                return re.sub(r"\$(\w+)", lambda v: m.group(v.group(1)) or "", repl)
        return uri

    token, _ = mint_token(owner_id="u1", thread_id="t1", preview_id="p1")
    for uri, expected in (
        (f"/api/threads/t1/previews/p1/live/{token}/src/main.js?v=1", "/api/threads/t1/previews/p1/live/[redacted]/src/main.js?v=1"),
        (f"/api/threads/t1/previews/p1/live/{token}", "/api/threads/t1/previews/p1/live/[redacted]"),
        (f"/api/threads/t1/previews/p1/live/{token}/frame.html?t=1", "/api/threads/t1/previews/p1/live/[redacted]/frame.html?t=1"),
        (f"/api/threads/t1/previews/p1/live/{token}/artifacts/preview-token/x/y", "/api/threads/t1/previews/p1/live/[redacted]/artifacts/preview-token/x/y"),
    ):
        assert logged(uri) == expected
    # The existing redactions are unchanged.
    assert logged("/api/threads/t1/artifacts/preview-token/SECRET/mnt/a.js") == "/api/threads/t1/artifacts/preview-token/[redacted]/mnt/a.js"
    assert logged("/api/artifacts/a/versions/1/frame.html?t=SECRET") == "/api/artifacts/a/versions/1/frame.html?[redacted]"
    assert logged("/api/threads/t1/previews/p1/logs") == "/api/threads/t1/previews/p1/logs"
