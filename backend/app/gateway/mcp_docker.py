"""The one way the MCP builder talks to Docker (Feature 006, #59).

Every ``docker`` command the builder issues goes through a ``DockerRunner``.
Production uses ``CliDockerRunner`` (the ``docker`` CLI, as the gateway image
ships it); tests swap in a recording fake through the same port, so what the
gateway would have run can be asserted argument by argument.

Values that must stay out of ``docker inspect`` and out of process listings
(secrets, the proxy login, the endpoint token) are only ever passed as
``stdin``, never as arguments.
"""

from __future__ import annotations

import asyncio
import os
from typing import Protocol


class DockerRunner(Protocol):
    async def run(self, args: list[str], *, stdin: bytes | None = None, timeout: float = 120.0) -> tuple[int, str, str]:
        """Run ``docker <args...>``; returns (returncode, stdout, stderr)."""
        ...


class CliDockerRunner:
    """``DockerRunner`` over the ``docker`` CLI."""

    async def run(self, args: list[str], *, stdin: bytes | None = None, timeout: float = 120.0) -> tuple[int, str, str]:
        if not args or args[0] != "docker":
            raise ValueError("DockerRunner only runs the docker CLI")
        env = None
        if len(args) > 1 and args[1] == "build":
            # The classic builder resolves FROM against the local image store
            # only. BuildKit was seen (Docker 29.5.3) trying docker.io for a
            # FROM naming a local image ID, so it is never used here.
            env = {**os.environ, "DOCKER_BUILDKIT": "0"}
        proc = await asyncio.create_subprocess_exec(
            *args,
            env=env,
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(stdin), timeout=timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise
        return proc.returncode or 0, (out or b"").decode(errors="replace"), (err or b"").decode(errors="replace")
