"""GET a page through the fetch egress proxy, with hard caps.

* Every request goes to the configured proxy; environment proxies are ignored
  (``trust_env=False``) and with no proxy configured nothing is fetched.
* Redirects are never followed by the HTTP client: each hop is checked by
  ``guard`` again and requested through the proxy again, at most 5 hops.
* 2 MB body (counted after decompression, and before it), 15 s for the whole
  fetch including every hop.
* A PDF (Content-Type ``application/pdf``, or ``application/octet-stream``
  whose body starts with ``%PDF-``) may be up to 10 MB, refused while
  streaming as soon as it passes that, and its fetch plus text extraction get
  30 s in all, counted from the start of the fetch.
"""

from __future__ import annotations

import asyncio
import zlib
from dataclasses import dataclass, field
from urllib.parse import urljoin

import httpx

from omniharness.community.builtin_fetch.guard import (
    EgressProxyDown,
    FetchFailed,
    FetchRefused,
    IPNetwork,
    PdfUnreadable,
    WebFetchError,
    check_url,
    resolve_and_check,
)

MAX_BYTES_CAP = 2 * 1024 * 1024
TIMEOUT_CAP = 15.0
MAX_REDIRECTS_CAP = 5
#: Opening the connection to the proxy (and, inside a CONNECT tunnel, the
#: site's TLS handshake) gets at most this, well inside the overall budget, so
#: an unreachable proxy shows up as a connect timeout, not the whole budget.
CONNECT_TIMEOUT_CAP = 5.0
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

#: PDFs: their own size and time caps (not configurable upward either), and
#: text extraction with pypdf in a killable worker process (``pdf``).
PDF_MAX_BYTES = 10 * 1024 * 1024
PDF_TIMEOUT_CAP = 30.0
PDF_TYPES = frozenset({"application/pdf", "application/x-pdf"})
#: Generic binary types: treated as a PDF only if the body starts with this.
SNIFF_TYPES = frozenset({"application/octet-stream", "binary/octet-stream"})
PDF_MAGIC = b"%PDF-"
PDF_CONTENT_TYPE = "application/pdf"
#: The egress proxy's own body cap (plain http only): 1 MB above the PDF cap,
#: so the gateway's streaming cap always fires first and a too-large PDF is
#: reported as one. A proxy refusal on a larger Content-Length comes before the
#: real headers, so its content type is unknown: ResponseTooLarge, final.
PROXY_MAX_BODY_MB = PDF_MAX_BYTES // (1024 * 1024) + 1

#: Content the extractor can turn into text. Anything else (images, archives)
#: is a failure, so a configured fallback can try it.
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
    "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,application/pdf;q=0.8,*/*;q=0.5",
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


class ResponseTooLarge(FetchFailed):
    """The egress proxy refused a body over its cap. Final: never retried elsewhere."""


class NotPdf(Exception):
    """A sniffed body did not start with the PDF magic."""


async def read_capped(response: httpx.Response, max_bytes: int, *, require_prefix: bytes | None = None) -> tuple[bytes, bool]:
    """Read at most ``max_bytes`` of body, then stop. Returns (body, truncated).

    Reads the raw stream and decodes gzip/deflate here with an output bound, so
    a small compressed body cannot expand past the cap in memory either. With
    ``require_prefix``, raises NotPdf as soon as enough of the body is in to
    see it does not start with that prefix.
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
        if require_prefix is not None and len(out) >= len(require_prefix):
            if not out.startswith(require_prefix):
                raise NotPdf
            require_prefix = None
        if len(out) > max_bytes or raw_read > max_bytes:
            return bytes(out[:max_bytes]), True
    if require_prefix is not None and not out.startswith(require_prefix):
        raise NotPdf
    return bytes(out), False


def _pdf_too_large() -> PdfUnreadable:
    return PdfUnreadable(f"it is larger than the {PDF_MAX_BYTES // (1024 * 1024)} MB limit")


async def read_pdf(response: httpx.Response, *, sniffed: bool) -> bytes:
    """The whole PDF body, or PdfUnreadable once it passes PDF_MAX_BYTES:
    refused up front on a Content-Length over the cap, and otherwise counted
    while streaming, so at most one chunk past the cap is ever read."""
    length = response.headers.get("content-length", "").strip()
    if length.isdigit() and int(length) > PDF_MAX_BYTES:
        raise _pdf_too_large()
    body, truncated = await read_capped(response, PDF_MAX_BYTES, require_prefix=PDF_MAGIC if sniffed else None)
    if truncated:
        raise _pdf_too_large()
    return body


#: Squid errors that are policy, not failure: an ACL denial, and a lookup that
#: failed because the proxy's resolver dropped a private (rebinding) answer.
#: Neither is ever retried elsewhere.
_PROXY_REFUSALS = ("ERR_ACCESS_DENIED", "ERR_DNS_FAIL")


def _proxy_denied(response: httpx.Response) -> bool:
    error = response.headers.get("x-squid-error", "")
    return response.status_code in (403, 503) and any(code in error for code in _PROXY_REFUSALS)


def proxy_url_problem(proxy: str) -> str | None:
    """Why ``proxy`` is not a usable proxy URL (no hostnames in the answer), or None."""
    try:
        url = httpx.URL(proxy)
    except (httpx.InvalidURL, ValueError, TypeError):
        return "the proxy URL cannot be parsed"
    if url.scheme not in ("http", "https"):
        return "the proxy URL must be http:// or https://"
    if not url.host:
        return "the proxy URL has no host"
    return None


@dataclass
class _Progress:
    """Where the current hop is. ``waiting``: the request went to the proxy
    and the proxy has not answered yet (no response headers: no CONNECT reply
    for https, no response for http). A failure while waiting is the proxy's;
    after the proxy answered (a 200 CONNECT included) it is the site's."""

    waiting: bool = False
    pdf: bool = False

    async def trace(self, name: str, info: dict) -> None:
        # httpcore reports the proxy's CONNECT reply (and a forward-proxied
        # response) as http11.receive_response_headers.complete.
        if name.endswith("receive_response_headers.complete"):
            self.waiting = False


def _connect_timeout(settings: FetchSettings) -> float:
    return min(CONNECT_TIMEOUT_CAP, settings.timeout / 2)


def _client(settings: FetchSettings, transport: httpx.AsyncBaseTransport | None) -> httpx.AsyncClient:
    common = {
        "headers": _HEADERS,
        "timeout": httpx.Timeout(settings.timeout, connect=_connect_timeout(settings)),
        "follow_redirects": False,
        "trust_env": False,
    }
    if transport is not None:
        # Tests only: the transport stands in for the proxy and the network.
        return httpx.AsyncClient(transport=transport, **common)
    return httpx.AsyncClient(proxy=settings.proxy, **common)


async def _fetch(
    url: str,
    settings: FetchSettings,
    transport: httpx.AsyncBaseTransport | None,
    progress: _Progress,
    budget: asyncio.Timeout,
    started: float,
) -> FetchResult:
    current = url
    try:
        client = _client(settings, transport)
    except (ValueError, TypeError):
        raise EgressProxyDown("the proxy URL is not usable") from None
    async with client:
        for _hop in range(settings.max_redirects + 1):
            progress.waiting = False
            target = check_url(current, settings.extra_blocked)
            await resolve_and_check(target, settings.extra_blocked)
            progress.waiting = True
            async with client.stream("GET", target.url, extensions={"trace": progress.trace}) as response:
                progress.waiting = False
                if _proxy_denied(response):
                    raise FetchRefused(f"the egress proxy refused {target.host}: not a public destination, or it does not resolve to one")
                if response.status_code in REDIRECT_STATUSES:
                    location = response.headers.get("location")
                    if not location:
                        raise FetchFailed(f"HTTP {response.status_code} without a Location header")
                    current = urljoin(target.url, location.strip())
                    continue
                if "ERR_TOO_BIG" in response.headers.get("x-squid-error", ""):
                    raise ResponseTooLarge(f"the response is larger than the egress proxy allows ({PROXY_MAX_BODY_MB} MB)")
                if response.status_code >= 400:
                    raise FetchFailed(f"HTTP {response.status_code} from {target.host}")
                media, charset = _media_type(response.headers.get("content-type", "text/html"))
                if media in PDF_TYPES or media in SNIFF_TYPES:
                    # A PDF gets its own (larger) budget, counted from the start.
                    progress.pdf = True
                    budget.reschedule(started + PDF_TIMEOUT_CAP)
                    try:
                        body = await read_pdf(response, sniffed=media not in PDF_TYPES)
                    except NotPdf:
                        raise FetchFailed(f"unsupported content type {media!r}") from None
                    return FetchResult(url=target.url, status=response.status_code, content_type=PDF_CONTENT_TYPE, charset=None, body=body, truncated=False)
                if media not in TEXT_TYPES:
                    raise FetchFailed(f"unsupported content type {media!r}")
                body, truncated = await read_capped(response, settings.max_bytes)
                return FetchResult(url=target.url, status=response.status_code, content_type=media, charset=charset, body=body, truncated=truncated)
    raise FetchFailed(f"more than {settings.max_redirects} redirects")


async def fetch(url: str, settings: FetchSettings, *, transport: httpx.AsyncBaseTransport | None = None) -> FetchResult:
    """Fetch ``url``; raises FetchRefused (policy), EgressProxyDown (no proxy, a
    bad proxy URL, or any failure before the proxy answered) or FetchFailed
    (anything else, including the site failing after the proxy answered)."""
    if transport is None:
        if not settings.proxy:
            raise EgressProxyDown("not configured: set tools.web_fetch.proxy or OMNI_HARNESS_FETCH_EGRESS_PROXY")
        problem = proxy_url_problem(settings.proxy)
        if problem:
            raise EgressProxyDown(problem)
    progress = _Progress()
    started = asyncio.get_running_loop().time()
    try:
        async with asyncio.timeout(settings.timeout) as budget:
            return await _fetch(url, settings, transport, progress, budget, started)
    except TimeoutError:
        if progress.waiting:
            raise EgressProxyDown(f"no answer from the proxy within {settings.timeout:g} s") from None
        raise FetchFailed(f"timed out after {PDF_TIMEOUT_CAP if progress.pdf else settings.timeout:g} s") from None
    except httpx.ProxyError as exc:
        # A CONNECT the proxy denied ("403 Forbidden") or could not resolve
        # ("503 ..."; the error page is not visible through httpx, and the
        # resolver drops private answers): refusals, never retried elsewhere.
        if str(exc).startswith("403"):
            raise FetchRefused("the egress proxy refused the destination: not a public address") from None
        if str(exc).startswith("503"):
            raise FetchRefused("the page could not be fetched through the egress proxy") from None
        raise EgressProxyDown(f"proxy error: {exc}") from None
    except WebFetchError:
        raise
    except httpx.HTTPError as exc:
        if progress.waiting:
            # Refused, timed out, closed, or not HTTP: before the proxy answered.
            raise EgressProxyDown(f"no response from the proxy: {type(exc).__name__}") from None
        raise FetchFailed(f"request failed: {type(exc).__name__}: {exc}") from None
    except Exception as exc:
        if progress.waiting:
            raise EgressProxyDown(f"no response from the proxy: {type(exc).__name__}") from None
        raise
