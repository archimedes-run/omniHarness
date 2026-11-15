"""Fetch Metadata rules for routes that may answer with model-authored HTML.

A cookie-authenticated document request that another site (or an opaque-origin
frame, such as an artifact's locked frame navigating itself) starts is refused
by the server, not only by the browser's SameSite handling. A request without
the headers (an older client, curl) is judged as before.
"""

from __future__ import annotations

from fastapi import Request, Response

NAVIGATION_DESTS = frozenset({"iframe", "document", "frame", "object", "embed"})
TRUSTED_SITES = frozenset({"same-origin", "none"})

#: What a refused navigation gets: nothing that runs, nothing of the content.
REFUSED_BODY = b'<!doctype html><html><head><meta charset="utf-8"><title>Not here</title></head><body>Open this in OmniHarness.</body></html>'
REFUSED_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; sandbox; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "private, no-store",
}


def cross_site_navigation(request: Request) -> bool:
    """A frame or page navigation that this origin did not start (the
    Sec-Fetch-Site header present and neither same-origin nor none)."""
    dest = request.headers.get("sec-fetch-dest")
    site = request.headers.get("sec-fetch-site")
    return dest in NAVIGATION_DESTS and site is not None and site not in TRUSTED_SITES


def own_frame_request(request: Request) -> bool:
    """The stricter rule of the artifact frame route: this app's own iframe."""
    return request.headers.get("sec-fetch-dest") == "iframe" and request.headers.get("sec-fetch-site") == "same-origin"


def refused_navigation() -> Response:
    return Response(REFUSED_BODY, status_code=403, media_type="text/html; charset=utf-8", headers=REFUSED_HEADERS)
