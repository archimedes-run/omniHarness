"""The extraction child process: a fetched page (JSON) on stdin, markdown on stdout.

Started by ``extract.to_markdown_bounded`` in its own process group, with a
minimal environment and a private TMPDIR, under a deadline; it does no network
I/O. ``argv[1]`` is its own deadline in seconds: it limits its CPU time (and
that of the node readability may start) and arms an alarm that kills its whole
process group, so it cannot outlive a gateway that went away.
"""

from __future__ import annotations

import logging
import os
import resource
import signal
import sys

from omniharness.community.builtin_fetch.extract import WORKER_MEMORY_BYTES, decode_result, to_markdown


def limit_resources(seconds: int) -> None:
    """CPU seconds and a heap ceiling, inherited by every child (node)."""
    resource.setrlimit(resource.RLIMIT_CPU, (seconds + 1, seconds + 1))
    try:
        resource.setrlimit(resource.RLIMIT_DATA, (WORKER_MEMORY_BYTES, WORKER_MEMORY_BYTES))
    except (ValueError, OSError):  # not enforceable on every platform (macOS)
        pass


def _kill_own_group(signum, frame) -> None:  # noqa: ARG001 - signal handler signature
    os.killpg(0, signal.SIGKILL)


def arm_deadline(seconds: int) -> None:
    """After ``seconds`` (+1) of wall time, SIGKILL this process group."""
    signal.signal(signal.SIGALRM, _kill_own_group)
    signal.alarm(seconds + 1)


def main() -> int:
    seconds = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    seconds = min(max(seconds, 1), 15)
    arm_deadline(seconds)
    limit_resources(seconds)
    logging.basicConfig(level=logging.ERROR, stream=sys.stderr)
    result = decode_result(sys.stdin.buffer.read())
    sys.stdout.buffer.write(to_markdown(result).encode("utf-8"))
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
