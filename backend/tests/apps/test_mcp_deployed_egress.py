"""The deployed topology, on real Docker (#59): T7, T7d, T9, T13, T14, T16, T20.

A built server runs on an --internal network with a Squid sidecar as its only
neighbour. These tests deploy a probe server through the production deploy
path (`_run_docker_deploy`, with the real runner and real images, labelled and
throwaway), then call its tools through the sidecar's endpoint, as the gateway
does.

A test-only DNS server (tests/apps/assets/fake_dns.py) is the upstream of the
sidecar's dnsmasq, which keeps --stop-dns-rebind on; and the sidecar is also
attached to the listener's network, so it COULD route to the private target:
refusals have to come from dnsmasq and Squid's ACLs, not from routing.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from docker_ledger import LABEL, PREFIX, Resource
from test_mcp_sandbox_escape import HostListener

from omniharness.persistence.mcp_server.approval import code_sha256

pytestmark = pytest.mark.docker

FAKE_DNS = (Path(__file__).parent / "assets" / "fake_dns.py").read_text()
LABEL_ARG = f"{LABEL[0]}={LABEL[1]}"
STORED_SECRET = "ghp_STOREDSECRETVALUE0123456789abcdef"

PROBE = r'''
import json, os, socket, ssl, base64, urllib.parse
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("egress-probe")
HOSTS = ["https://allowed.test/", "https://rebind.test/", "https://api.github.com/"]


@mcp.tool()
def raw(host: str, port: int) -> str:
    """A socket that ignores the proxy."""
    try:
        socket.create_connection((host, port), timeout=3).close()
        return "C"
    except Exception as e:
        return "x:" + type(e).__name__


@mcp.tool()
def dns(name: str) -> str:
    try:
        socket.getaddrinfo(name, 443)
        return "D"
    except Exception as e:
        return "x:" + type(e).__name__


@mcp.tool()
def connect(target: str, sni: str = "-", tls: bool = True, auth: bool = True) -> str:
    """CONNECT through the sidecar, then (optionally) a TLS hello with SNI."""
    proxy = urllib.parse.urlparse(os.environ["HTTPS_PROXY"])
    s = socket.create_connection((proxy.hostname, proxy.port), timeout=20)
    req = "CONNECT %s HTTP/1.1\r\nHost: %s\r\n" % (target, target)
    if auth:
        cred = base64.b64encode(("%s:%s" % (proxy.username, proxy.password)).encode()).decode()
        req += "Proxy-Authorization: Basic %s\r\n" % cred
    s.sendall((req + "\r\n").encode())
    head = b""
    while b"\r\n\r\n" not in head:
        chunk = s.recv(4096)
        if not chunk:
            break
        head += chunk
    status = head.split(b"\r\n", 1)[0].decode(errors="replace")
    code = status.split(" ")[1] if " " in status else "?"
    if code != "200" or not tls:
        s.close()
        return code
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        t = ctx.wrap_socket(s, server_hostname=None if sni == "" else (target.split(":")[0] if sni == "-" else sni))
    except Exception as e:
        return "200|tls:" + type(e).__name__
    # Inside the tunnel: Squid's own error page (it refused the tunnel and
    # answers itself) carries X-Squid-Error; anything else came from upstream.
    t.sendall(("GET / HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n\r\n" % target.split(":")[0]).encode())
    data = b""
    try:
        while b"\r\n\r\n" not in data and len(data) < 16384:
            chunk = t.recv(4096)
            if not chunk:
                break
            data += chunk
    except Exception as e:
        return "200|read:" + type(e).__name__
    t.close()
    for line in data.split(b"\r\n"):
        if line.lower().startswith(b"x-squid-error:"):
            return "squid:" + line.split(b":", 1)[1].strip().split(b" ")[0].decode()
    return "upstream:" + data.split(b"\r\n", 1)[0].decode(errors="replace")[:20]


@mcp.tool()
def plain() -> str:
    """Bytes that are not TLS inside an allowed tunnel."""
    proxy = urllib.parse.urlparse(os.environ["HTTPS_PROXY"])
    s = socket.create_connection((proxy.hostname, proxy.port), timeout=20)
    cred = base64.b64encode(("%s:%s" % (proxy.username, proxy.password)).encode()).decode()
    s.sendall(("CONNECT api.github.com:443 HTTP/1.1\r\nProxy-Authorization: Basic %s\r\n\r\n" % cred).encode())
    s.recv(4096)
    s.sendall(b"GET / HTTP/1.0\r\nHost: api.github.com\r\n\r\n")
    try:
        data = s.recv(4096)
        return "closed" if not data else "got:" + data[:12].decode(errors="replace")
    except Exception as e:
        return "x:" + type(e).__name__


@mcp.tool()
def head(url: str) -> str:
    """An ordinary client through HTTPS_PROXY (the positive control)."""
    import httpx
    try:
        return str(httpx.head(url, timeout=15).status_code)
    except Exception as e:
        return "x:" + type(e).__name__


@mcp.tool()
def env_has(name: str) -> str:
    """Whether a key reached this process (its length only, never its value)."""
    v = os.environ.get(name)
    return "unset" if v is None else "set:%d" % len(v)


@mcp.tool()
def secrets_file() -> str:
    st = os.stat("/run/omni/secrets")
    d = os.stat("/run/omni")
    return "%o %d %o" % (st.st_mode & 0o777, st.st_uid, d.st_mode & 0o777)
'''


def _docker(*args: str) -> str:
    return subprocess.run(["docker", *args], capture_output=True, text=True).stdout.strip()


class Targets:
    """A listener and a fake DNS server on an ordinary test network."""

    def __init__(self, ledger, names: dict) -> None:
        pid = os.getpid()
        self.net = f"{PREFIX}tnet-{pid}"
        self.listener = f"{PREFIX}tlisten-{pid}"
        self.dns = f"{PREFIX}tdns-{pid}"
        for kind, name in (("network", self.net), ("container", self.listener), ("container", self.dns)):
            ledger.resources.append(Resource(kind, name))
        _docker("network", "create", "--label", LABEL_ARG, self.net)
        code = "import socket\ns=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind(('0.0.0.0',443));s.listen()\nwhile True:\n c,a=s.accept();print('CONNECTION',a,flush=True);c.close()"
        common = ["run", "--pull=never", "-d", "--rm", "--label", LABEL_ARG, "--network", self.net, "--read-only", "--cap-drop", "ALL", "--user", "65534:65534", "--sysctl", "net.ipv4.ip_unprivileged_port_start=0"]
        _docker(*common, "--name", self.listener, "python:3.12-slim", "python", "-c", code)
        self.listener_ip = _docker("inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", self.listener)
        resolved = {k: (v.replace("LISTENER", self.listener_ip) if isinstance(v, str) else [x.replace("LISTENER", self.listener_ip) for x in v]) for k, v in names.items()}
        _docker(*common, "--name", self.dns, "-e", f"NAMES={json.dumps(resolved)}", "python:3.12-slim", "python", "-c", FAKE_DNS)
        self.dns_ip = _docker("inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", self.dns)

    def connections(self) -> int:
        return _docker("logs", self.listener).count("CONNECTION")

    def close(self) -> None:
        _docker("rm", "-f", self.listener, self.dns)
        attached = _docker("network", "inspect", "-f", "{{range $k, $v := .Containers}}{{$v.Name}} {{end}}", self.net).split()
        for name in attached:
            _docker("network", "disconnect", "-f", self.net, name)
        _docker("network", "rm", self.net)


def _deploy(gw, manager, ledger, runtime_images, monkeypatch, *, hosts: list[str], upstream: str | None = None, stop_dns_rebind: bool = True) -> tuple[str, dict]:
    manager._runner = ledger
    manager._images = runtime_images
    if upstream:
        manager._egress_upstream_dns = upstream
    manager._egress_stop_dns_rebind = stop_dns_rebind
    repo = gw.app.state.mcp_server_repo
    vault = gw.app.state.mcp_secrets_vault
    sha = code_sha256(PROBE)

    async def go():
        row = await repo.create(name="egress-probe", owner_id=gw.user_id, source_code=PROBE)
        sid = row["id"]
        # What a passing sandbox test stores for this code (its hosts, its hash).
        await repo.update_build_result(sid, phase="verified", tools_discovered=[], test_results=[], last_verified_at=None, user_id=gw.user_id, tested_code_sha256=sha, egress_hosts=hosts)
        await vault.store(server_id=sid, owner_id=gw.user_id, key_name="GITHUB_TOKEN", plaintext_value=STORED_SECRET)
        await repo.set_pending_approval(sid, {"code_sha256": sha, "egress_hosts": hosts, "tool_tiers": {}}, user_id=gw.user_id)
        from app.gateway.mcp_server_manager import MCPBuildRecord, _init_deploy_steps

        manager._records[sid] = MCPBuildRecord(server_id=sid, phase="deploying", owner_id=gw.user_id, deploy_steps=_init_deploy_steps())
        await manager._run_docker_deploy(server_id=sid, user_id=gw.user_id, source=PROBE, expected_sha256=sha)
        record = manager._records[sid]
        assert record.phase == "deployed", (record.phase, record.error)
        token = await manager.inbound_token(sid)
        return sid, {"port": record.container_port, "token": token}

    return gw.client.portal.call(go)


def _call(url: str, token: str | None, calls: list[tuple[str, dict]]) -> list[str]:
    import asyncio

    from mcp import ClientSession
    from mcp.client.sse import sse_client

    async def go():
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with sse_client(url, headers=headers, timeout=10, sse_read_timeout=120) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                out = []
                for name, args in calls:
                    res = await s.call_tool(name, args)
                    out.append(res.content[0].text if res.content else "")
                return out

    return asyncio.run(go())


@pytest.fixture
def probe_env(builder_gateway, docker_ledger, runtime_images, monkeypatch):
    allow = AsyncMock(return_value=type("R", (), {"decision": "allow", "reason": "stubbed"})())
    monkeypatch.setattr("app.gateway.mcp_server_manager.scan_python_code", allow)
    manager = builder_gateway.app.state.mcp_server_manager
    yield builder_gateway, manager
    # Undeploy everything this test deployed (the production undeploy path).
    for sid in list(manager._records):
        try:
            builder_gateway.client.portal.call(lambda: manager.undeploy(server_id=sid, user_id=builder_gateway.user_id))
        except Exception:
            pass


def test_deployed_egress_is_the_allowlist_and_nothing_else(probe_env, docker_ledger, runtime_images, monkeypatch) -> None:
    gw, manager = probe_env
    targets = Targets(docker_ledger, {"allowed.test": ["LISTENER"], "rebind.test": "flip:198.51.100.7,LISTENER"})
    host = HostListener()
    docker_ledger.resources.append(Resource("container", f"{PREFIX}thostip-{os.getpid()}"))
    host_ip = _docker(
        "run", "--pull=never", "--rm", "--name", f"{PREFIX}thostip-{os.getpid()}", "--label", LABEL_ARG, "--network", targets.net, "python:3.12-slim", "python", "-c", "import socket;print(socket.gethostbyname('host.docker.internal'))"
    )
    try:
        sid, info = _deploy(gw, manager, docker_ledger, runtime_images, monkeypatch, hosts=["allowed.test", "rebind.test", "api.github.com"], upstream=targets.dns_ip)
        names = manager._names(sid)
        # Give the sidecar a ROUTE to the private target: refusals must be ACLs.
        _docker("network", "connect", targets.net, names["egress"])
        url = manager.endpoint_url(sid, info["port"])
        assert url.startswith("http://127.0.0.1:"), url

        calls = [
            ("connect", {"target": "blocked.test:443"}),  # 0 T7(1) not allowlisted
            ("raw", {"host": targets.listener_ip, "port": 443}),  # 1 T7(2) literal IP, no proxy
            ("raw", {"host": names_ip(names["egress"], targets.net), "port": 3128}),  # 2 the sidecar's OTHER side
            ("connect", {"target": "allowed.test:443"}),  # 3 T7(3) allowlisted, resolves private
            ("dns", {"name": "example.com"}),  # 4 T13
            ("dns", {"name": "allowed.test"}),  # 5 T13
            ("connect", {"target": "allowed.test:443", "auth": False}),  # 6 T14 no proxy login
            ("secrets_file", {}),  # 7 T16
        ]
        calls += [("connect", {"target": "rebind.test:443"})] * 10  # 8..17 T7(4) rebinding
        calls += [("raw", {"host": host_ip, "port": host.port})]  # 18 T7(2) the host, by literal IP
        out = _call(url, info["token"], calls)
        seen = targets.connections() + host.count
        # T14: from the OUTER network, the forward proxy is not there at all.
        pub_ip = names_ip(names["egress"], names["pub"])
        probe_outer = f"import socket\ntry:\n socket.create_connection(('{pub_ip}',3128),timeout=3).close();print('OPEN')\nexcept Exception as e:\n print('x:'+type(e).__name__)"
        docker_ledger.resources.append(Resource("container", f"{PREFIX}touter-{os.getpid()}"))
        outer = _docker("run", "--pull=never", "--rm", "--name", f"{PREFIX}touter-{os.getpid()}", "--label", LABEL_ARG, "--network", names["pub"], "python:3.12-slim", "python", "-c", probe_outer)
        sidecar_log = subprocess.run(["docker", "logs", names["egress"]], capture_output=True, text=True)
        sidecar_log = sidecar_log.stdout + sidecar_log.stderr
    finally:
        targets.close()
        host.close()

    assert out[0] in ("403", "squid:ERR_ACCESS_DENIED"), out[0]
    assert out[18].startswith("x:"), out[18]
    assert outer.startswith("x:"), f"the forward proxy answered on the outer network: {outer}"
    assert out[1].startswith("x:"), out[1]
    assert out[2].startswith("x:"), out[2]
    # dnsmasq dropped the private answer, so Squid could not resolve it: the
    # tunnel never reached anything (the client sees the TLS fail), and the
    # listener saw nothing. dnsmasq says why.
    assert not out[3].startswith("upstream:") and out[3] != "200|tls-ok", out[3]
    assert "possible DNS-rebind attack detected: allowed.test" in sidecar_log
    assert out[4].startswith("x:") and out[5].startswith("x:"), out[4:6]
    assert out[6] == "407", out[6]
    assert out[7] == "400 10001 500", out[7]
    assert not any(o.startswith("upstream:") for o in out[8:]), out[8:]
    assert "possible DNS-rebind attack detected: rebind.test" in sidecar_log
    assert seen == 0, f"the private listener saw {seen} connection(s)"

    # T14: the endpoint refuses without its token, and with a wrong one.
    import httpx

    for headers in ({}, {"Authorization": "Bearer " + "0" * 48}):
        r = httpx.get(url, headers=headers, timeout=10)
        assert r.status_code == 403, (headers, r.status_code)

    # T20 and T9 (docker): nothing secret in docker inspect, no port but 127.0.0.1.
    password = None
    for c in (names["server"], names["egress"]):
        dump = subprocess.run(["docker", "inspect", c], capture_output=True, text=True).stdout
        for secret in (STORED_SECRET, info["token"]):
            assert secret not in dump and base64.b64encode(secret.encode()).decode() not in dump, c
        assert '"HostIp": "0.0.0.0"' not in dump and '"HostIp": ""' not in dump
    ports = _docker("port", names["egress"])
    assert ports and all("127.0.0.1:" in line for line in ports.splitlines()), ports
    assert _docker("port", names["server"]) == ""
    del password


def names_ip(container: str, network: str) -> str:
    """The sidecar's address on the test network: the server must not reach it."""
    return _docker("inspect", "-f", '{{(index .NetworkSettings.Networks "' + network + '").IPAddress}}', container)


def test_t7d_squids_own_private_destination_acl(probe_env, docker_ledger, runtime_images, monkeypatch) -> None:
    """With dnsmasq passing private answers (a renderer parameter only this
    test uses), Squid's dst ACL alone refuses an allowlisted name that
    resolves to a private address."""
    gw, manager = probe_env
    targets = Targets(docker_ledger, {"allowed.test": ["LISTENER"]})
    try:
        sid, info = _deploy(gw, manager, docker_ledger, runtime_images, monkeypatch, hosts=["allowed.test"], upstream=targets.dns_ip, stop_dns_rebind=False)
        _docker("network", "connect", targets.net, manager._names(sid)["egress"])
        out = _call(manager.endpoint_url(sid, info["port"]), info["token"], [("connect", {"target": "allowed.test:443"})])
        seen = targets.connections()
    finally:
        targets.close()
    assert out in (["403"], ["squid:ERR_ACCESS_DENIED"]), out
    assert seen == 0


@pytest.mark.internet
def test_t7_positive_control_and_t17_sni(probe_env, docker_ledger, runtime_images, monkeypatch) -> None:
    """Through the production DNS path (Docker's resolver), an allowlisted
    public host is reachable only when the TLS name the client sends equals
    the CONNECT host: no SNI, or SNI naming another (even allowlisted) host, is
    refused. Needs internet; skipped (and reported) without it."""
    gw, manager = probe_env
    sid, info = _deploy(gw, manager, docker_ledger, runtime_images, monkeypatch, hosts=["api.github.com", "github.com"])
    url = manager.endpoint_url(sid, info["port"])
    out = _call(
        url,
        info["token"],
        [
            ("dns", {"name": "api.github.com"}),
            ("head", {"url": "https://api.github.com/"}),
            ("connect", {"target": "api.github.com:443"}),
            ("connect", {"target": "API.GitHub.com.:443", "sni": "api.github.com"}),
            ("connect", {"target": "api.github.com:443", "sni": "evil.example"}),
            ("connect", {"target": "api.github.com:443", "sni": ""}),
            ("connect", {"target": "api.github.com:80"}),
            ("connect", {"target": "140.82.112.6:443"}),
            ("connect", {"target": "[::1]:443"}),
            ("connect", {"target": "2130706433:443"}),
            ("connect", {"target": "user@api.github.com:443"}),
            ("connect", {"target": "xn--pi-6kc.github.com:443"}),
            ("plain", {}),
            ("connect", {"target": "api.github.com:443", "sni": "github.com"}),  # 13: another ALLOWLISTED name
        ],
    )
    if out[1].startswith("x:"):
        pytest.skip(f"no internet from Docker here ({out[1]}): the positive control did not run (skipped, not passed)")
    assert out[0].startswith("x:"), "the server itself still resolves nothing"
    assert out[1] in ("200", "301", "302", "403"), out[1]
    assert out[2].startswith("upstream:HTTP/1.1"), out[2]
    assert out[3].startswith("upstream:HTTP/1.1"), out[3]  # CONNECT host normalised (case, one trailing dot)
    # The TLS name the client sends must EQUAL the CONNECT host: another name
    # (even an allowlisted one), or no name at all, never reaches upstream.
    assert not out[4].startswith("upstream:"), out[4]
    assert not out[5].startswith("upstream:"), out[5]
    assert not out[13].startswith("upstream:"), out[13]
    for o in out[6:12]:
        assert o in ("403", "400") or o.startswith("squid:"), out[6:12]
    assert not out[12].startswith("got:HTTP"), out[12]


def _serves(url: str, token: str, timeout: float = 120.0) -> list[str] | None:
    """Call env_has through the sidecar until it answers (or give up)."""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return _call(url, token, [("env_has", {"name": "GITHUB_TOKEN"}), ("secrets_file", {})])
        except Exception:
            time.sleep(2)
    return None


def test_a_restarted_server_or_sidecar_gets_its_files_again(probe_env, docker_ledger, runtime_images, monkeypatch) -> None:
    """Docker restarts a container (its tmpfs is empty, it waits for its
    files): the gateway, watching docker events, hands them over again; never
    through env vars, and docker inspect still shows no secret."""
    gw, manager = probe_env
    sid, info = _deploy(gw, manager, docker_ledger, runtime_images, monkeypatch, hosts=["api.github.com"])
    url = manager.endpoint_url(sid, info["port"])
    names = manager._names(sid)
    gw.client.portal.call(manager.start_event_watcher)
    try:
        assert _call(url, info["token"], [("env_has", {"name": "GITHUB_TOKEN"})]) == [f"set:{len(STORED_SECRET)}"]
        for container in (names["server"], names["egress"]):
            _docker("restart", container)
            out = _serves(url, info["token"])
            assert out == [f"set:{len(STORED_SECRET)}", "400 10001 500"], (container, out)
            for c in (names["server"], names["egress"]):
                dump = subprocess.run(["docker", "inspect", c], capture_output=True, text=True).stdout
                for secret in (STORED_SECRET, info["token"]):
                    assert secret not in dump and base64.b64encode(secret.encode()).decode() not in dump, c
                assert "GITHUB_TOKEN" not in json.dumps(json.loads(dump)[0]["Config"].get("Env") or [])
    finally:
        gw.client.portal.call(manager.stop_event_watcher)
