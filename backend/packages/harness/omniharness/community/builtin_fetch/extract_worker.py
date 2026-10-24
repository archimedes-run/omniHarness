"""The extraction child process: a fetched page (JSON) on stdin, markdown on stdout.

Started by ``extract.to_markdown_bounded`` in its own process group, under a
deadline; it does no network I/O.
"""

from __future__ import annotations

import logging
import sys

from omniharness.community.builtin_fetch.extract import decode_result, to_markdown


def main() -> int:
    logging.basicConfig(level=logging.ERROR, stream=sys.stderr)
    result = decode_result(sys.stdin.buffer.read())
    sys.stdout.buffer.write(to_markdown(result).encode("utf-8"))
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
