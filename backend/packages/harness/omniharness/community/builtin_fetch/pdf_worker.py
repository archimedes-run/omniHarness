"""The PDF extraction child process: PDF bytes on stdin, JSON on stdout.

Started by ``pdf.pdf_to_markdown_bounded`` through ``extract.run_bounded``
(own process group, minimal environment, private TMPDIR, deadline); it does no
network I/O. ``argv[1]`` is its own deadline in seconds (at most 30): the same
CPU/memory limits and self-kill alarm as the HTML worker.
"""

from __future__ import annotations

import contextlib
import json
import logging
import sys

from omniharness.community.builtin_fetch.extract_worker import arm_deadline, limit_resources
from omniharness.community.builtin_fetch.fetcher import PDF_TIMEOUT_CAP
from omniharness.community.builtin_fetch.pdf import extract_pdf_text


def main() -> int:
    seconds = int(sys.argv[1]) if len(sys.argv) > 1 else int(PDF_TIMEOUT_CAP)
    seconds = min(max(seconds, 1), int(PDF_TIMEOUT_CAP))
    arm_deadline(seconds)
    limit_resources(seconds)
    logging.basicConfig(level=logging.ERROR, stream=sys.stderr)
    body = sys.stdin.buffer.read()
    out = sys.stdout.buffer
    # Only the result may reach the real stdout.
    with contextlib.redirect_stdout(sys.stderr):
        data = extract_pdf_text(body)
    out.write(json.dumps(data).encode("utf-8"))
    out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
