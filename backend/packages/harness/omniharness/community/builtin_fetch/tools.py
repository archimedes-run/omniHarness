"""The ``web_fetch`` tool on the built-in fetcher, Jina as an optional fallback.

Config (``tools:`` entry named ``web_fetch``, all optional):

* ``proxy``: the fetch egress proxy URL; defaults to
  ``$OMNI_HARNESS_FETCH_EGRESS_PROXY``. With neither, nothing is fetched.
* ``timeout`` (s, at most 15), ``max_bytes`` (at most 2 MB),
  ``max_redirects`` (at most 5): caps can be lowered, never raised.
* ``blocked_networks``: extra CIDRs to refuse, on top of the built-in list.
* ``provider``: ``builtin`` (default) or ``jina``.
* ``jina_fallback``: true (default) lets Jina try a URL the built-in fetch
  FAILED on (network, status, content type). Never for a refused URL, and only
  when ``JINA_API_KEY`` is set: with no key Jina is never called.

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
from omniharness.community.builtin_fetch.fetcher import MAX_BYTES_CAP, MAX_REDIRECTS_CAP, TIMEOUT_CAP, FetchResult, FetchSettings, fetch
from omniharness.community.builtin_fetch.guard import FetchFailed, FetchRefused, WebFetchError, check_url, parse_networks, resolve_and_check
from omniharness.config import get_app_config

logger = logging.getLogger(__name__)

PROXY_ENV = "OMNI_HARNESS_FETCH_EGRESS_PROXY"
JINA_KEY_ENV = "JINA_API_KEY"


@dataclass(frozen=True)
class WebFetchConfig:
    fetch: FetchSettings
    provider: str = "builtin"
    jina_fallback: bool = True


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
    return WebFetchConfig(fetch=settings, provider=provider, jina_fallback=bool(extra.get("jina_fallback", True)))


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
        return await to_markdown_bounded(result, config.fetch.timeout - (loop.time() - start))
    except FetchRefused:
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
    """Fetch the contents of a web page at a given URL.
    Only fetch EXACT URLs that have been provided directly by the user or have been returned in results from the web_search and web_fetch tools.
    This tool can NOT access content that requires authentication, such as private Google Docs or pages behind login walls.
    Do NOT add www. to URLs that do NOT have them.
    URLs must include the schema: https://example.com is a valid URL while example.com is an invalid URL.

    Args:
        url: The URL to fetch the contents of.
    """
    try:
        return await fetch_markdown(url, load_config())
    except WebFetchError as exc:
        return f"Error: {exc}"
