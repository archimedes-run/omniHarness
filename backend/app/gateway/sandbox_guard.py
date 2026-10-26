"""Refuse gateway API requests that come from the sandbox network.

The gateway joins the sandbox network so it can reach the sandboxes (their
keyed API) and so they can reach its separate LLM proxy listener (spec 009).
Its main API listener binds every interface, so without this a sandbox could
open connections to it. A request whose TCP peer is inside a sandbox network
subnet is answered 403 before anything else runs. The subnets are read once
at startup from Docker (app.gateway.code_jobs.network); the LLM proxy is a
different listener and is not affected.
"""

from __future__ import annotations

import ipaddress
import logging

logger = logging.getLogger(__name__)

_subnets: list[ipaddress.IPv4Network] = []


def set_sandbox_subnets(subnets: list[ipaddress.IPv4Network]) -> None:
    global _subnets
    _subnets = list(subnets)


def from_sandbox(host: str | None) -> bool:
    if not host or not _subnets:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(ip in net for net in _subnets)


class SandboxPeerGuard:
    """Pure ASGI: the raw TCP peer, before any forwarded-header handling."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            client = scope.get("client")
            if from_sandbox(client[0] if client else None):
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                    return
                body = b'{"detail":"Not reachable from a sandbox."}'
                await send({"type": "http.response.start", "status": 403, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)


def init_from_docker() -> None:
    """Read the sandbox network's subnets (the gateway runs in Docker with it)."""
    from app.gateway.code_jobs.network import network_subnets
    from omniharness.community.aio_sandbox.local_backend import sandbox_network

    name = sandbox_network()
    if not name:
        return
    subnets = network_subnets(name)
    set_sandbox_subnets(subnets)
    if subnets:
        logger.info("sandbox guard: requests from %s are refused", ", ".join(str(n) for n in subnets))
    else:
        logger.warning("sandbox guard: the sandbox network %s could not be read; its requests are not filtered", name)
