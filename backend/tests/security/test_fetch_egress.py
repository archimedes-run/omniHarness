"""The fetch egress proxy (docker/fetch-egress): the gateway's web_fetch goes
out through it and nowhere else, public internet only.

The static half runs everywhere: the Squid rules and their order, the resolver,
the compose wiring, and that the proxy refuses exactly the ranges the
gateway's own guard refuses. The Docker half needs Docker, the network and the
local sandbox-egress image: OMNI_FETCH_EGRESS_E2E=1 runs `squid -k parse` on
the config and the end to end (scripts/fetch-egress-e2e.sh) in throwaway
containers; nothing of a running stack is touched.
"""

from __future__ import annotations

import ipaddress
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from omniharness.community.builtin_fetch.guard import BLOCKED_NETWORKS

REPO = Path(__file__).resolve().parents[3]
FETCH = REPO / "docker" / "fetch-egress"
SANDBOX_EGRESS = REPO / "docker" / "sandbox-egress"
E2E = os.environ.get("OMNI_FETCH_EGRESS_E2E") == "1"
COMPOSE = {"docker-compose.yaml": "omni-harness", "docker-compose-dev.yaml": "omni-harness-dev"}


def _lines(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text().splitlines() if line.strip() and not line.lstrip().startswith("#")]


def _acl(lines: list[str], name: str) -> list[str]:
    [line] = [line for line in lines if line.startswith(f"acl {name} ")]
    return line.split()[3:]


def test_squid_allows_only_public_destinations_on_80_and_443() -> None:
    lines = _lines(FETCH / "squid.conf")
    assert [line for line in lines if line.startswith("http_access ")] == [
        "http_access deny !clients",
        "http_access deny manager",
        "http_access deny CONNECT !tls_port",
        "http_access deny !CONNECT !http_port",
        "http_access deny !CONNECT !fetch_methods",
        "http_access deny internal_names",
        "http_access deny single_label",
        "http_access deny to_localhost",
        "http_access deny private_dst",
        "http_access deny attached_nets",
        "http_access allow clients",
        "http_access deny all",
    ], "the order IS the policy: every deny precedes the one allow"
    assert "acl tls_port port 443" in lines and "acl http_port port 80" in lines
    assert "acl fetch_methods method GET HEAD" in lines
    assert 'acl attached_nets dst "/run/fetch/attached.acl"' in lines
    assert 'acl clients src "/run/fetch/clients.acl"' in lines
    # dst (not dst -n): Squid resolves the name and checks the addresses it connects to.
    assert any(line.startswith("acl private_dst dst 0.0.0.0/8 ") for line in lines)
    assert _acl(lines, "single_label") == ["-n", "^[^.:]+$"]
    assert {".localhost", ".internal", ".local"} <= set(_acl(lines, "internal_names"))


def test_squid_refuses_exactly_the_ranges_the_gateway_guard_refuses() -> None:
    squid = {ipaddress.ip_network(n if "/" in n else f"{n}/{128 if ':' in n else 32}") for n in _acl(_lines(FETCH / "squid.conf"), "private_dst")}
    assert squid == set(BLOCKED_NETWORKS)
    required = {"10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "169.254.0.0/16", "100.64.0.0/10", "0.0.0.0/8", "::1/128", "fc00::/7", "fe80::/10", "224.0.0.0/3"}
    assert {ipaddress.ip_network(n) for n in required} <= squid


def test_squid_resolves_only_through_the_rebind_filtering_resolver() -> None:
    lines = _lines(FETCH / "squid.conf")
    assert "dns_nameservers 127.0.0.1" in lines and "hosts_file none" in lines and "dns_defnames off" in lines
    assert "cache deny all" in lines and "via off" in lines and "forwarded_for delete" in lines
    assert "reply_body_max_size 2 MB" in lines
    assert not any("ssl_bump" in line or "ssl-bump" in line for line in lines), "no TLS interception"
    entry = (FETCH / "entrypoint.sh").read_text()
    assert "stop-dns-rebind" in entry and "rebind-localhost-ok" not in entry and "rebind-domain-ok" not in entry
    assert "listen-address=127.0.0.1" in entry and "no-hosts" in entry
    # The attached (compose) networks are refused as destinations and are the only clients.
    assert "ip -o addr show scope global" in entry and '"$RUN/attached.acl"' in entry


def test_compose_runs_the_proxy_on_the_gateway_network_only_and_points_the_gateway_at_it() -> None:
    for compose, network in COMPOSE.items():
        services = yaml.safe_load((REPO / "docker" / compose).read_text())["services"]
        proxy = services["fetch-egress"]
        assert proxy["container_name"] == "omni-harness-fetch-egress"
        assert proxy["networks"] == [network], f"{compose}: never on the sandboxes' network"
        assert "ports" not in proxy, f"{compose}: the fetch proxy publishes a port"
        assert proxy["volumes"] == ["./fetch-egress:/opt/fetch:ro"]
        assert proxy["tmpfs"] == ["/run/fetch"]
        assert proxy["entrypoint"] == ["/bin/sh", "/opt/fetch/entrypoint.sh"]
        # The same image as the sandbox egress, built the same way.
        assert proxy["build"] == services["sandbox-egress"]["build"] and proxy["image"] == services["sandbox-egress"]["image"]
        env = services["gateway"]["environment"]
        assert "OMNI_HARNESS_FETCH_EGRESS_PROXY=http://omni-harness-fetch-egress:3128" in env, compose
        # The sandbox egress keeps its own config and networks.
        assert "entrypoint" not in services["sandbox-egress"] and "./fetch-egress:/opt/fetch:ro" not in (services["sandbox-egress"].get("volumes") or [])


def test_the_sandbox_egress_rules_are_not_loosened() -> None:
    lines = _lines(SANDBOX_EGRESS / "squid.conf")
    assert _acl(lines, "registries") == ["registry.npmjs.org", "pypi.org", "files.pythonhosted.org"]
    assert "http_access deny !registries" in lines and "http_access deny ip_literal" in lines


@pytest.mark.skipif(not E2E, reason="needs Docker and the sandbox-egress image: OMNI_FETCH_EGRESS_E2E=1")
def test_squid_parses_the_config() -> None:
    script = "mkdir -p /run/fetch && echo 172.31.0.0/16 > /run/fetch/attached.acl && cp /run/fetch/attached.acl /run/fetch/clients.acl && squid -k parse -f /opt/fetch/squid.conf 2>&1; echo rc=$?"
    result = subprocess.run(
        ["docker", "run", "--rm", "-v", f"{FETCH}:/opt/fetch:ro", "--entrypoint", "sh", os.environ.get("EGRESS_IMAGE", "omni-harness-sandbox-egress:1"), "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
    )
    out = result.stdout + result.stderr
    # `via off` (as in the sandbox egress) is the one expected warning.
    warnings = [line for line in out.splitlines() if "WARNING" in line and "requires the use of Via" not in line]
    assert "rc=0" in out and "FATAL" not in out and "ERROR" not in out and not warnings, out[-3000:]


@pytest.mark.skipif(not E2E, reason="needs Docker, the network and local images: OMNI_FETCH_EGRESS_E2E=1")
def test_docker_end_to_end() -> None:
    result = subprocess.run(["bash", str(REPO / "scripts/fetch-egress-e2e.sh")], capture_output=True, text=True, timeout=900)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
