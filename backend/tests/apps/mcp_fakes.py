"""A recording DockerRunner for the MCP builder's HTTP tests (#59).

It stands in for the docker CLI behind the same port production uses
(`app.gateway.mcp_docker.DockerRunner`), so a test sees every command the
gateway would have run, argument by argument, plus what went over stdin.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass
class Call:
    args: list[str]
    stdin: bytes | None


@dataclass
class FakeDockerRunner:
    calls: list[Call] = field(default_factory=list)
    #: verb ("build", "run", ...) -> (rc, out, err)
    results: dict[str, tuple[int, str, str]] = field(default_factory=dict)
    #: When set, `docker build` waits on this event (the race tests hold it).
    hold_build: asyncio.Event | None = None
    build_started: asyncio.Event | None = None

    async def run(self, args: list[str], *, stdin: bytes | None = None, timeout: float = 120.0) -> tuple[int, str, str]:
        self.calls.append(Call(list(args), stdin))
        verb = args[1] if len(args) > 1 else ""
        if verb == "build" and self.hold_build is not None:
            if self.build_started is not None:
                self.build_started.set()
            await self.hold_build.wait()
        if verb in self.results:
            return self.results[verb]
        if verb == "run":
            return 0, "c0ffee" * 10 + "\n", ""
        return 0, "", ""

    async def run_bytes(self, args: list[str], *, stdin: bytes | None = None, timeout: float = 120.0) -> tuple[int, bytes, str]:
        rc, out, err = await self.run(args, stdin=stdin, timeout=timeout)
        return rc, out.encode(), err

    def verbs(self) -> list[str]:
        return [c.args[1] for c in self.calls if len(c.args) > 1]

    def ran(self) -> list[Call]:
        return [c for c in self.calls if len(c.args) > 1 and c.args[1] == "run"]
