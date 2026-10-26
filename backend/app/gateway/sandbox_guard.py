"""Refuse gateway API requests that come from the sandbox network.

The gateway joins the sandbox network so it can reach the sandboxes (their
keyed API) and so they can reach its separate LLM proxy listener (spec 009).
Its main API listener binds every interface, so without this a sandbox could
open connections to it. A request whose TCP peer is inside a sandbox network
subnet is answered 403 before anything else runs; the LLM proxy is a different
listener and is not affected.

The subnets come from Docker (`docker network inspect`), retried in the
background until read and refreshed every few minutes. While they are not
known and a sandbox network is configured, the guard fails CLOSED: only
loopback, the gateway's own addresses (its channels call itself) and peers on
the network of the trusted proxy (nginx, GATEWAY_TRUSTED_PROXIES) are served.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
import struct
import threading

logger = logging.getLogger(__name__)

RETRY_SECONDS = 30.0
REFRESH_SECONDS = 300.0

_lock = threading.Lock()
_state: dict = {"configured": False, "known": False, "subnets": [], "own": set(), "trusted": []}
_thread: threading.Thread | None = None


def set_state(*, configured: bool, subnets: list[ipaddress.IPv4Network], own: set[str] | None = None, trusted: list[ipaddress.IPv4Network] | None = None) -> None:
    """`configured`: a sandbox network exists; `subnets`: its subnets, empty
    while they could not be read (the guard then fails closed)."""
    with _lock:
        _state["configured"] = configured
        _state["subnets"] = list(subnets)
        _state["known"] = bool(subnets)
        if own is not None:
            _state["own"] = set(own)
        if trusted is not None:
            _state["trusted"] = list(trusted)


def refused(host: str | None) -> bool:
    """True when a request from `host` must not reach the gateway's API."""
    with _lock:
        state = dict(_state)
    if not state["configured"] or not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False  # not an IP (an in-process test client)
    if ip.is_loopback or host in state["own"]:
        return False
    if state["known"]:
        return any(ip in net for net in state["subnets"])
    # The sandbox subnets are not known yet: serve only the trusted proxy's network.
    return not any(ip in net for net in state["trusted"])


class SandboxPeerGuard:
    """Pure ASGI: the raw TCP peer, before any forwarded-header handling."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            client = scope.get("client")
            if refused(client[0] if client else None):
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                    return
                body = b'{"detail":"Not reachable from a sandbox."}'
                await send({"type": "http.response.start", "status": 403, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)


def local_networks() -> list[ipaddress.IPv4Network]:
    """Directly connected IPv4 networks, from the kernel routing table."""
    nets = []
    try:
        with open("/proc/net/route", encoding="utf-8") as handle:
            next(handle, None)
            for line in handle:
                parts = line.split()
                if len(parts) < 8 or parts[2] != "00000000" or parts[1] == "00000000":
                    continue
                dest = socket.inet_ntoa(struct.pack("<L", int(parts[1], 16)))
                mask = socket.inet_ntoa(struct.pack("<L", int(parts[7], 16)))
                nets.append(ipaddress.IPv4Network(f"{dest}/{mask}", strict=False))
    except (OSError, ValueError):
        pass
    return nets


def trusted_networks() -> list[ipaddress.IPv4Network]:
    """The local networks that hold a trusted proxy (nginx's network)."""
    proxies = []
    for raw in os.environ.get("GATEWAY_TRUSTED_PROXIES", "").split(","):
        try:
            proxies.append(ipaddress.ip_address(raw.strip()))
        except ValueError:
            continue
    return [net for net in local_networks() if any(p in net for p in proxies)]


def _refresh(name: str) -> bool:
    from app.gateway.code_jobs.network import _local_ipv4_addresses, network_subnets

    subnets = network_subnets(name)
    set_state(configured=True, subnets=subnets, own=set(_local_ipv4_addresses()), trusted=trusted_networks())
    if subnets:
        logger.info("sandbox guard: requests from %s are refused", ", ".join(str(n) for n in subnets))
    return bool(subnets)


def init_from_docker() -> None:
    """Start guarding (closed until the sandbox network is read) and keep the
    subnets fresh in the background."""
    global _thread
    from omniharness.community.aio_sandbox.local_backend import sandbox_network

    name = sandbox_network()
    if not name:
        set_state(configured=False, subnets=[])
        return
    if not _refresh(name):
        logger.warning("sandbox guard: the sandbox network %s could not be read yet; only loopback, this gateway and the trusted proxy's network are served until it is", name)

    def loop() -> None:
        stop = threading.Event()
        while True:
            with _lock:
                known = _state["known"]
            stop.wait(REFRESH_SECONDS if known else RETRY_SECONDS)
            try:
                _refresh(name)
            except Exception:  # noqa: BLE001 - keep trying
                logger.exception("sandbox guard: refresh failed")

    if _thread is None or not _thread.is_alive():
        _thread = threading.Thread(target=loop, name="sandbox-guard-refresh", daemon=True)
        _thread.start()
