"""T1-T3: the sandbox test can't reach your files, the network or root (#59).

Real Docker, real images (labelled, throwaway, listed in the report). The
code scanners are stubbed to ALLOW everything: containment must hold even
when they miss. Each probe is a tool; its result comes back as the tool's
test output.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
from unittest.mock import AsyncMock

import pytest
from docker_ledger import LABEL, PREFIX

pytestmark = pytest.mark.docker

PROBE = r'''
import json, os, socket, pathlib
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("probe")


def _try_read(path):
    # One letter per path (tool output is cut at 200 characters):
    # x = could not; e = an empty directory; L = listed something; R = read it.
    try:
        p = pathlib.Path(os.path.expanduser(path))
        if p.is_dir():
            return "L" if any(p.iterdir()) else "e"
        p.read_bytes()
        return "R"
    except Exception:
        return "x"


@mcp.tool()
def files() -> str:
    """Tries to read things that live on the host."""
    paths = ["~/.ssh", "~/.ssh/id_ed25519", "~/.ssh/id_rsa", "~", os.environ.get("CANARY_PATH", "/nonexistent"),
             "/var/run/docker.sock", "/app/config.yaml", "/app/backend/.omni-harness", "/run/secrets/mcp_vault_key",
             "/root/.claude", "/Users", "/home"]
    return "".join(_try_read(p) for p in paths)


@mcp.tool()
def sockets() -> str:
    """Tries to leave the sandbox over the network."""
    out = ""
    for label, host, port in json.loads(os.environ.get("TARGETS", "[]")):
        try:
            socket.create_connection((host, port), timeout=2).close()
            out += "C"
        except Exception:
            out += "x"
    try:
        socket.getaddrinfo("example.com", 443)
        out += "D"
    except Exception:
        out += "x"
    return out


@mcp.tool()
def identity() -> str:
    """Who am I, and can I write my own code or the root filesystem?"""
    out = {"uid": os.getuid()}
    for key, path in (("write_code", "/app/server.py"), ("write_root", "/var/tmp/omni-probe")):
        try:
            open(path, "a").close()
            out[key] = "WROTE"
        except Exception as e:
            out[key] = "no:" + type(e).__name__[:12]
    return json.dumps(out)


@mcp.tool()
def forks() -> str:
    """How many processes can I start?"""
    import time
    pids = []
    try:
        for _ in range(150):
            pid = os.fork()
            if pid == 0:
                time.sleep(1)
                os._exit(0)
            pids.append(pid)
        result = "all"
    except Exception:
        result = "stopped"
    for pid in pids:
        try:
            os.waitpid(pid, 0)
        except Exception:
            pass
    return "%s:%d" % (result, len(pids))
'''


class HostListener:
    """A listener on this machine's loopback, which Docker Desktop makes
    reachable from containers as host.docker.internal."""

    def __init__(self) -> None:
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen()
        self.sock.settimeout(0.5)
        self.port = self.sock.getsockname()[1]
        self.count = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self.sock.accept()
                self.count += 1
                conn.close()
            except OSError:
                continue

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        self.sock.close()


class Listener:
    """A TCP listener in a throwaway container on an ordinary bridge network:
    a literal IP the sandbox must NOT reach. It logs every connection."""

    def __init__(self, runner) -> None:
        self.name = f"{PREFIX}listener-{os.getpid()}"
        self.net = f"{PREFIX}net-{os.getpid()}"
        runner.resources.append(__import__("docker_ledger").Resource("network", self.net))
        runner.resources.append(__import__("docker_ledger").Resource("container", self.name))
        subprocess.run(["docker", "network", "create", "--label", f"{LABEL[0]}={LABEL[1]}", self.net], check=True, capture_output=True)
        code = "import socket\ns=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind(('0.0.0.0',8443));s.listen()\nwhile True:\n c,a=s.accept();print('CONNECTION',a,flush=True);c.close()"
        label = f"{LABEL[0]}={LABEL[1]}"
        run = ["docker", "run", "--pull=never", "-d", "--rm", "--name", self.name, "--label", label, "--network", self.net, "--read-only", "--cap-drop", "ALL"]
        subprocess.run([*run, "python:3.12-slim", "python", "-c", code], check=True, capture_output=True)
        self.ip = subprocess.run(["docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", self.name], capture_output=True, text=True).stdout.strip()
        # The host, as a container sees it: a literal IP, no DNS involved.
        runner.resources.append(__import__("docker_ledger").Resource("container", f"{PREFIX}hostip-{os.getpid()}"))
        probe = ["docker", "run", "--pull=never", "--rm", "--name", f"{PREFIX}hostip-{os.getpid()}", "--label", label, "--network", self.net, "python:3.12-slim"]
        lookup = "import socket;print(socket.gethostbyname('host.docker.internal'))"
        self.host_ip = subprocess.run([*probe, "python", "-c", lookup], capture_output=True, text=True).stdout.strip()

    def connections(self) -> int:
        return subprocess.run(["docker", "logs", self.name], capture_output=True, text=True).stdout.count("CONNECTION")

    def close(self) -> None:
        subprocess.run(["docker", "rm", "-f", self.name], capture_output=True)
        subprocess.run(["docker", "network", "rm", self.net], capture_output=True)


@pytest.fixture
def sandbox(builder_gateway, docker_ledger, runtime_images, monkeypatch):
    """The production manager, with the real runner (recorded) and test images."""
    manager = builder_gateway.app.state.mcp_server_manager
    manager._runner = docker_ledger
    manager._images = runtime_images
    allow = AsyncMock(return_value=type("R", (), {"decision": "allow", "reason": "stubbed: containment must hold anyway"})())
    monkeypatch.setattr("app.gateway.mcp_server_manager.scan_python_code", allow)
    monkeypatch.setattr("app.gateway.mcp_server_manager.scan_python_code_static", lambda src: None)
    return builder_gateway, manager


def _probe(gw, manager, code: str) -> dict[str, dict]:
    async def go():
        row = await gw.app.state.mcp_server_repo.create(name="probe", owner_id=gw.user_id, source_code=code)
        return await manager._run_server_sandbox_test(server_id=row["id"], user_id=gw.user_id, source_code=code)

    tools, results = gw.client.portal.call(go)
    assert {t["name"] for t in tools} == {"files", "sockets", "identity", "forks"}, tools
    out = {}
    for r in results:
        text = r.get("output") or r.get("error") or ""
        try:
            out[r["tool"]] = json.loads(text)
        except ValueError:
            out[r["tool"]] = text
    return out


def test_t1_t2_t3_the_sandbox_cannot_reach_files_network_or_root(sandbox, docker_ledger, tmp_path, monkeypatch) -> None:
    gw, manager = sandbox
    # A canary in a fresh HOME for this process: the old sandbox passed
    # HOME=Path.home() through, so the code could read it.
    canary = tmp_path / "home"
    (canary / ".ssh").mkdir(parents=True)
    (canary / ".ssh" / "id_ed25519").write_text("CANARY-PRIVATE-KEY")
    monkeypatch.setenv("HOME", str(canary))
    listener = Listener(docker_ledger)
    host = HostListener()
    try:
        targets = [["listener_ip", listener.ip, 8443], ["host_ip", listener.host_ip, host.port], ["public_ip", "1.1.1.1", 443]]
        code = PROBE.replace('os.environ.get("TARGETS", "[]")', repr(json.dumps(targets))).replace('os.environ.get("CANARY_PATH", "/nonexistent")', repr(str(canary / ".ssh" / "id_ed25519")))
        out = _probe(gw, manager, code)
    finally:
        seen = listener.connections() + host.count
        listener.close()
        host.close()

    # ~/.ssh, its keys, ~ (an empty tmpfs), the canary, docker.sock, config,
    # gateway state, the vault key, Claude credentials, /Users, /home.
    files = out["files"]
    assert len(files) == 12, out
    assert files[3] == "e", f"HOME must be an empty tmpfs: {files}"
    # Nothing was read or listed anywhere; an empty directory of the image's
    # own (/home) is all there is.
    assert set(files) <= {"x", "e"}, f"the sandbox reached a host path: {files}"
    assert files[:3] == "xxx" and files[4:11] == "xxxxxxx", f"the sandbox reached a host path: {files}"
    assert "CANARY" not in json.dumps(out)

    nets = out["sockets"]
    assert nets == "xxxx", f"listener IP, host IP, a public IP, DNS: {nets}"
    assert seen == 0, f"the listener saw {seen} connection(s) from the sandbox"

    who = out["identity"]
    assert who["uid"] == 10001, who
    assert who["write_code"].startswith("no:"), who
    assert who["write_root"].startswith("no:"), who  # read-only root filesystem
    assert str(out["forks"]).startswith("stopped:"), out["forks"]  # the pids limit
