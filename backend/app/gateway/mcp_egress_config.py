"""Squid and dnsmasq configs for a built server's egress sidecar (#59).

Pure functions. The sidecar's two listeners:

* ``fwd`` on the internal network's fixed address, port 3128: the built
  server's only way out. CONNECT only, port 443 only, to allowlisted hosts
  only, never to a private address (checked on the RESOLVED addresses), the
  TLS server name the client sends must be allowlisted too, and a proxy login.
* ``inbound`` on the outer network's address (found by the entrypoint), port
  8080: the endpoint's login. It forwards to the server only with the
  per-server bearer token.

dnsmasq is Squid's only resolver, with ``stop-dns-rebind``: an upstream
answer in a private range never reaches Squid.

The renderer refuses to produce a config that lacks any of the lines that
make these promises.
"""

from __future__ import annotations

import hashlib
import ipaddress
import os
import re
from collections.abc import Iterable

FWD_PORT = 3128
INBOUND_PORT = 8080
UPSTREAM_DNS = "127.0.0.11"  # Docker's embedded DNS, from inside the sidecar

#: Checked on the RESOLVED addresses. IPv4-mapped IPv6 (::ffff:0:0/96) and
#: ::/128 are not listed: Squid stores mapped addresses as IPv4 (the IPv4
#: ranges cover them), and `squid -k parse` (6.12) read them as 0.0.0.0/0.
PRIVATE_DESTINATIONS = "0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.0.0.0/24 192.168.0.0/16 198.18.0.0/15 224.0.0.0/3 ::1 64:ff9b::/96 fc00::/7 fe80::/10 ff00::/8"

#: Every one of these must be in a rendered squid.conf, or the renderer refuses.
REQUIRED_SQUID_LINES = (
    "http_access deny fwd !CONNECT",
    "http_access deny fwd !tls_port",
    "http_access deny fwd ip_literal",
    "http_access deny fwd !allowed",
    "http_access deny fwd private_dst",
    "http_access allow fwd mcp_login",
    "http_access allow inbound inbound_token",
    "http_access deny all",
    "ssl_bump peek step1",
    "ssl_bump splice sni_ok",
    "ssl_bump terminate all",
    "on_unsupported_protocol respond all",
    "cache deny all",
    "dns_nameservers 127.0.0.1",
    "cache_peer_access mcp deny all",
)
REQUIRED_DNSMASQ_LINES = ("no-resolv", "no-hosts", "cache-size=0", "listen-address=127.0.0.1")

_HOST = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$")


class EgressConfigError(ValueError):
    pass


def allowlist_hosts(hosts: Iterable[str]) -> list[str]:
    """The allowlist as Squid will compare it: lower-case ASCII names, one
    trailing dot removed. Wildcards, IP addresses, ports and non-ASCII names
    are refused, not rewritten."""
    out: list[str] = []
    for raw in hosts:
        host = str(raw).strip().lower()
        if host.endswith("."):
            host = host[:-1]
        if not host.isascii():
            raise EgressConfigError(f"{raw!r}: only ASCII host names can be allowlisted")
        if any(c in host for c in "*:/@[] "):
            raise EgressConfigError(f"{raw!r}: wildcards, ports and paths can't be allowlisted")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise EgressConfigError(f"{raw!r}: an IP address can't be allowlisted, only a host name")
        if not _HOST.match(host) or host.replace(".", "").isdigit():
            raise EgressConfigError(f"{raw!r} is not a host name")
        if host not in out:
            out.append(host)
    return out


_ITOA64 = "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def _md5_crypt(password: str, salt: str) -> str:
    """The "$1$" MD5-crypt that Squid's basic_ncsa_auth reads (its own
    implementation; the {SHA} form was refused by Squid 6.12, seen as 407)."""
    pw, magic, salt_b = password.encode(), b"$1$", salt.encode()[:8]
    alt = hashlib.md5(pw + salt_b + pw).digest()  # noqa: S324 - the format Squid reads; random password
    ctx = pw + magic + salt_b
    n = len(pw)
    while n > 0:
        ctx += alt[: min(16, n)]
        n -= 16
    i = len(pw)
    while i:
        ctx += b"\x00" if i & 1 else pw[:1]
        i >>= 1
    final = hashlib.md5(ctx).digest()  # noqa: S324
    for r in range(1000):
        c = (pw if r & 1 else final) + (salt_b if r % 3 else b"") + (pw if r % 7 else b"") + (final if r & 1 else pw)
        final = hashlib.md5(c).digest()  # noqa: S324
    out = ""
    for a, b_, c in ((0, 6, 12), (1, 7, 13), (2, 8, 14), (3, 9, 15), (4, 10, 5)):
        v = (final[a] << 16) | (final[b_] << 8) | final[c]
        for _ in range(4):
            out += _ITOA64[v & 0x3F]
            v >>= 6
    v = final[11]
    for _ in range(2):
        out += _ITOA64[v & 0x3F]
        v >>= 6
    return f"$1${salt}${out}"


def proxy_password_line(user: str, password: str) -> bytes:
    """An htpasswd line Squid's basic_ncsa_auth reads ($1$ MD5-crypt)."""
    salt = "".join(_ITOA64[b % 64] for b in os.urandom(8))
    return f"{user}:{_md5_crypt(password, salt)}\n".encode()


def render_squid(*, hosts: list[str], internal_ip: str, upstream_ip: str, token: str, upstream_port: int = 8080) -> str:
    if not re.fullmatch(r"[0-9a-f]{32,128}", token):
        raise EgressConfigError("the endpoint token must be hex")
    ipaddress.ip_address(internal_ip)
    ipaddress.ip_address(upstream_ip)
    allowed = " ".join(hosts) if hosts else "omni-egress.invalid"  # nothing allowed: a name that never resolves
    lines = [
        "# Rendered by the gateway for one built MCP server (Feature 006, #59).",
        f"http_port {internal_ip}:{FWD_PORT} name=fwd ssl-bump tls-cert=/tmp/never-presented.pem generate-host-certificates=off",
        f"http_port @OUTER_IP@:{INBOUND_PORT} name=inbound accel defaultsite=mcp no-vhost",
        "acl fwd myportname fwd",
        "acl inbound myportname inbound",
        "acl CONNECT method CONNECT",
        "acl tls_port port 443",
        f"acl allowed dstdomain -n {allowed}",
        r"acl ip_literal dstdom_regex -n ^[0-9.]+$ ^\[ ^[0-9a-f:]+$ ^0x",
        f"acl private_dst dst {PRIVATE_DESTINATIONS}",
        "auth_param basic program /usr/lib/squid/basic_ncsa_auth /run/omni/passwd",
        "auth_param basic realm omni-egress",
        "acl mcp_login proxy_auth REQUIRED",
        rf"acl inbound_token req_header Authorization ^Bearer\ {token}$",
        "http_access deny fwd !CONNECT",
        "http_access deny fwd !tls_port",
        "http_access deny fwd ip_literal",
        "http_access deny fwd !allowed",
        "http_access deny fwd private_dst",
        "http_access allow fwd mcp_login",
        "http_access allow inbound inbound_token",
        "http_access deny all",
        "acl step1 at_step SslBump1",
        f"acl sni_ok ssl::server_name --client-requested {allowed}",
        "ssl_bump peek step1",
        "ssl_bump splice sni_ok",
        "ssl_bump terminate all",
        "on_unsupported_protocol respond all",
        f"cache_peer {upstream_ip} parent {upstream_port} 0 no-query originserver name=mcp",
        "cache_peer_access mcp allow inbound inbound_token",
        "cache_peer_access mcp deny all",
        "never_direct allow inbound",
        "cache deny all",
        "dns_nameservers 127.0.0.1",
        "via off",
        "forwarded_for delete",
        "httpd_suppress_version_string on",
        "visible_hostname omni-egress",
        "pid_filename /tmp/squid.pid",
        "cache_log stdio:/dev/stderr",
        "access_log stdio:/dev/stdout",
        "coredump_dir /tmp",
        "read_timeout 60 minutes",
        "client_lifetime 1 day",
        "shutdown_lifetime 1 seconds",
        # Squid sizes its tables by the fd limit; Docker's default (1M) made it
        # take ~670 MB and abort. A sidecar for one server needs few.
        "max_filedescriptors 1024",
    ]
    text = "\n".join(lines) + "\n"
    missing = [line for line in REQUIRED_SQUID_LINES if line not in lines]
    if missing:
        raise EgressConfigError(f"refusing a squid.conf without: {missing}")
    return text


def render_dnsmasq(*, upstream: str = UPSTREAM_DNS, stop_dns_rebind: bool = True) -> str:
    """dnsmasq for the sidecar. *stop_dns_rebind* exists for one test that
    proves Squid's own private-destination ACL on its own (T7d); production
    never passes it, and a test asserts the rendered production config has it."""
    lines = [
        "port=53",
        "listen-address=127.0.0.1",
        "bind-interfaces",
        "no-resolv",
        "no-hosts",
        f"server={upstream}",
        "cache-size=0",
        "pid-file=/tmp/dnsmasq.pid",
        "log-facility=-",
    ]
    if stop_dns_rebind:
        lines.append("stop-dns-rebind")
    missing = [line for line in REQUIRED_DNSMASQ_LINES if line not in lines]
    if missing:
        raise EgressConfigError(f"refusing a dnsmasq.conf without: {missing}")
    return "\n".join(lines) + "\n"
