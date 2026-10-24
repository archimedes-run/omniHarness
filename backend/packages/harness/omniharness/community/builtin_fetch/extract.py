"""Readable markdown from a fetched page: trafilatura, then readability.

Extraction never runs in the gateway process. ``to_markdown_bounded`` runs it
in a child process (``extract_worker``) in its own process group, under a hard
deadline; on timeout or cancellation the whole group is killed, including any
``node`` the readability fallback started. Pathological trees (very deep or
very large) skip the readability fallback altogether.

Only ``trafilatura.extract`` / ``extract_metadata`` are called, on bytes
already fetched. trafilatura's own downloader is never used: it would go
around the egress proxy and the guard.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import signal
import sys

from omniharness.community.builtin_fetch.fetcher import FetchResult
from omniharness.community.builtin_fetch.guard import FetchFailed

logger = logging.getLogger(__name__)

#: The same bound the Jina reader tool returned, so the model sees the same shape.
MAX_OUTPUT_CHARS = 4096
#: Beyond these, the readability fallback (a node subprocess, or a recursive
#: pure-Python parse) is not attempted: real pages stay far below both.
MAX_FALLBACK_DEPTH = 256
MAX_FALLBACK_ELEMENTS = 100_000
WORKER_MODULE = "omniharness.community.builtin_fetch.extract_worker"
NO_CONTENT = "*No content could be extracted from this page*\n"

_HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_TAG = re.compile(rb"<(/?)([a-zA-Z][a-zA-Z0-9-]*)[^>]*?(/?)>")
_VOID = frozenset(b"area base br col embed hr img input link meta param source track wbr".split())


def _decode(result: FetchResult) -> str:
    try:
        return result.body.decode(result.charset or "utf-8", errors="replace")
    except LookupError:
        return result.body.decode("utf-8", errors="replace")


def tree_too_complex(body: bytes, max_depth: int = MAX_FALLBACK_DEPTH, max_elements: int = MAX_FALLBACK_ELEMENTS) -> bool:
    """A linear scan of the tags: True as soon as nesting or element count is past the limit."""
    depth = elements = 0
    for match in _TAG.finditer(body):
        closing, name, self_closing = match.group(1), match.group(2).lower(), match.group(3)
        if closing:
            depth = max(depth - 1, 0)
            continue
        elements += 1
        if elements > max_elements:
            return True
        if not self_closing and name not in _VOID:
            depth += 1
            if depth > max_depth:
                return True
    return False


def _html_to_markdown(result: FetchResult) -> str:
    import trafilatura

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
    if tree_too_complex(result.body):
        return NO_CONTENT
    from omniharness.utils.readability import ReadabilityExtractor

    return ReadabilityExtractor().extract_article(_decode(result)).to_markdown()


def to_markdown(result: FetchResult) -> str:
    """The extraction itself. Runs in the worker process, never in the gateway."""
    if result.content_type in _HTML_TYPES:
        text = _html_to_markdown(result)
    else:
        text = _decode(result)
    if not text.strip():
        text = "*No content available*\n"
    return text[:MAX_OUTPUT_CHARS]


def encode_result(result: FetchResult) -> bytes:
    return json.dumps(
        {
            "url": result.url,
            "status": result.status,
            "content_type": result.content_type,
            "charset": result.charset,
            "truncated": result.truncated,
            "body": base64.b64encode(result.body).decode("ascii"),
        }
    ).encode("ascii")


def decode_result(payload: bytes) -> FetchResult:
    data = json.loads(payload)
    return FetchResult(
        url=data["url"],
        status=data["status"],
        content_type=data["content_type"],
        charset=data["charset"],
        truncated=data["truncated"],
        body=base64.b64decode(data["body"]),
    )


def _kill_group(proc: asyncio.subprocess.Process) -> None:
    """SIGKILL the worker's process group (the worker and anything it started)."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass


async def run_bounded(argv: list[str], payload: bytes, timeout: float) -> bytes:
    """Run ``argv`` in a new process group with ``payload`` on stdin; return its
    stdout. On timeout, error or cancellation the group is killed and reaped."""
    if timeout <= 0:
        raise FetchFailed("timed out before the page could be read")
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        async with asyncio.timeout(timeout):
            out, _ = await proc.communicate(payload)
    except TimeoutError:
        raise FetchFailed(f"reading the page took longer than the {timeout:.1f} s left") from None
    finally:
        if proc.returncode is None:
            _kill_group(proc)
            await proc.wait()
    if proc.returncode != 0:
        raise FetchFailed("the page could not be read")
    return out


async def to_markdown_bounded(result: FetchResult, timeout: float) -> str:
    out = await run_bounded([sys.executable, "-I", "-m", WORKER_MODULE], encode_result(result), timeout)
    return out.decode("utf-8", errors="replace")[:MAX_OUTPUT_CHARS]
