"""Build firewall egress rules for MCP server sandboxes.

Pure function — no I/O, no state, no imports from app or harness business
logic. Tests can import this module without a database or Fernet key.

Policy
------
Default-deny: the sandbox allows NO outbound connections unless the server
record explicitly declares an egress_hosts entry.

Declared allows: each hostname in *egress_hosts* gets an explicit ALLOW rule
for port 443 (HTTPS) and port 80 (HTTP).

The resulting dict is opaque to this module — the sandbox runner (Phase 4)
converts it to iptables / nftables rules or Docker network policies.
"""

from __future__ import annotations

_ALLOWED_PORTS = (80, 443)


def build_egress_rules(egress_hosts: list[str]) -> dict:
    """Return a JSON-serialisable egress rule set for the given host list.

    Structure::

        {
            "default_policy": "deny",
            "allow": [
                {"host": "api.example.com", "port": 443},
                {"host": "api.example.com", "port": 80},
                ...
            ],
        }

    An empty *egress_hosts* list → default-deny with no allow entries.
    Duplicate hostnames in the input list are silently deduplicated.
    """
    seen: set[str] = set()
    allow: list[dict] = []

    for host in egress_hosts:
        host = host.strip().lower()
        if not host or host in seen:
            continue
        seen.add(host)
        for port in _ALLOWED_PORTS:
            allow.append({"host": host, "port": port})

    return {"default_policy": "deny", "allow": allow}
