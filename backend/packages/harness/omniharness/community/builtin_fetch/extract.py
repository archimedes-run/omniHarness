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
import math
import os
import re
import shutil
import signal
import sys
import tempfile
import weakref

from omniharness.community.builtin_fetch.fetcher import FetchResult
from omniharness.community.builtin_fetch.guard import FetchFailed

logger = logging.getLogger(__name__)

#: The same bound the Jina reader tool returned, so the model sees the same shape.
MAX_OUTPUT_CHARS = 4096
#: Beyond these, the readability fallback (a node subprocess, or a recursive
#: pure-Python parse) is not attempted: real pages stay far below both.
MAX_FALLBACK_DEPTH = 256
MAX_FALLBACK_ELEMENTS = 100_000
MAX_FALLBACK_ATTRIBUTES = 100_000
MAX_TAG_BYTES = 16 * 1024
#: Extraction workers running at once, per event loop (each can use hundreds
#: of MB on a 2 MB page). A fetch waiting for a slot waits inside its deadline.
MAX_WORKERS = 4
#: Memory ceiling for a worker and anything it starts (RLIMIT_DATA, Linux).
WORKER_MEMORY_BYTES = 1024 * 1024 * 1024
WORKER_MODULE = "omniharness.community.builtin_fetch.extract_worker"
NO_CONTENT = "*No content could be extracted from this page*\n"

_HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_TAG = re.compile(rb"<(/?)([a-zA-Z][a-zA-Z0-9-]*)([^>]*?)(/?)>")
_ATTRIBUTE = re.compile(rb"[^\s=/]+(?:\s*=)?")
_VOID = frozenset(b"area base br col embed hr img input link meta param source track wbr".split())


def _decode(result: FetchResult) -> str:
    try:
        return result.body.decode(result.charset or "utf-8", errors="replace")
    except LookupError:
        return result.body.decode("utf-8", errors="replace")


def tree_too_complex(body: bytes, max_depth: int = MAX_FALLBACK_DEPTH, max_elements: int = MAX_FALLBACK_ELEMENTS) -> bool:
    """A linear scan of the tags: True as soon as nesting, element count,
    attribute count or the size of a single tag is past the limit."""
    depth = elements = attributes = 0
    for match in _TAG.finditer(body):
        closing, name, inner, self_closing = match.group(1), match.group(2).lower(), match.group(3), match.group(4)
        if closing:
            depth = max(depth - 1, 0)
            continue
        elements += 1
        if elements > max_elements or len(inner) > MAX_TAG_BYTES:
            return True
        attributes += inner.count(b"=") if inner else 0
        if attributes > MAX_FALLBACK_ATTRIBUTES:
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


_SLOTS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = weakref.WeakKeyDictionary()


def _slots() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    if loop not in _SLOTS:
        _SLOTS[loop] = asyncio.Semaphore(MAX_WORKERS)
    return _SLOTS[loop]


def worker_env(tmpdir: str) -> dict[str, str]:
    """The worker's whole environment: nothing inherited from the gateway
    (no secrets), a private TMPDIR/HOME removed after the call, and a heap
    ceiling for the node that readability may start."""
    return {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TMPDIR": tmpdir,
        "HOME": tmpdir,
        "NODE_OPTIONS": "--max-old-space-size=512",
    }


async def run_bounded(argv: list[str], payload: bytes, timeout: float) -> bytes:
    """Run ``argv`` in a new process group with ``payload`` on stdin; return its
    stdout. At most MAX_WORKERS at once; waiting for a slot counts against
    ``timeout``. On timeout, error or cancellation the group is killed and
    reaped, and its private temporary directory removed."""
    if timeout <= 0:
        raise FetchFailed("timed out before the page could be read")
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    slots = _slots()
    try:
        async with asyncio.timeout(timeout):
            await slots.acquire()
    except TimeoutError:
        raise FetchFailed("timed out waiting to read the page") from None
    tmpdir = tempfile.mkdtemp(prefix="omni-extract-")
    proc = None
    try:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise FetchFailed("timed out waiting to read the page")
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
            env=worker_env(tmpdir),
            cwd=tmpdir,
        )
        try:
            async with asyncio.timeout(remaining):
                out, _ = await proc.communicate(payload)
        except TimeoutError:
            raise FetchFailed(f"reading the page took longer than the {timeout:.1f} s left") from None
    finally:
        if proc is not None and proc.returncode is None:
            _kill_group(proc)
            await proc.wait()
        shutil.rmtree(tmpdir, ignore_errors=True)
        slots.release()
    if proc.returncode != 0:
        raise FetchFailed("the page could not be read")
    return out


async def to_markdown_bounded(result: FetchResult, timeout: float) -> str:
    # The worker gets its own deadline too (CPU limit and an alarm), so it
    # cannot outlive a gateway that crashed or reloaded mid-extraction.
    seconds = str(max(1, math.ceil(timeout)))
    out = await run_bounded([sys.executable, "-I", "-m", WORKER_MODULE, seconds], encode_result(result), timeout)
    return out.decode("utf-8", errors="replace")[:MAX_OUTPUT_CHARS]
