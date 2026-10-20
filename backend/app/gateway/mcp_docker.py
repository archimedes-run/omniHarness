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

    async def run_bytes(self, args: list[str], *, stdin: bytes | None = None, timeout: float = 120.0) -> tuple[int, bytes, str]:
        """As ``run``, with stdout as bytes (a tar on stdout)."""
        ...


#: Verbs that talk to a registry: never issued by the gateway (#59). The one
#: approved download (the digest-pinned Alpine base) is pulled by a person.
REGISTRY_VERBS = frozenset({"pull", "push", "login", "logout", "search"})


class RegistryContactError(ValueError):
    """A docker command that could contact a registry was refused."""


def check_no_registry(args: list[str]) -> None:
    """Refuse any docker command that could reach a registry (#59).

    * ``pull``/``push``/``login``/``search`` are never run;
    * ``run`` and ``create`` must say ``--pull=never`` (a missing image is an
      error, never a download);
    * ``build`` must say ``--pull=false`` (and the runner forces the classic
      builder: BuildKit was seen resolving a local image ID on docker.io).
    """
    verb = args[1] if len(args) > 1 else ""
    if verb in REGISTRY_VERBS:
        raise RegistryContactError(f"docker {verb} is never run by the gateway")
    if verb in ("run", "create") and "--pull=never" not in args:
        raise RegistryContactError(f"docker {verb} without --pull=never could download an image")
    if verb == "build" and "--pull=false" not in args:
        raise RegistryContactError("docker build without --pull=false could download a base image")


class CliDockerRunner:
    """``DockerRunner`` over the ``docker`` CLI."""

    async def run(self, args: list[str], *, stdin: bytes | None = None, timeout: float = 120.0) -> tuple[int, str, str]:
        rc, out, err = await self.run_bytes(args, stdin=stdin, timeout=timeout)
        return rc, out.decode(errors="replace"), err

    async def run_bytes(self, args: list[str], *, stdin: bytes | None = None, timeout: float = 120.0) -> tuple[int, bytes, str]:
        if not args or args[0] != "docker":
            raise ValueError("DockerRunner only runs the docker CLI")
        check_no_registry(args)
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
        return proc.returncode or 0, out or b"", (err or b"").decode(errors="replace")
