"""The ``web_fetch`` tool on the built-in fetcher, Jina only when enabled.

Config (``tools:`` entry named ``web_fetch``, all optional):

* ``proxy``: the fetch egress proxy URL; defaults to
  ``$OMNI_HARNESS_FETCH_EGRESS_PROXY``. With neither, with an unusable proxy
  URL, or with any failure before the proxy answers, nothing is fetched: the
  tool answers "page fetching unavailable: egress proxy down" and tries
  nothing else (no direct fetch, no Jina, whatever ``jina_fallback`` says).
  After the proxy answered (for https, its CONNECT reply) a failure is the
  site's, an ordinary error.
* ``timeout`` (s, at most 15), ``max_bytes`` (at most 2 MB),
  ``max_redirects`` (at most 5): caps can be lowered, never raised.
* ``blocked_networks``: extra CIDRs to refuse, on top of the built-in list.
* ``provider``: ``builtin`` (default) or ``jina``.
* ``jina_fallback``: false (default). When true, Jina may try a URL the
  built-in fetch FAILED on (HTTP status, content type, a site that timed out).
  Never for a refused URL, never when the egress proxy is down, and only when
  ``JINA_API_KEY`` is set. A key in the environment alone enables nothing.

PDFs (Content-Type ``application/pdf``, or a generic binary type whose body
starts with ``%PDF-``) come through the same proxy, guard and redirect checks,
up to 10 MB and 30 s for fetch plus extraction; the text of the first 200
pages is extracted with pypdf in a killable worker. An encrypted, image-only
or malformed PDF, or one over 10 MB, answers "couldn't extract text from this
PDF: <reason>" and is never handed to Jina.

The tool keeps the name ``web_fetch``, so its output is tagged and gated
exactly as before (public-result tool, outbound after a private read).
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass

from langchain.tools import tool

from omniharness.community.builtin_fetch.extract import to_markdown_bounded
from omniharness.community.builtin_fetch.fetcher import (
    MAX_BYTES_CAP,
    MAX_REDIRECTS_CAP,
    PDF_CONTENT_TYPE,
    PDF_TIMEOUT_CAP,
    TIMEOUT_CAP,
    FetchResult,
    FetchSettings,
    ResponseTooLarge,
    fetch,
    proxy_url_problem,
)
from omniharness.community.builtin_fetch.guard import EgressProxyDown, FetchFailed, FetchRefused, PdfUnreadable, WebFetchError, check_url, parse_networks, resolve_and_check
from omniharness.community.builtin_fetch.pdf import pdf_to_markdown_bounded
from omniharness.config import get_app_config

logger = logging.getLogger(__name__)

PROXY_ENV = "OMNI_HARNESS_FETCH_EGRESS_PROXY"
JINA_KEY_ENV = "JINA_API_KEY"


@dataclass(frozen=True)
class WebFetchConfig:
    fetch: FetchSettings
    provider: str = "builtin"
    jina_fallback: bool = False


def load_config() -> WebFetchConfig:
    tool_config = get_app_config().get_tool_config("web_fetch")
    extra = dict(getattr(tool_config, "model_extra", None) or {}) if tool_config is not None else {}
    provider = str(extra.get("provider") or "builtin").strip().lower()
    if provider not in ("builtin", "jina"):
        raise FetchFailed(f"tools.web_fetch.provider must be 'builtin' or 'jina', not {provider!r}")
    try:
        settings = FetchSettings(
            proxy=(str(extra.get("proxy") or "").strip() or os.getenv(PROXY_ENV, "").strip() or None),
            timeout=extra.get("timeout", TIMEOUT_CAP),
            max_bytes=extra.get("max_bytes", MAX_BYTES_CAP),
            max_redirects=extra.get("max_redirects", MAX_REDIRECTS_CAP),
            extra_blocked=parse_networks(extra.get("blocked_networks")),
        )
    except (TypeError, ValueError) as exc:
        raise FetchFailed(f"tools.web_fetch is misconfigured: {exc}") from None
    if provider == "builtin" and settings.proxy:
        problem = proxy_url_problem(settings.proxy)
        if problem:
            raise EgressProxyDown(problem)
    return WebFetchConfig(fetch=settings, provider=provider, jina_fallback=extra.get("jina_fallback", False) is True)


def _jina_key_set() -> bool:
    return bool(os.getenv(JINA_KEY_ENV, "").strip())


async def _jina(url: str, settings: FetchSettings) -> str:
    """The Jina reader, called only with a key. The URL passes the same guard."""
    if not _jina_key_set():
        return f"Error: the Jina reader is selected but {JINA_KEY_ENV} is not set"
    target = check_url(url, settings.extra_blocked)
    await resolve_and_check(target, settings.extra_blocked)
    from omniharness.community.jina_ai.jina_client import JinaClient

    loop = asyncio.get_running_loop()
    start = loop.time()
    html = await JinaClient().crawl(target.url, return_format="html", timeout=int(settings.timeout))
    if isinstance(html, str) and html.startswith("Error:"):
        return html
    # The reader's HTML is as untrusted as any page: the same bounded extraction,
    # within the same budget as the reader call.
    page = FetchResult(url=target.url, status=200, content_type="text/html", charset="utf-8", body=str(html).encode("utf-8")[:MAX_BYTES_CAP], truncated=False)
    return await to_markdown_bounded(page, settings.timeout - (loop.time() - start))


async def fetch_markdown(url: str, config: WebFetchConfig) -> str:
    if config.provider == "jina":
        return await _jina(url, config.fetch)
    loop = asyncio.get_running_loop()
    start = loop.time()
    try:
        result = await fetch(url, config.fetch)
        # Extraction runs in a killable child process, in what is left of the budget.
        if result.content_type == PDF_CONTENT_TYPE:
            return await pdf_to_markdown_bounded(result, PDF_TIMEOUT_CAP - (loop.time() - start))
        return await to_markdown_bounded(result, config.fetch.timeout - (loop.time() - start))
    except (FetchRefused, EgressProxyDown, PdfUnreadable, ResponseTooLarge):
        # Policy, the only way out is down, a PDF with no text to take, or a
        # body over every cap: final, never retried elsewhere.
        raise
    except WebFetchError as exc:
        failure = exc
    except Exception as exc:  # noqa: BLE001 - extraction bugs are failures, not crashes
        logger.warning("web_fetch extraction failed for a fetched page", exc_info=True)
        failure = FetchFailed(f"the page could not be read: {type(exc).__name__}")
    if config.jina_fallback and _jina_key_set():
        logger.info("built-in web_fetch failed (%s); trying the Jina reader", failure)
        return await _jina(url, config.fetch)
    raise failure


@tool("web_fetch", parse_docstring=True)
async def web_fetch_tool(url: str) -> str:
    """Fetch the contents of a web page at a given URL. PDF documents are supported: their text is returned.
    Only fetch EXACT URLs that have been provided directly by the user or have been returned in results from the web_search and web_fetch tools.
    This tool can NOT access content that requires authentication, such as private Google Docs or pages behind login walls.
    Do NOT add www. to URLs that do NOT have them.
    URLs must include the schema: https://example.com is a valid URL while example.com is an invalid URL.

    Args:
        url: The URL to fetch the contents of.
    """
    try:
        return await fetch_markdown(url, load_config())
    except (EgressProxyDown, PdfUnreadable) as exc:
        return str(exc)
    except WebFetchError as exc:
        return f"Error: {exc}"
