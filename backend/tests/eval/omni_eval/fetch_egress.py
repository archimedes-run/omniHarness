"""The fetch egress proxy for a real-mode eval run (owner rule, 2026-11-13).

A real-model trial fetches web pages exactly as the live stack does: through the
public-internet-only fetch egress proxy. Without it the built-in fetcher has no
route, and before this module a trial silently used a paid fallback reader
whose key happened to be in the env file (it ran out of balance and failed
every research task with a 402).

So `make eval EVAL_MODEL=real` starts the SAME service the compose file runs
as `fetch-egress`: the same local image (`IMAGE`, built by `make up`/`make
dev`; nothing is pulled or built here), the same entrypoint and Squid config
(mounted read-only from docker/fetch-egress), on its own user-defined network
(Docker's resolver, which the entrypoint uses, exists only there), with its
port published on 127.0.0.1 only. It is started once per eval run and removed
at the end, on failure and on Ctrl-C too (a `finally`, plus SIGTERM turned into
an exception). A leftover from a run that was killed outright (SIGKILL) is
found by its label and removed when the next run starts.

If it cannot start, or a probe through it to a public page fails, real mode
refuses to run (`EgressUnavailable`): research tasks are never scored without
the fetch path.
"""

from __future__ import annotations

import contextlib
import secrets
import signal
import socket
import subprocess
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

#: The image the compose file's `fetch-egress` service runs (docker/
#: docker-compose.yaml; tests/eval/test_harness_limits.py keeps them equal).
IMAGE = "omni-harness-sandbox-egress:1"
LABEL = "omni-eval-fetch-egress"
#: A public page fetched through the proxy before any trial runs.
PROBE_URL = "https://pypi.org/simple/"

Runner = Callable[..., Any]


class EgressUnavailable(RuntimeError):
    """The fetch egress proxy could not be started or did not answer."""


def _docker(runner: Runner, *args: str, check: bool = True, timeout: float = 60) -> Any:
    result = runner(["docker", *args], capture_output=True, text=True, timeout=timeout)
    if check and getattr(result, "returncode", 1) != 0:
        raise EgressUnavailable(f"docker {args[0]} failed: {(getattr(result, 'stderr', '') or '').strip()[:300]}")
    return result


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def remove_leftovers(runner: Runner = subprocess.run) -> None:
    """Remove containers and networks an earlier, killed eval run left."""
    for kind, listing in (("container", ["ps", "-aq"]), ("network", ["network", "ls", "-q"])):
        found = _docker(runner, *listing, "--filter", f"label={LABEL}", check=False)
        ids = [i for i in (getattr(found, "stdout", "") or "").split() if i]
        if ids:
            if kind == "container":
                _docker(runner, "rm", "-f", *ids, check=False)
            else:
                _docker(runner, "network", "rm", *ids, check=False)


def _probe(url: str, timeout: float) -> str | None:
    """None when a public page comes back through the proxy, else why not."""
    import httpx

    deadline = time.time() + timeout
    last = "no answer"
    while time.time() < deadline:
        try:
            with httpx.Client(proxy=url, timeout=10) as client:
                status = client.head(PROBE_URL).status_code
            if status < 500:
                return None
            last = f"HTTP {status}"
        except Exception as exc:  # noqa: BLE001 - reported, never raised from here
            last = f"{type(exc).__name__}: {exc}"[:200]
        time.sleep(1)
    return last


@contextlib.contextmanager
def proxy(repo: Path, *, runner: Runner = subprocess.run, probe: Callable[[str, float], str | None] = _probe, probe_timeout: float = 45) -> Iterator[str]:
    """Run the fetch egress proxy for the duration of the block; yields its URL."""
    remove_leftovers(runner)
    name = f"{LABEL}-{secrets.token_hex(4)}"
    config_dir = repo / "docker" / "fetch-egress"
    if not (config_dir / "squid.conf").is_file():
        raise EgressUnavailable(f"{config_dir}/squid.conf is missing")
    image = _docker(runner, "image", "inspect", IMAGE, check=False)
    if getattr(image, "returncode", 1) != 0:
        raise EgressUnavailable(f"the image {IMAGE} is not built locally (make up or make dev builds it; the eval never pulls or builds)")

    previous = signal.getsignal(signal.SIGTERM)

    def _terminate(signum, frame):  # noqa: ARG001
        raise KeyboardInterrupt("SIGTERM")

    port = _free_port()
    started = False
    try:
        with contextlib.suppress(ValueError):  # not the main thread: no handler, the finally still runs
            signal.signal(signal.SIGTERM, _terminate)
        _docker(runner, "network", "create", "--label", f"{LABEL}=1", name)
        _docker(
            runner,
            "run",
            "-d",
            "--name",
            name,
            "--label",
            f"{LABEL}=1",
            "--network",
            name,
            "--entrypoint",
            "/bin/sh",
            "-v",
            f"{config_dir}:/opt/fetch:ro",
            "--tmpfs",
            "/run/fetch",
            "-p",
            f"127.0.0.1:{port}:3128",
            IMAGE,
            "/opt/fetch/entrypoint.sh",
        )
        started = True
        url = f"http://127.0.0.1:{port}"
        why = probe(url, probe_timeout)
        if why is not None:
            logs = _docker(runner, "logs", "--tail", "20", name, check=False)
            tail = ((getattr(logs, "stdout", "") or "") + (getattr(logs, "stderr", "") or "")).strip()[-600:]
            raise EgressUnavailable(f"the fetch egress proxy did not fetch {PROBE_URL}: {why}" + (f"\n{tail}" if tail else ""))
        yield url
    finally:
        if started:
            _docker(runner, "rm", "-f", name, check=False)
        _docker(runner, "network", "rm", name, check=False)
        with contextlib.suppress(ValueError, TypeError):
            signal.signal(signal.SIGTERM, previous)
