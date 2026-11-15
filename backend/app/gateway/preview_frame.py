"""The live preview frame: its link, its token and its response headers.

A live preview (a web app the agent runs on a dev server in the thread's
sandbox) is shown in an ``<iframe sandbox="allow-scripts allow-forms">``: an
opaque origin, so nothing the app runs shares this app's origin, storage or
session. A frame like that sends no session cookie on its own requests, so the
link carries its authorization in the path, the way the static preview's
``/artifacts/preview-token/`` route does:

    /api/threads/{thread_id}/previews/{preview_id}/live/{token}/<app path>

The token is ``v1.<expiry>.<signature>``: an HMAC over the owner, the thread,
the preview and the expiry, with a key derived for this one purpose
(auth/derived.py), never the session secret. It opens that one preview's
proxy and nothing else on the gateway; it is not a session and is refused for
any other thread, preview or owner. It lives ``TOKEN_TTL_SECONDS``; the panel
asks for a fresh link before it lapses.

Every response on the link carries ``FRAME_HEADERS``: the same sandbox as a
response header (a link opened on its own is inert too), and the headers the
static preview's token assets use.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import Request, Response

from app.gateway.auth.derived import derived_key

TOKEN_PURPOSE = "live_preview_frame"
TOKEN_VERSION = "v1"
#: The same lifetime as the static preview's token (routers/artifacts.py).
TOKEN_TTL_SECONDS = 10 * 60

#: preview_frame_profile.json: the iframe's sandbox (read by the frontend's
#: rendering specs) and these headers, whose CSP is the same sandbox.
FRAME_HEADERS: dict[str, str] = dict(json.loads((Path(__file__).parent / "preview_frame_profile.json").read_text(encoding="utf-8"))["headers"])

#: Headers of the dev server's own response that the frame headers replace.
_REPLACED_RESPONSE_HEADERS = frozenset(
    {
        "x-content-type-options",
        "referrer-policy",
        "cross-origin-resource-policy",
        "access-control-allow-origin",
        "access-control-allow-credentials",
        "access-control-allow-methods",
        "access-control-allow-headers",
        "access-control-expose-headers",
        "access-control-max-age",
    }
)

#: The link's path, for the auth and CSRF middlewares (no session, no CSRF
#: cookie: the token in the path is the authorization).
LIVE_PATH_RE = re.compile(r"^/api/threads/[A-Za-z0-9_-]+/previews/[A-Za-z0-9_.-]+/live/[^/]+(?:/.*)?$")
_TOKEN_RE = re.compile(r"^v1\.(?P<exp>[0-9]{1,12})\.(?P<sig>[A-Za-z0-9_-]{43})$")
_HEADER_NAME_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")

_EXPIRED_BODY = b'<!doctype html><html><head><meta charset="utf-8"><title>Preview link expired</title></head><body>This preview link has expired. Open the preview again in OmniHarness.</body></html>'
_EXPIRED_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; sandbox",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "private, no-store",
}


def _signature(*, owner_id: str, thread_id: str, preview_id: str, expires: int) -> str:
    message = "|".join((TOKEN_VERSION, owner_id, thread_id, preview_id, str(expires))).encode("utf-8")
    digest = hmac.new(derived_key(TOKEN_PURPOSE), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def mint_token(*, owner_id: str, thread_id: str, preview_id: str, now: float | None = None) -> tuple[str, int]:
    """A token for one preview of one owner's thread, and its expiry (epoch s)."""
    expires = int(now if now is not None else time.time()) + TOKEN_TTL_SECONDS
    signature = _signature(owner_id=owner_id, thread_id=thread_id, preview_id=preview_id, expires=expires)
    return f"{TOKEN_VERSION}.{expires}.{signature}", expires


def token_valid(token: str, *, owner_id: str, thread_id: str, preview_id: str, now: float | None = None) -> bool | None:
    """True for a token of exactly this owner, thread and preview that has not
    expired; None for one that WAS valid and has expired; False otherwise. The
    signature is compared in constant time."""
    match = _TOKEN_RE.fullmatch(token)
    if match is None:
        return False
    expires = int(match.group("exp"))
    expected = _signature(owner_id=owner_id, thread_id=thread_id, preview_id=preview_id, expires=expires)
    if not hmac.compare_digest(expected.encode("ascii"), match.group("sig").encode("ascii")):
        return False
    if expires <= int(now if now is not None else time.time()):
        return None
    return True


def frame_root(*, thread_id: str, preview_id: str, token: str) -> str:
    """The link's root (no trailing slash): the proxy root the shim rewrites to."""
    return f"/api/threads/{quote(thread_id, safe='')}/previews/{quote(preview_id, safe='')}/live/{quote(token, safe='')}"


def expired_response() -> Response:
    return Response(_EXPIRED_BODY, status_code=401, media_type="text/html; charset=utf-8", headers=_EXPIRED_HEADERS)


def _cors_headers(request: Request) -> dict[str, str]:
    # The frame's origin is opaque ("null"), so its loads of module scripts and
    # its fetches are cross-origin. Nothing on this link reads a cookie (the
    # proxy drops them toward the dev server), so answering the frame is safe;
    # the token in the path is what authorizes.
    if request.headers.get("origin") == "null":
        return {"Access-Control-Allow-Origin": "null", "Access-Control-Allow-Credentials": "true", "Vary": "Origin"}
    return {"Access-Control-Allow-Origin": "*"}


def is_preflight(request: Request) -> bool:
    return request.method == "OPTIONS" and "access-control-request-method" in request.headers


def preflight_response(request: Request) -> Response:
    """A CORS preflight from the frame, answered here (the dev server never
    sees one when the app is served same-origin, as it was meant to be)."""
    method = request.headers.get("access-control-request-method", "GET")
    if not _HEADER_NAME_RE.fullmatch(method):
        method = "GET"
    requested = [name.strip() for name in request.headers.get("access-control-request-headers", "").split(",") if name.strip()]
    allowed = ", ".join(name for name in requested if _HEADER_NAME_RE.fullmatch(name))
    headers = {**FRAME_HEADERS, **_cors_headers(request), "Access-Control-Allow-Methods": method, "Access-Control-Max-Age": "600"}
    if allowed:
        headers["Access-Control-Allow-Headers"] = allowed
    return Response(status_code=204, headers=headers)


def frame_response_headers(headers: dict[str, str], request: Request) -> dict[str, str]:
    """The dev server's response headers with the frame's set on top. A
    Content-Security-Policy of its own is kept beside the sandbox (both apply)."""
    out: dict[str, str] = {}
    upstream_csp = ""
    upstream_vary = ""
    for key, value in headers.items():
        lowered = key.lower()
        if lowered in _REPLACED_RESPONSE_HEADERS:
            continue
        if lowered == "content-security-policy":
            upstream_csp = value
            continue
        if lowered == "vary":
            upstream_vary = value
            continue
        out[key] = value
    out.update(FRAME_HEADERS)
    if upstream_csp:
        out["Content-Security-Policy"] = f"{FRAME_HEADERS['Content-Security-Policy']}, {upstream_csp}"
    cors = _cors_headers(request)
    vary = ", ".join(v for v in (upstream_vary, cors.pop("Vary", "")) if v)
    out.update(cors)
    if vary:
        out["Vary"] = vary
    return out
