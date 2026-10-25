"""URL and address checks for the built-in fetcher (defense in depth).

The fetch egress proxy is the authority: it resolves the name itself and
refuses non-public destinations by the address it would connect to. These
checks run in the gateway first so a bad URL is refused before anything is
sent, and so a misconfigured proxy is not the only line:

* http and https only, ports 80 and 443 only, no credentials in the URL;
* no single-label names (Docker service names such as ``gateway``), no
  ``localhost`` and no internal suffixes;
* no non-canonical IPv4 literals (``2130706433``, ``0x7f.1``, ``127.1``);
* the name is resolved and refused if ANY address it resolves to is not
  public (loopback, private, link-local, CGNAT, multicast, reserved, ...).
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network
IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

#: Destination ranges refused on top of ``not ip.is_global``. Kept explicit so
#: the list reads the same as docker/fetch-egress/squid.conf.
BLOCKED_NETWORKS: tuple[IPNetwork, ...] = tuple(
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.0.2.0/24",
        "192.88.99.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/3",
        "::/128",
        "::1/128",
        "64:ff9b::/96",
        "100::/64",
        "2001::/23",
        "2001:db8::/32",
        "2002::/16",
        "fc00::/7",
        "fe80::/10",
        "fec0::/10",
        "ff00::/8",
    )
)

DEFAULT_PORTS = {"http": 80, "https": 443}
ALLOWED_PORTS = frozenset({80, 443})
MAX_URL_LENGTH = 2048
_INTERNAL_NAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"})
_INTERNAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa", ".localdomain", ".docker", ".intranet", ".corp")


class WebFetchError(Exception):
    """Base for the fetcher's errors; the message is safe to show the model."""


class FetchRefused(WebFetchError):
    """The URL is not allowed (policy). Never retried elsewhere."""


class FetchFailed(WebFetchError):
    """The fetch did not succeed (network, HTTP status, content). May fall back."""


@dataclass(frozen=True)
class Target:
    url: str
    scheme: str
    host: str
    port: int


def parse_networks(values: Iterable[str] | None) -> tuple[IPNetwork, ...]:
    """Extra blocked CIDRs from config; an invalid entry is an error, not ignored."""
    return tuple(ipaddress.ip_network(str(v).strip(), strict=False) for v in values or ())


def is_blocked_ip(ip: IPAddress | str, extra: Iterable[IPNetwork] = ()) -> bool:
    if isinstance(ip, str):
        ip = ipaddress.ip_address(ip.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address):
        mapped = ip.ipv4_mapped or ip.sixtofour
        if mapped is not None and is_blocked_ip(mapped, extra):
            return True
        if ip.teredo is not None:
            return True
    if not ip.is_global or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return True
    return any(ip.version == net.version and ip in net for net in (*BLOCKED_NETWORKS, *extra))


def _ip_literal(host: str) -> IPAddress | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def check_url(url: str, extra: Iterable[IPNetwork] = ()) -> Target:
    """Refuse a URL the fetcher must never request. Does no network I/O."""
    if not isinstance(url, str) or not url.strip():
        raise FetchRefused("the URL is empty")
    url = url.strip()
    if len(url) > MAX_URL_LENGTH:
        raise FetchRefused(f"the URL is longer than {MAX_URL_LENGTH} characters")
    if any(ord(c) < 0x21 or ord(c) == 0x7F for c in url):
        raise FetchRefused("the URL contains whitespace or control characters")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise FetchRefused(f"the URL is malformed: {exc}") from None
    scheme = parts.scheme.lower()
    if scheme not in DEFAULT_PORTS:
        raise FetchRefused(f"only http and https URLs can be fetched, not {scheme or 'a URL without a scheme'}")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise FetchRefused("URLs with credentials cannot be fetched")
    host = (parts.hostname or "").lower()
    if host and not host.isascii():
        # IDNA first: it maps the ideographic/fullwidth dots (U+3002, U+FF0E,
        # U+FF61) to ".", so the trailing-dot strip and every check below see
        # the name as it will be resolved.
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError:
            raise FetchRefused("the host name is not valid") from None
    host = host.rstrip(".").lower()
    if not host:
        raise FetchRefused("the URL has no host")
    port = port if port is not None else DEFAULT_PORTS[scheme]
    if port not in ALLOWED_PORTS:
        raise FetchRefused(f"only ports 80 and 443 can be fetched, not {port}")

    literal = _ip_literal(host)
    if literal is not None:
        if is_blocked_ip(literal, extra):
            raise FetchRefused(f"{host} is not a public address")
    else:
        if host in _INTERNAL_NAMES or host.endswith(_INTERNAL_SUFFIXES):
            raise FetchRefused(f"{host} is an internal name")
        if "." not in host:
            raise FetchRefused(f"{host} is a single-label (internal) name")
        try:
            socket.inet_aton(host)
        except OSError:
            pass
        else:
            raise FetchRefused(f"{host} is a non-canonical IPv4 address")
        if host.endswith(".arpa"):
            raise FetchRefused(f"{host} is an internal name")

    netloc = f"[{host}]" if isinstance(literal, ipaddress.IPv6Address) else host
    if parts.port is not None:
        netloc = f"{netloc}:{port}"
    clean = urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))
    return Target(url=clean, scheme=scheme, host=host, port=port)


async def _getaddrinfo(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


async def resolve_and_check(target: Target, extra: Iterable[IPNetwork] = ()) -> list[str]:
    """Resolve the host and refuse it if any address is not public."""
    extra = tuple(extra)
    literal = _ip_literal(target.host)
    if literal is not None:
        if is_blocked_ip(literal, extra):
            raise FetchRefused(f"{target.host} is not a public address")
        return [str(literal)]
    try:
        addresses = await _getaddrinfo(target.host, target.port)
    except (OSError, UnicodeError) as exc:
        raise FetchFailed(f"could not resolve {target.host}: {exc}") from None
    if not addresses:
        raise FetchFailed(f"could not resolve {target.host}")
    for address in addresses:
        try:
            blocked = is_blocked_ip(address, extra)
        except ValueError:
            blocked = True
        if blocked:
            raise FetchRefused(f"{target.host} resolves to a non-public address")
    return addresses
