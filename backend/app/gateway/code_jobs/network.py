"""Where the LLM proxy listens: the gateway's own address on the sandbox network (D3).

Not 0.0.0.0: the proxy must be reachable from the sandboxes and from nothing
else (not nginx, the frontend or the host). The sandbox network is a Docker
network the gateway joined; its subnet is read from Docker, and the local
interface address inside that subnet is the bind address. If any step fails,
there is no address and coding jobs are not offered (fail closed).
`code_jobs.proxy_bind` overrides the discovery (it is still checked to be a
local address).
"""

from __future__ import annotations

import ipaddress
import json
import logging
import socket
import subprocess

logger = logging.getLogger(__name__)


def _local_ipv4_addresses() -> list[str]:
    """Every IPv4 address on this host's interfaces (Linux: from `ip`, else getaddrinfo)."""
    try:
        out = subprocess.run(["ip", "-o", "-4", "addr", "show"], capture_output=True, text=True, timeout=5)
        if out.returncode == 0:
            addrs = []
            for line in out.stdout.splitlines():
                parts = line.split()
                if "inet" in parts:
                    addrs.append(parts[parts.index("inet") + 1].split("/")[0])
            if addrs:
                return addrs
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        # /proc/net/fib_trie fallback: "|-- <ip>" lines followed by "/32 host LOCAL".
        text = open("/proc/net/fib_trie", encoding="utf-8").read().splitlines()
        addrs = []
        for i, line in enumerate(text[:-1]):
            if "/32 host LOCAL" in text[i + 1]:
                addrs.append(line.split()[-1])
        if addrs:
            return sorted(set(addrs))
    except OSError:
        pass
    try:
        return sorted({info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)})
    except OSError:
        return []


def network_subnets(network: str) -> list[ipaddress.IPv4Network]:
    try:
        out = subprocess.run(["docker", "network", "inspect", network, "--format", "{{json .IPAM.Config}}"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("code jobs: cannot inspect the sandbox network %s: %s", network, exc)
        return []
    if out.returncode != 0:
        logger.warning("code jobs: cannot inspect the sandbox network %s: %s", network, (out.stderr or "").strip()[:200])
        return []
    nets = []
    try:
        for entry in json.loads(out.stdout or "[]") or []:
            subnet = (entry or {}).get("Subnet")
            if subnet and ":" not in subnet:
                nets.append(ipaddress.IPv4Network(subnet, strict=False))
    except (ValueError, TypeError, json.JSONDecodeError):
        return []
    return nets


def sandbox_network_address(network: str, override: str | None = None) -> tuple[str | None, list[ipaddress.IPv4Network]]:
    """(this gateway's address on `network`, the network's subnets)."""
    subnets = network_subnets(network)
    local = _local_ipv4_addresses()
    if override:
        if override not in local:
            logger.warning("code jobs: code_jobs.proxy_bind %s is not an address of this host; the LLM proxy is off", override)
            return None, subnets
        return override, subnets
    for addr in local:
        ip = ipaddress.IPv4Address(addr)
        if any(ip in net for net in subnets):
            return addr, subnets
    logger.warning("code jobs: this gateway has no address on the sandbox network %s; the LLM proxy is off", network)
    return None, subnets
