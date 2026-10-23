"""The container sandbox: a key per sandbox (#98), default seccomp (#99), the
registries-only egress proxy, and bash at Tier 2 because of them.

The Docker end-to-end half (npm/pip through the proxy, everything else
refused, one sandbox unable to drive another) needs Docker and the network:
OMNI_SANDBOX_DOCKER_E2E=1 runs it (scripts/sandbox-egress-e2e.sh).
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
EGRESS = REPO / "docker" / "sandbox-egress"
REGISTRIES = {"registry.npmjs.org", "pypi.org", "files.pythonhosted.org"}


def _run_cmd(monkeypatch, *, name: str = "sb1", environment: dict | None = None) -> list[str]:
    from omniharness.community.aio_sandbox import local_backend as lb

    captured: dict = {}

    class _R:
        stdout = "cid\n"
        returncode = 0
        stderr = ""

    def fake_run(cmd, *a, **k):
        captured["cmd"] = cmd
        return _R()

    monkeypatch.setenv("OMNI_HARNESS_SANDBOX_NETWORK", "omni-harness-dev-sandboxes")
    monkeypatch.setattr(lb.LocalContainerBackend, "_detect_runtime", lambda self: "docker")
    monkeypatch.setattr(lb.subprocess, "run", fake_run)
    backend = lb.LocalContainerBackend(image="img", base_port=8080, container_prefix="omni-harness-sandbox", config_mounts=[], environment=environment or {})
    backend.create("t1", name)
    return captured["cmd"]


def _env(cmd: list[str]) -> dict[str, str]:
    return dict(cmd[i + 1].split("=", 1) for i, a in enumerate(cmd) if a == "-e")


# ── #98: a key per sandbox ──────────────────────────────────────────────────


def test_each_sandbox_starts_with_its_own_key_derived_from_the_gateway_secret(monkeypatch) -> None:
    monkeypatch.setenv("OMNI_HARNESS_INTERNAL_AUTH_TOKEN", "gateway-secret-xyz")
    a = _env(_run_cmd(monkeypatch, name="aaa"))["SANDBOX_API_KEY"]
    b = _env(_run_cmd(monkeypatch, name="bbb"))["SANDBOX_API_KEY"]
    assert a and b and a != b, "two sandboxes share a key: one can drive the other"
    assert "gateway-secret-xyz" not in a + b, "the gateway secret itself reached a sandbox"
    from omniharness.community.aio_sandbox.sandbox_auth import sandbox_api_key

    assert a == sandbox_api_key("omni-harness-sandbox-aaa"), "a restarted gateway could not derive the key again"


def test_a_configured_environment_cannot_replace_the_key(monkeypatch) -> None:
    monkeypatch.setenv("OMNI_HARNESS_INTERNAL_AUTH_TOKEN", "s")
    cmd = _run_cmd(monkeypatch, environment={"SANDBOX_API_KEY": "chosen-by-config"})
    keys = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-e" and cmd[i + 1].startswith("SANDBOX_API_KEY=")]
    assert keys[-1] != "SANDBOX_API_KEY=chosen-by-config", "docker keeps the LAST -e: config chose the key"


def test_without_the_gateway_secret_no_sandbox_starts(monkeypatch) -> None:
    monkeypatch.delenv("OMNI_HARNESS_INTERNAL_AUTH_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="OMNI_HARNESS_INTERNAL_AUTH_TOKEN"):
        _run_cmd(monkeypatch)


def test_every_call_to_a_local_sandbox_carries_its_key(monkeypatch) -> None:
    monkeypatch.setenv("OMNI_HARNESS_INTERNAL_AUTH_TOKEN", "s")
    from omniharness.community.aio_sandbox import backend as be
    from omniharness.community.aio_sandbox.aio_sandbox import AioSandbox
    from omniharness.community.aio_sandbox.sandbox_auth import HEADER, auth_headers, sandbox_api_key

    seen = {}

    class _Resp:
        status_code = 200

    monkeypatch.setattr(be.requests, "get", lambda url, timeout, headers: seen.update(headers) or _Resp())
    assert be.wait_for_sandbox_ready("http://x:8080", timeout=1, headers=auth_headers("omni-harness-sandbox-c"))
    assert seen == {HEADER: sandbox_api_key("omni-harness-sandbox-c")}

    sandbox = AioSandbox(id="c", base_url="http://x:8080", headers=auth_headers("omni-harness-sandbox-c"))
    sent = sandbox._client._client_wrapper.get_headers()
    assert sent.get(HEADER) == sandbox_api_key("omni-harness-sandbox-c"), "the API client sends no key"
    assert auth_headers(None) == {}, "a remote (provisioner) sandbox is not keyed here"


def test_the_provider_keys_every_client_it_builds() -> None:
    source = (REPO / "backend/packages/harness/omniharness/community/aio_sandbox/aio_sandbox_provider.py").read_text()
    built = re.findall(r"AioSandbox\(([^)]*)\)", source)
    assert built and all("headers=auth_headers(" in b for b in built), built
    assert all("headers=auth_headers(" in c for c in re.findall(r"wait_for_sandbox_ready\(([^)]*)\)", source))


# ── #99: Docker's default seccomp profile ───────────────────────────────────


def test_sandboxes_run_under_the_default_seccomp_profile(monkeypatch) -> None:
    monkeypatch.setenv("OMNI_HARNESS_INTERNAL_AUTH_TOKEN", "s")
    cmd = " ".join(_run_cmd(monkeypatch))
    assert "seccomp=unconfined" not in cmd and "--privileged" not in cmd, cmd


# ── egress: registries only, GET/HEAD, 443 ──────────────────────────────────


def test_with_the_proxy_configured_a_sandbox_trusts_its_ca_and_uses_it(monkeypatch) -> None:
    monkeypatch.setenv("OMNI_HARNESS_INTERNAL_AUTH_TOKEN", "s")
    monkeypatch.setenv("OMNI_HARNESS_SANDBOX_EGRESS_PROXY", "http://omni-harness-sandbox-egress:3128")
    monkeypatch.setenv("OMNI_HARNESS_SANDBOX_EGRESS_CA_VOLUME", "ca-vol")
    cmd = _run_cmd(monkeypatch)
    env = _env(cmd)
    for key in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        assert env[key] == "http://omni-harness-sandbox-egress:3128"
    assert env["NODE_EXTRA_CA_CERTS"] == env["PIP_CERT"] == "/etc/omni-egress/ca.crt"
    assert "type=volume,src=ca-vol,dst=/etc/omni-egress,readonly" in cmd, "the CA must be mounted read-only"


def test_without_the_proxy_a_sandbox_has_no_proxy_settings(monkeypatch) -> None:
    monkeypatch.setenv("OMNI_HARNESS_INTERNAL_AUTH_TOKEN", "s")
    monkeypatch.delenv("OMNI_HARNESS_SANDBOX_EGRESS_PROXY", raising=False)
    env = _env(_run_cmd(monkeypatch))
    assert not {"HTTPS_PROXY", "HTTP_PROXY", "NODE_EXTRA_CA_CERTS"} & env.keys()


def _squid_lines() -> list[str]:
    return [line.strip() for line in (EGRESS / "squid.conf").read_text().splitlines() if line.strip() and not line.startswith("#")]


def test_squid_allows_only_the_registries_by_get_and_head_on_443() -> None:
    lines = _squid_lines()
    [registries] = [line for line in lines if line.startswith("acl registries dstdomain ")]
    assert set(registries.split()[3:]) == REGISTRIES, registries
    access = [line for line in lines if line.startswith("http_access ")]
    assert access == [
        "http_access deny !sandboxes",
        "http_access deny !tls_port",
        "http_access deny !CONNECT !https",
        "http_access deny ip_literal",
        "http_access deny !registries",
        "http_access deny private_dst",
        "http_access allow CONNECT",
        "http_access deny !read_only",
        "http_access allow sandboxes",
        "http_access deny all",
    ], "the order IS the policy: every deny precedes the allows"
    assert "acl tls_port port 443" in lines and "acl read_only method GET HEAD" in lines
    # Bumped so the method is visible; upstream certificates are verified.
    assert "ssl_bump bump all" in lines and "sslproxy_cert_error deny all" in lines
    assert "host_verify_strict on" in lines and "cache deny all" in lines


def test_the_proxy_ca_is_name_constrained_and_its_key_stays_in_the_container() -> None:
    script = (EGRESS / "entrypoint.sh").read_text()
    [constraint] = re.findall(r'nameConstraints=critical,([^"]+)"', script)
    assert sorted(constraint.split(",")) == ["permitted;DNS:npmjs.org", "permitted;DNS:pypi.org", "permitted;DNS:pythonhosted.org"]
    assert "pathlen:0" in script
    # Only the certificate leaves the tmpfs, readable by the sandbox's unprivileged shell (review M2).
    assert 'install -m 0644 "$RUN/ca.crt" /ca-out/' in script and "ca.key" not in script.split("/ca-out/ca.crt.tmp")[1]
    for compose in ("docker-compose.yaml", "docker-compose-dev.yaml"):
        egress = yaml.safe_load((REPO / "docker" / compose).read_text())["services"]["sandbox-egress"]
        assert "ports" not in egress, f"{compose}: the egress proxy publishes a port"
        assert egress["tmpfs"] == ["/run/egress"], f"{compose}: the CA key must live on a tmpfs"


# ── bash: Tier 2 only because it runs in that container ─────────────────────


def test_bash_is_tier_2_and_offered_only_with_a_container_sandbox() -> None:
    rules = yaml.safe_load((REPO / "backend/app/policy/default_rules.yaml").read_text())["policy"]["rules"]
    [bash] = [r for r in rules if r["pattern"] == "bash"]
    assert bash["tier"] == 2
    from types import SimpleNamespace

    from omniharness.sandbox.security import is_host_bash_allowed

    local = SimpleNamespace(sandbox=SimpleNamespace(use="omniharness.sandbox.local:LocalSandboxProvider"))
    container = SimpleNamespace(sandbox=SimpleNamespace(use="omniharness.community.aio_sandbox:AioSandboxProvider"))
    assert not is_host_bash_allowed(local), "bash at Tier 2 would run on the host"
    assert is_host_bash_allowed(container)


@pytest.mark.skipif(os.environ.get("OMNI_SANDBOX_DOCKER_E2E") != "1", reason="needs Docker and the network: OMNI_SANDBOX_DOCKER_E2E=1")
def test_docker_end_to_end() -> None:
    result = subprocess.run(["bash", str(REPO / "scripts/sandbox-egress-e2e.sh")], capture_output=True, text=True, timeout=900)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]


# ── adoption: nothing unkeyed or unconfined is ever handed to a thread (review H1)


def _inspect(name: str, *, env: list[str] | None, security_opt: list[str] | None = None) -> dict:
    return {"Name": f"/{name}", "Created": "2026-10-23T10:00:00Z", "NetworkSettings": {"Ports": {}}, "Config": {"Env": env or []}, "HostConfig": {"SecurityOpt": security_opt}}


def _backend_with_containers(monkeypatch, entries: list[dict]):
    import json as _json

    from omniharness.community.aio_sandbox import local_backend as lb

    stopped: list[str] = []

    class _R:
        def __init__(self, out: str = "", rc: int = 0):
            self.stdout, self.returncode, self.stderr = out, rc, ""

    def fake_run(cmd, *a, **k):
        if cmd[1] == "ps":
            if "--filter" in cmd and any(str(c).startswith("name=^") for c in cmd):
                return _R("".join(e["Name"].lstrip("/") + "\n" for e in entries))
            return _R("".join(e["Name"].lstrip("/") + "\n" for e in entries))
        if cmd[1] == "inspect":
            names = set(cmd[2:])
            return _R(_json.dumps([e for e in entries if e["Name"].lstrip("/") in names]))
        if cmd[1] == "stop":
            stopped.append(cmd[-1])
        return _R()

    monkeypatch.setenv("OMNI_HARNESS_SANDBOX_NETWORK", "omni-harness-dev-sandboxes")
    monkeypatch.setattr(lb.subprocess, "run", fake_run)
    monkeypatch.setattr(lb.LocalContainerBackend, "_detect_runtime", lambda self: "docker")
    monkeypatch.setattr(lb.LocalContainerBackend, "_is_container_running", lambda self, name: True)
    backend = lb.LocalContainerBackend(image="img", base_port=8080, container_prefix="omni-harness-sandbox", config_mounts=[], environment={})
    return backend, stopped


def test_containers_without_this_gateways_key_or_with_unconfined_seccomp_are_removed_not_adopted(monkeypatch) -> None:
    monkeypatch.setenv("OMNI_HARNESS_INTERNAL_AUTH_TOKEN", "s")
    from omniharness.community.aio_sandbox.sandbox_auth import sandbox_api_key

    good = "omni-harness-sandbox-good"
    entries = [
        _inspect(good, env=[f"SANDBOX_API_KEY={sandbox_api_key(good)}"]),
        _inspect("omni-harness-sandbox-old", env=["PATH=/bin"]),  # started before #98
        _inspect("omni-harness-sandbox-wrong", env=["SANDBOX_API_KEY=someone-elses"]),
        _inspect("omni-harness-sandbox-unconf", env=[f"SANDBOX_API_KEY={sandbox_api_key('omni-harness-sandbox-unconf')}"], security_opt=["seccomp=unconfined"]),
    ]
    backend, stopped = _backend_with_containers(monkeypatch, entries)
    assert [i.container_name for i in backend.list_running()] == [good]
    assert sorted(stopped) == ["omni-harness-sandbox-old", "omni-harness-sandbox-unconf", "omni-harness-sandbox-wrong"]


def test_discover_removes_an_unkeyed_container_instead_of_adopting_it(monkeypatch) -> None:
    monkeypatch.setenv("OMNI_HARNESS_INTERNAL_AUTH_TOKEN", "s")
    from omniharness.community.aio_sandbox import local_backend as lb

    backend, stopped = _backend_with_containers(monkeypatch, [_inspect("omni-harness-sandbox-old", env=[])])
    monkeypatch.setattr(lb, "wait_for_sandbox_ready", lambda *a, **k: True)  # an unkeyed API answers anything
    assert backend.discover("old") is None
    assert stopped == ["omni-harness-sandbox-old"]


# ── bash is Tier 2 only in the hardened sandbox (review M1) ─────────────────


def _bash_tier(monkeypatch, *, use: str, provisioner_url: str | None = None, egress: bool = True) -> int:
    from types import SimpleNamespace

    from app.policy import runtime_floors
    from app.policy.classify import classify
    from app.policy.config import ConfigLoader

    monkeypatch.setenv("OMNI_HARNESS_INTERNAL_AUTH_TOKEN", "s")
    monkeypatch.setenv("OMNI_HARNESS_SANDBOX_NETWORK", "omni-harness-dev-sandboxes")
    if egress:
        monkeypatch.setenv("OMNI_HARNESS_SANDBOX_EGRESS_PROXY", "http://omni-harness-sandbox-egress:3128")
        monkeypatch.setenv("OMNI_HARNESS_SANDBOX_EGRESS_CA_VOLUME", "v")
    else:
        monkeypatch.delenv("OMNI_HARNESS_SANDBOX_EGRESS_PROXY", raising=False)
    sandbox = SimpleNamespace(use=use, provisioner_url=provisioner_url, model_extra={})
    monkeypatch.setattr("omniharness.config.get_app_config", lambda: SimpleNamespace(sandbox=sandbox))
    assert runtime_floors is not None
    ruleset = ConfigLoader(REPO / "backend/app/policy/default_rules.yaml").load()
    return int(classify("bash", {"command": "ls"}, ruleset).tier)


def test_bash_is_tier_2_only_in_the_hardened_container_sandbox(monkeypatch) -> None:
    aio = "omniharness.community.aio_sandbox:AioSandboxProvider"
    assert _bash_tier(monkeypatch, use=aio) == 2
    assert _bash_tier(monkeypatch, use=aio, provisioner_url="http://provisioner:8002") == 3, "a remote sandbox is not keyed or confined here"
    assert _bash_tier(monkeypatch, use=aio, egress=False) == 3, "no registries proxy configured"
    assert _bash_tier(monkeypatch, use="omniharness.sandbox.local:LocalSandboxProvider") == 3


def test_the_sandbox_image_requires_the_key_on_every_request_but_the_ping() -> None:
    """Review of #103, round 2: the upstream nginx exempted GETs ending in a
    static-file extension, matched against the URI with its query string, so
    `...&z=.json` read another sandbox's files. Our image deletes the
    exemption and its build fails if anything but the ping stays open."""
    dockerfile = (REPO / "docker" / "sandbox" / "Dockerfile").read_text()
    assert "sed -i '/@proxy_without_auth;/{/GET:\\/v1\\/ping\"/!d}' /opt/gem/nginx-server-with-auth.conf" in dockerfile
    assert "test \"$(grep -c '@proxy_without_auth;' /opt/gem/nginx-server-with-auth.conf)\" = 1" in dockerfile
    assert "grep -q 'default @proxy_with_auth;'" in dockerfile
