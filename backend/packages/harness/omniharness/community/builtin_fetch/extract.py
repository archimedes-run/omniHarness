"""Readable markdown from a fetched page: trafilatura, then readability.

Only ``trafilatura.extract`` / ``extract_metadata`` are called, on bytes
already fetched. trafilatura's own downloader is never used: it would go
around the egress proxy and the guard.
"""

from __future__ import annotations

import logging

import trafilatura

from omniharness.community.builtin_fetch.fetcher import FetchResult
from omniharness.utils.readability import ReadabilityExtractor

logger = logging.getLogger(__name__)

#: The same bound the Jina reader tool returned, so the model sees the same shape.
MAX_OUTPUT_CHARS = 4096
_HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})

_readability = ReadabilityExtractor()


def _decode(result: FetchResult) -> str:
    try:
        return result.body.decode(result.charset or "utf-8", errors="replace")
    except LookupError:
        return result.body.decode("utf-8", errors="replace")


def _html_to_markdown(result: FetchResult) -> str:
    markdown = None
    title = None
    try:
        markdown = trafilatura.extract(
            result.body,
            url=result.url,
            output_format="markdown",
            include_links=True,
            include_tables=True,
            include_comments=False,
            favor_recall=True,
        )
        metadata = trafilatura.extract_metadata(result.body)
        title = metadata.title if metadata is not None else None
    except Exception:  # noqa: BLE001 - a parser crash falls through to readability
        logger.warning("trafilatura could not extract %s; using readability", result.url, exc_info=True)
    if markdown and markdown.strip():
        return f"# {title.strip() if title and title.strip() else 'Untitled'}\n\n{markdown.strip()}\n"
    return _readability.extract_article(_decode(result)).to_markdown()


def to_markdown(result: FetchResult) -> str:
    if result.content_type in _HTML_TYPES:
        text = _html_to_markdown(result)
    else:
        text = _decode(result)
    if not text.strip():
        text = "*No content available*\n"
    return text[:MAX_OUTPUT_CHARS]
