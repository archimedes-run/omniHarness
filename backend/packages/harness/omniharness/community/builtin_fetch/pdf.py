"""Text from a fetched PDF, with pypdf, never in the gateway process.

``pdf_to_markdown_bounded`` hands the PDF bytes to a child process
(``pdf_worker``) through the same bounded runner as HTML extraction: its own
process group, a minimal environment, a CPU and memory limit, a hard deadline
(what is left of the 30 s PDF budget), and the whole group killed on timeout
or cancellation. A pathological PDF can cost a worker slot until the deadline,
never the event loop.

At most ``PDF_MAX_PAGES`` pages are read; a longer PDF is not refused, its
header says that only the first pages were read. Encrypted PDFs, PDFs with no
text layer (scanned or image-only) and malformed ones raise PdfUnreadable,
which is final (no fallback reader).
"""

from __future__ import annotations

import io
import json
import logging
import math
import sys

from omniharness.community.builtin_fetch.extract import MAX_OUTPUT_CHARS, run_bounded
from omniharness.community.builtin_fetch.fetcher import PDF_TIMEOUT_CAP, FetchResult
from omniharness.community.builtin_fetch.guard import FetchFailed, PdfUnreadable

logger = logging.getLogger(__name__)

PDF_MAX_PAGES = 200
WORKER_MODULE = "omniharness.community.builtin_fetch.pdf_worker"
MAX_TITLE_CHARS = 200

ENCRYPTED = "it is encrypted"
NO_TEXT = "it has no extractable text (it may be scanned or image-only)"
MALFORMED = "it is malformed or not a PDF"


def extract_pdf_text(body: bytes, max_pages: int = PDF_MAX_PAGES, max_chars: int = MAX_OUTPUT_CHARS) -> dict:
    """The extraction itself. Runs in the worker process, never in the gateway.

    Returns ``{"error": reason}`` or ``{"pages": n, "read": k, "title": str|None,
    "text": str}``. Stops early once ``max_chars`` of text are in: the tool
    output is cut there anyway.
    """
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(body), strict=False)
        if reader.is_encrypted:
            return {"error": ENCRYPTED}
        total = len(reader.pages)
    except Exception:  # noqa: BLE001 - pypdf raises many types on broken files
        return {"error": MALFORMED}
    if total == 0:
        return {"error": MALFORMED}
    title = None
    try:
        meta = reader.metadata
        if meta is not None and meta.title:
            title = " ".join(str(meta.title).split())[:MAX_TITLE_CHARS] or None
    except Exception:  # noqa: BLE001 - a broken info dict is not a broken PDF
        title = None
    parts: list[str] = []
    chars = 0
    failed = 0
    read = 0
    for index in range(min(total, max_pages)):
        read += 1
        try:
            text = reader.pages[index].extract_text() or ""
        except Exception:  # noqa: BLE001 - one broken page does not sink the rest
            failed += 1
            continue
        text = text.strip()
        if text:
            parts.append(text)
            chars += len(text)
            if chars >= max_chars:
                break
    if not parts:
        return {"error": MALFORMED if failed == read else NO_TEXT}
    return {"pages": total, "read": read, "title": title, "text": "\n\n".join(parts)}


def format_result(url: str, data: dict, max_pages: int = PDF_MAX_PAGES) -> str:
    """The tool output: a header (title, source URL, page count) and the text,
    cut to the same output bound as an HTML page."""
    pages = data["pages"]
    note = f" (text read from the first {max_pages} only)" if pages > max_pages else ""
    header = f"# {data.get('title') or 'PDF document'}\n\nSource: {url}\nPages: {pages}{note}\n\n"
    return (header + data["text"].strip() + "\n")[:MAX_OUTPUT_CHARS]


async def pdf_to_markdown_bounded(result: FetchResult, timeout: float) -> str:
    """Extract in a killable worker within ``timeout`` seconds; PdfUnreadable
    for anything that yields no text, the timeout included."""
    seconds = str(max(1, math.ceil(min(timeout, PDF_TIMEOUT_CAP))))
    try:
        out = await run_bounded([sys.executable, "-I", "-m", WORKER_MODULE, seconds], result.body, timeout)
    except FetchFailed as exc:
        raise PdfUnreadable(f"it could not be read in time or the reader failed ({exc})") from None
    try:
        data = json.loads(out)
    except ValueError:
        raise PdfUnreadable("the reader failed") from None
    if not isinstance(data, dict):
        raise PdfUnreadable("the reader failed")
    if "error" in data:
        raise PdfUnreadable(str(data["error"]))
    return format_result(result.url, data)
