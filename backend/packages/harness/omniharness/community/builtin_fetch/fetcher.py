"""GET a page through the fetch egress proxy, with hard caps.

* Every request goes to the configured proxy; environment proxies are ignored
  (``trust_env=False``) and with no proxy configured nothing is fetched.
* Redirects are never followed by the HTTP client: each hop is checked by
  ``guard`` again and requested through the proxy again, at most 5 hops.
* 2 MB body (counted after decompression, and before it), 15 s for the whole
  fetch including every hop.
"""

from __future__ import annotations

import asyncio
import zlib
from dataclasses import dataclass, field
from urllib.parse import urljoin

import httpx

from omniharness.community.builtin_fetch.guard import (
    FetchFailed,
    FetchRefused,
    IPNetwork,
    check_url,
    resolve_and_check,
)

MAX_BYTES_CAP = 2 * 1024 * 1024
TIMEOUT_CAP = 15.0
MAX_REDIRECTS_CAP = 5
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

#: Content the extractor can turn into text. Anything else (PDF, images,
#: archives) is a failure, so a configured fallback can try it.
TEXT_TYPES = frozenset(
    {
        "text/html",
        "application/xhtml+xml",
        "text/plain",
        "text/markdown",
        "text/xml",
        "application/xml",
        "application/json",
        "text/csv",
    }
)

USER_AGENT = "Mozilla/5.0 (compatible; OmniHarness-WebFetch/1.0; +https://github.com/archimedes-run/omniHarness)"
_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
    # Never br/zstd: those are decoded here, bounded, and only gzip/deflate are.
    "Accept-Encoding": "gzip, deflate",
}


@dataclass(frozen=True)
class FetchSettings:
    proxy: str | None
    timeout: float = TIMEOUT_CAP
    max_bytes: int = MAX_BYTES_CAP
    max_redirects: int = MAX_REDIRECTS_CAP
    extra_blocked: tuple[IPNetwork, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        # Config can lower the caps, never raise them.
        object.__setattr__(self, "timeout", min(max(float(self.timeout), 0.1), TIMEOUT_CAP))
        object.__setattr__(self, "max_bytes", min(max(int(self.max_bytes), 1), MAX_BYTES_CAP))
        object.__setattr__(self, "max_redirects", min(max(int(self.max_redirects), 0), MAX_REDIRECTS_CAP))


@dataclass(frozen=True)
class FetchResult:
    url: str
    status: int
    content_type: str
    charset: str | None
    body: bytes
    truncated: bool


def _media_type(content_type: str) -> tuple[str, str | None]:
    media, _, params = content_type.partition(";")
    charset = None
    for param in params.split(";"):
        key, _, value = param.strip().partition("=")
        if key.lower() == "charset" and value:
            charset = value.strip().strip('"').lower() or None
    return media.strip().lower(), charset


def _decoder(encoding: str):
    encoding = encoding.strip().lower()
    if encoding in ("", "identity"):
        return None
    if encoding in ("gzip", "x-gzip"):
        return zlib.decompressobj(16 + zlib.MAX_WBITS)
    if encoding == "deflate":
        return zlib.decompressobj()
    raise FetchFailed(f"unsupported content encoding {encoding!r}")


async def read_capped(response: httpx.Response, max_bytes: int) -> tuple[bytes, bool]:
    """Read at most ``max_bytes`` of body, then stop. Returns (body, truncated).

    Reads the raw stream and decodes gzip/deflate here with an output bound, so
    a small compressed body cannot expand past the cap in memory either.
    """
    decoder = _decoder(response.headers.get("content-encoding", ""))
    out = bytearray()
    raw_read = 0
    async for chunk in response.aiter_raw():
        raw_read += len(chunk)
        if decoder is None:
            out += chunk
        else:
            try:
                out += decoder.decompress(chunk, max_bytes + 1 - len(out))
            except zlib.error as exc:
                raise FetchFailed(f"the response could not be decompressed: {exc}") from None
            if decoder.unconsumed_tail:
                return bytes(out[:max_bytes]), True
        if len(out) > max_bytes or raw_read > max_bytes:
            return bytes(out[:max_bytes]), True
    return bytes(out), False


#: Squid errors that are policy, not failure: an ACL denial, and a lookup that
#: failed because the proxy's resolver dropped a private (rebinding) answer.
#: Neither is ever retried elsewhere.
_PROXY_REFUSALS = ("ERR_ACCESS_DENIED", "ERR_DNS_FAIL")


def _proxy_denied(response: httpx.Response) -> bool:
    error = response.headers.get("x-squid-error", "")
    return response.status_code in (403, 503) and any(code in error for code in _PROXY_REFUSALS)


def _client(settings: FetchSettings, transport: httpx.AsyncBaseTransport | None) -> httpx.AsyncClient:
    common = {
        "headers": _HEADERS,
        "timeout": httpx.Timeout(settings.timeout),
        "follow_redirects": False,
        "trust_env": False,
    }
    if transport is not None:
        # Tests only: the transport stands in for the proxy and the network.
        return httpx.AsyncClient(transport=transport, **common)
    return httpx.AsyncClient(proxy=settings.proxy, **common)


async def _fetch(url: str, settings: FetchSettings, transport: httpx.AsyncBaseTransport | None) -> FetchResult:
    current = url
    async with _client(settings, transport) as client:
        for _hop in range(settings.max_redirects + 1):
            target = check_url(current, settings.extra_blocked)
            await resolve_and_check(target, settings.extra_blocked)
            async with client.stream("GET", target.url) as response:
                if _proxy_denied(response):
                    raise FetchRefused(f"the egress proxy refused {target.host}: not a public destination, or it does not resolve to one")
                if response.status_code in REDIRECT_STATUSES:
                    location = response.headers.get("location")
                    if not location:
                        raise FetchFailed(f"HTTP {response.status_code} without a Location header")
                    current = urljoin(target.url, location.strip())
                    continue
                if response.status_code >= 400:
                    raise FetchFailed(f"HTTP {response.status_code} from {target.host}")
                media, charset = _media_type(response.headers.get("content-type", "text/html"))
                if media not in TEXT_TYPES:
                    raise FetchFailed(f"unsupported content type {media!r}")
                body, truncated = await read_capped(response, settings.max_bytes)
                return FetchResult(url=target.url, status=response.status_code, content_type=media, charset=charset, body=body, truncated=truncated)
    raise FetchFailed(f"more than {settings.max_redirects} redirects")


async def fetch(url: str, settings: FetchSettings, *, transport: httpx.AsyncBaseTransport | None = None) -> FetchResult:
    """Fetch ``url``; raises FetchRefused (policy) or FetchFailed (anything else)."""
    if transport is None and not settings.proxy:
        raise FetchFailed("no fetch egress proxy is configured (tools.web_fetch.proxy or OMNI_HARNESS_FETCH_EGRESS_PROXY)")
    try:
        async with asyncio.timeout(settings.timeout):
            return await _fetch(url, settings, transport)
    except TimeoutError:
        raise FetchFailed(f"timed out after {settings.timeout:g} s") from None
    except httpx.ProxyError as exc:
        # A CONNECT the proxy denied ("403 Forbidden") or could not resolve
        # ("503 ..."; the error page is not visible through httpx, and the
        # resolver drops private answers): refusals, never retried elsewhere.
        if str(exc).startswith(("403", "503")):
            raise FetchRefused("the egress proxy refused the destination: not a public address, or it does not resolve to one") from None
        raise FetchFailed(f"the egress proxy failed: {exc}") from None
    except httpx.HTTPError as exc:
        raise FetchFailed(f"request failed: {type(exc).__name__}: {exc}") from None
