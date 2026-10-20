"""Docker for the MCP builder's container tests (#59), on the developer's
Docker Desktop, with throwaway resources only:

* every container, image and network a test creates is labelled
  ``omni.mcp.test=<run id>`` and named ``omni-mcp-t-*``;
* every container is checked to have NO mounts the first time the gateway
  talks to it (a host mount fails the test);
* everything created is listed in the pytest report (and in
  ``test-results/docker-resources.json``), and anything left at the end is
  removed and FAILS the run.

Where Docker is not available the tests skip, and the skip is reported.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from app.gateway.mcp_docker import CliDockerRunner

RUN_ID = uuid.uuid4().hex[:10]
LABEL = ("omni.mcp.test", RUN_ID)
PREFIX = "omni-mcp-t-"
REPORT = Path(__file__).resolve().parents[2] / "test-results" / "docker-resources.json"


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], capture_output=True, timeout=20).returncode == 0
    except Exception:
        return False


@dataclass
class Resource:
    kind: str
    name: str
    created_at: float = field(default_factory=time.time)
    mounts: str | None = None
    removed_at: float | None = None


@dataclass
class LedgerRunner(CliDockerRunner):
    """The production CLI runner, recording what it creates."""

    resources: list[Resource] = field(default_factory=list)
    mount_problems: list[str] = field(default_factory=list)
    _checked: set = field(default_factory=set)

    def _note(self, args: list[str]) -> None:
        verb = args[1] if len(args) > 1 else ""
        if verb in ("run", "create") and "--name" in args:
            self.resources.append(Resource("container", args[args.index("--name") + 1]))
        elif verb == "build" and "-t" in args:
            self.resources.append(Resource("image", args[args.index("-t") + 1]))
        elif verb == "network" and len(args) > 2 and args[2] == "create":
            self.resources.append(Resource("network", args[-1]))

    async def _check_mounts(self, container: str) -> None:
        if container in self._checked:
            return
        self._checked.add(container)
        rc, out, _ = await super().run_bytes(["docker", "container", "inspect", "-f", "{{json .Mounts}}", container])
        mounts = out.decode().strip()
        for r in self.resources:
            if r.kind == "container" and r.name == container:
                r.mounts = mounts
        if rc == 0 and mounts not in ("[]", "null"):
            self.mount_problems.append(f"{container}: {mounts}")

    async def run_bytes(self, args, *, stdin=None, timeout=120.0):
        self._note(args)
        if len(args) > 2 and args[1] == "exec":
            target = next((a for a in args[2:] if a.startswith(PREFIX)), None)
            if target:
                # Sandbox-test containers are started by the MCP stdio client,
                # not through this runner: they are recorded here, at the
                # first file handed to them.
                if not any(r.kind == "container" and r.name == target for r in self.resources):
                    self.resources.append(Resource("container", target))
                await self._check_mounts(target)
        return await super().run_bytes(args, stdin=stdin, timeout=timeout)

    def cleanup(self) -> list[str]:
        """Remove everything still carrying this run's label; returns leftovers."""
        leftovers: list[str] = []
        flt = f"label={LABEL[0]}={LABEL[1]}"
        for kind, cmd in (("container", ["docker", "ps", "-aq", "--filter", flt]), ("network", ["docker", "network", "ls", "-q", "--filter", flt])):
            ids = subprocess.run(cmd, capture_output=True, text=True).stdout.split()
            for i in ids:
                leftovers.append(f"{kind} {i}")
                rm = ["docker", "rm", "-f", i] if kind == "container" else ["docker", "network", "rm", i]
                subprocess.run(rm, capture_output=True)
        images = subprocess.run(["docker", "images", "-q", "--filter", flt], capture_output=True, text=True).stdout.split()
        for i in dict.fromkeys(images):
            subprocess.run(["docker", "rmi", "-f", i], capture_output=True)
        for r in self.resources:
            r.removed_at = time.time()
        return leftovers

    def report(self) -> list[dict]:
        def hms(t: float | None) -> str | None:
            return time.strftime("%H:%M:%S", time.localtime(t)) if t else None

        rows = [{"kind": r.kind, "name": r.name, "mounts": r.mounts, "created": hms(r.created_at), "removed": hms(r.removed_at)} for r in self.resources]
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps({"run": RUN_ID, "label": "=".join(LABEL), "resources": rows}, indent=2))
        return rows
