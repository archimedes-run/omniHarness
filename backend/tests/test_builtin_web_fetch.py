"""The built-in web_fetch: the app-side guard, the caps, redirects, and the
Jina fallback rules (omniharness.community.builtin_fetch).

The fetch egress proxy is tested in tests/security/test_fetch_egress.py; here
an httpx.MockTransport stands in for the proxy and the network, and the
resolver is replaced, so no test touches the network.
"""

from __future__ import annotations

import asyncio
import gzip
import os
import re
from unittest.mock import MagicMock

import httpx
import pytest

from omniharness.community.builtin_fetch import fetcher as fetcher_module
from omniharness.community.builtin_fetch import guard
from omniharness.community.builtin_fetch import tools as tools_module
from omniharness.community.builtin_fetch.fetcher import MAX_BYTES_CAP, FetchSettings, fetch
from omniharness.community.builtin_fetch.guard import EGRESS_PROXY_DOWN, PDF_UNREADABLE, EgressProxyDown, FetchFailed, FetchRefused, PdfUnreadable, check_url, is_blocked_ip, resolve_and_check

PUBLIC_IP = "93.184.215.14"
HTML = b"<html><head><title>Hello page</title></head><body><article><h1>Hello page</h1><p>" + b"Readable paragraph text for the extractor. " * 20 + b"</p></article></body></html>"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def dns(monkeypatch):
    """A fake resolver: host -> list of answers, consumed one per lookup (the
    last answer repeats), so a test can make a name change between lookups."""
    table: dict[str, list[list[str]]] = {}
    lookups: list[str] = []

    async def fake_getaddrinfo(host: str, port: int) -> list[str]:
        lookups.append(host)
        answers = table.get(host)
        if not answers:
            raise OSError(f"no such host {host}")
        return answers.pop(0) if len(answers) > 1 else answers[0]

    monkeypatch.setattr(guard, "_getaddrinfo", fake_getaddrinfo)
    table["example.com"] = [[PUBLIC_IP]]
    table["public.example"] = [[PUBLIC_IP]]
    fake_getaddrinfo.table = table  # type: ignore[attr-defined]
    fake_getaddrinfo.lookups = lookups  # type: ignore[attr-defined]
    return fake_getaddrinfo


class Recorder:
    """A MockTransport that records every request it is sent."""

    def __init__(self, handler):
        self.requests: list[httpx.Request] = []

        async def wrapped(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            result = handler(request)
            if asyncio.iscoroutine(result):
                result = await result
            return result

        self.transport = httpx.MockTransport(wrapped)

    @property
    def urls(self) -> list[str]:
        return [str(r.url) for r in self.requests]


def page(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, stream=httpx.ByteStream(HTML))


def settings(**kwargs) -> FetchSettings:
    return FetchSettings(proxy="http://fetch-egress.test:3128", **kwargs)


# ── the guard: URLs refused before anything is sent ─────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/",
        "http://LOCALHOST./admin",
        "http://foo.localhost/",
        "http://127.0.0.1/",
        "http://127.0.0.1:80/",
        "https://127.1/",
        "http://2130706433/",
        "http://0x7f000001/",
        "http://0177.0.0.1/",
        "http://0.0.0.0/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[::ffff:169.254.169.254]/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.1/",
        "http://172.16.5.4/",
        "http://192.168.200.10/",
        "http://100.64.0.1/",
        "http://224.0.0.1/",
        "http://[fc00::1]/",
        "http://[fe80::1]/",
        "http://[2002:7f00:1::]/",
        "http://gateway/",
        "http://omni-harness-gateway/",
        "http://omni-harness-gateway:8001/",
        "http://metadata.google.internal/",
        "http://printer.local/",
        "http://host.docker.internal/",
        "ftp://example.com/",
        "file:///etc/passwd",
        "gopher://example.com/",
        "javascript:alert(1)",
        "example.com",
        "http://example.com:8080/",
        "https://example.com:8443/",
        "http://example.com:22/",
        "http://user:pass@example.com/",
        "http://example.com@127.0.0.1/",
        "http://exa mple.com/",
        "http://example.com/\r\nHost: x",
        "",
        "http://" + "a" * 3000 + ".com/",
        # Ideographic / fullwidth dots become a trailing "." after IDNA.
        "http://localhost\u3002/",
        "http://gateway\u3002/",
        "http://omni-harness-gateway\uff0e/",
        "http://metadata.google.internal\u3002/",
        "http://169.254.169.254\uff0e/",
        "http://2130706433\u3002/",
        "http://127\uff610\uff610\uff611/",
    ],
)
def test_check_url_refuses(url: str) -> None:
    with pytest.raises(FetchRefused):
        check_url(url)


@pytest.mark.parametrize(
    ("url", "clean"),
    [
        ("https://example.com", "https://example.com/"),
        ("https://Example.COM./a/b?q=1#frag", "https://example.com/a/b?q=1"),
        ("http://example.com:80/x", "http://example.com:80/x"),
        ("https://example.com:443/", "https://example.com:443/"),
        (f"https://{PUBLIC_IP}/", f"https://{PUBLIC_IP}/"),
        ("https://[2606:4700::1111]/", "https://[2606:4700::1111]/"),
    ],
)
def test_check_url_allows_public_http_and_https(url: str, clean: str) -> None:
    assert check_url(url).url == clean


def test_blocked_networks_cover_the_required_ranges() -> None:
    for ip in ("10.1.2.3", "172.31.0.1", "192.168.1.1", "127.0.0.2", "169.254.169.254", "100.100.100.200", "0.1.2.3", "::1", "fd12::1", "fe80::abcd", "239.1.1.1"):
        assert is_blocked_ip(ip), ip
    assert not is_blocked_ip(PUBLIC_IP)
    extra = guard.parse_networks(["203.0.114.0/24"])
    assert is_blocked_ip("203.0.114.9", extra) and not is_blocked_ip("203.0.114.9")


@pytest.mark.anyio
async def test_resolution_refuses_a_name_that_resolves_to_a_private_address(dns) -> None:
    dns.table["internal.example"] = [["10.0.0.7"]]
    with pytest.raises(FetchRefused, match="non-public"):
        await resolve_and_check(check_url("https://internal.example/"))


@pytest.mark.anyio
async def test_resolution_refuses_when_any_answer_is_private(dns) -> None:
    dns.table["mixed.example"] = [[PUBLIC_IP, "127.0.0.1"]]
    with pytest.raises(FetchRefused):
        await resolve_and_check(check_url("https://mixed.example/"))
    dns.table["mapped.example"] = [["::ffff:192.168.0.1"]]
    with pytest.raises(FetchRefused):
        await resolve_and_check(check_url("https://mapped.example/"))


@pytest.mark.anyio
async def test_resolution_failure_is_a_failure_not_a_refusal(dns) -> None:
    with pytest.raises(FetchFailed):
        await resolve_and_check(check_url("https://nowhere.example/"))


# ── fetch: refused URLs never reach the transport ───────────────────────────


@pytest.mark.anyio
@pytest.mark.parametrize("url", ["http://localhost/", "http://127.0.0.1/", "http://169.254.169.254/latest/meta-data/", "http://gateway/", "http://omni-harness-gateway/"])
async def test_fetch_refuses_internal_targets_without_sending(dns, url: str) -> None:
    rec = Recorder(page)
    with pytest.raises(FetchRefused):
        await fetch(url, settings(), transport=rec.transport)
    assert rec.requests == []


@pytest.mark.anyio
async def test_fetch_refuses_a_name_resolving_to_a_private_address(dns) -> None:
    dns.table["rebind.example"] = [["169.254.169.254"]]
    rec = Recorder(page)
    with pytest.raises(FetchRefused):
        await fetch("http://rebind.example/", settings(), transport=rec.transport)
    assert rec.requests == []


@pytest.mark.anyio
async def test_dns_rebinding_between_hops_is_refused(dns) -> None:
    """Public on the first lookup, private on the next: the redirect hop to the
    same name is resolved and checked again, and refused."""
    dns.table["rebind.example"] = [[PUBLIC_IP], ["127.0.0.1"]]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "/second"})

    rec = Recorder(handler)
    with pytest.raises(FetchRefused):
        await fetch("http://rebind.example/first", settings(), transport=rec.transport)
    assert rec.urls == ["http://rebind.example/first"]
    assert dns.lookups == ["rebind.example", "rebind.example"]


@pytest.mark.anyio
@pytest.mark.parametrize("location", ["http://169.254.169.254/latest/meta-data/", "http://127.0.0.1/", "http://localhost:80/", "http://gateway/", "http://[::1]/", "file:///etc/passwd", "http://example.com:8080/"])
async def test_redirect_from_a_public_url_to_a_private_target_is_refused(dns, location: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": location})

    rec = Recorder(handler)
    with pytest.raises(FetchRefused):
        await fetch("https://public.example/start", settings(), transport=rec.transport)
    assert rec.urls == ["https://public.example/start"], "the private hop must never be requested"


@pytest.mark.anyio
async def test_redirects_are_followed_hop_by_hop_up_to_the_cap(dns) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        n = int(request.url.path.strip("/") or 0)
        if n < 5:
            return httpx.Response(301, headers={"location": f"/{n + 1}"})
        return page(request)

    rec = Recorder(handler)
    result = await fetch("https://example.com/0", settings(), transport=rec.transport)
    assert result.url == "https://example.com/5" and len(rec.requests) == 6


@pytest.mark.anyio
async def test_more_than_five_redirects_fail(dns) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "/again"})

    rec = Recorder(handler)
    with pytest.raises(FetchFailed, match="more than 5 redirects"):
        await fetch("https://example.com/", settings(max_redirects=50), transport=rec.transport)
    assert len(rec.requests) == 6, "the initial request plus five hops, no more"


# ── caps: 2 MB, 15 s ────────────────────────────────────────────────────────


def test_config_can_lower_the_caps_but_never_raise_them() -> None:
    s = settings(timeout=120, max_bytes=50 * 1024 * 1024, max_redirects=99)
    assert (s.timeout, s.max_bytes, s.max_redirects) == (15.0, 2 * 1024 * 1024, 5)
    s = settings(timeout=3, max_bytes=1000, max_redirects=1)
    assert (s.timeout, s.max_bytes, s.max_redirects) == (3.0, 1000, 1)


@pytest.mark.anyio
async def test_body_is_cut_at_2_mb_and_the_stream_is_not_read_further(dns) -> None:
    sent = 0
    chunk = b"a" * 65536

    async def endless():
        nonlocal sent
        for _ in range(200):  # 12.5 MB available
            sent += len(chunk)
            yield chunk

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=endless())

    result = await fetch("https://example.com/big", settings(), transport=Recorder(handler).transport)
    assert len(result.body) == MAX_BYTES_CAP and result.truncated
    assert sent <= MAX_BYTES_CAP + len(chunk), f"read {sent} bytes, past the 2 MB cap"


@pytest.mark.anyio
async def test_a_gzip_bomb_is_cut_at_2_mb_without_expanding_in_memory(dns, monkeypatch) -> None:
    bomb = gzip.compress(b"\0" * (50 * 1024 * 1024))
    outputs: list[int] = []
    real_decompressobj = fetcher_module.zlib.decompressobj

    class Measured:
        def __init__(self, *args):
            self._d = real_decompressobj(*args)

        def decompress(self, data, *args):
            out = self._d.decompress(data, *args)
            outputs.append(len(out))
            return out

        @property
        def unconsumed_tail(self):
            return self._d.unconsumed_tail

    monkeypatch.setattr(fetcher_module.zlib, "decompressobj", Measured)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/plain", "content-encoding": "gzip"}, stream=httpx.ByteStream(bomb))

    result = await fetch("https://example.com/bomb", settings(), transport=Recorder(handler).transport)
    assert len(result.body) == MAX_BYTES_CAP and result.truncated
    assert outputs and max(outputs) <= MAX_BYTES_CAP + 1, f"decompressed {max(outputs)} bytes at once"


@pytest.mark.anyio
async def test_a_small_gzip_body_is_decoded(dns) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html", "content-encoding": "gzip"}, stream=httpx.ByteStream(gzip.compress(HTML)))

    result = await fetch("https://example.com/", settings(), transport=Recorder(handler).transport)
    assert result.body == HTML and not result.truncated


@pytest.mark.anyio
async def test_the_timeout_covers_the_whole_fetch(dns) -> None:
    async def slow(request: httpx.Request) -> httpx.Response:
        # The proxy answered (as a CONNECT reply would); the site is slow.
        await request.extensions["trace"]("http11.receive_response_headers.complete", {})
        await asyncio.sleep(0.15)
        if request.url.path == "/3":
            return page(request)
        return httpx.Response(302, headers={"location": f"/{int(request.url.path.strip('/')) + 1}"})

    loop = asyncio.get_running_loop()
    start = loop.time()
    with pytest.raises(FetchFailed, match="timed out"):
        # Each hop is under the limit; together they are over it.
        await fetch("https://example.com/0", settings(timeout=0.4), transport=Recorder(slow).transport)
    assert loop.time() - start < 1.0


@pytest.mark.anyio
async def test_a_stalled_body_times_out(dns) -> None:
    async def trickle():
        yield b"<html>"
        await asyncio.sleep(10)
        yield b"</html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, content=trickle())

    with pytest.raises(FetchFailed, match="timed out"):
        await fetch("https://example.com/", settings(timeout=0.3), transport=Recorder(handler).transport)


def test_the_default_timeout_is_15_seconds() -> None:
    assert FetchSettings(proxy="http://p:3128").timeout == 15.0 == fetcher_module.TIMEOUT_CAP


# ── the proxy is the only way out ───────────────────────────────────────────


@pytest.mark.anyio
async def test_no_proxy_configured_means_no_fetch(dns, monkeypatch) -> None:
    built = []
    monkeypatch.setattr(fetcher_module.httpx, "AsyncClient", lambda *a, **k: built.append(k))
    with pytest.raises(EgressProxyDown) as info:
        await fetch("https://example.com/", FetchSettings(proxy=None))
    assert str(info.value).startswith(EGRESS_PROXY_DOWN)
    assert not isinstance(info.value, FetchFailed), "never a failure a fallback may retry"
    assert built == []


def _closed_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.mark.anyio
@pytest.mark.parametrize("url", ["https://example.com/", "http://example.com/"])
async def test_an_unreachable_proxy_fails_closed(dns, url) -> None:
    """A real client, a proxy on a closed localhost port: connection refused."""
    with pytest.raises(EgressProxyDown) as info:
        await fetch(url, FetchSettings(proxy=f"http://127.0.0.1:{_closed_port()}", timeout=5))
    assert str(info.value).startswith(EGRESS_PROXY_DOWN)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "error",
    [httpx.ProxyError("502 Bad Gateway"), httpx.ProxyError("407 Proxy Authentication Required"), httpx.ConnectError("refused"), httpx.ConnectTimeout("timed out")],
)
async def test_a_proxy_error_fails_closed(dns, error) -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        raise error

    with pytest.raises(EgressProxyDown) as info:
        await fetch("https://example.com/", settings(), transport=Recorder(broken).transport)
    assert str(info.value).startswith(EGRESS_PROXY_DOWN)


# ── a real local fake proxy: what the proxy does decides proxy-down ─────────


class FakeProxy:
    """An asyncio TCP server standing in for the egress proxy. ``mode``:

    * hang: accept, read the request, never answer
    * close: accept, read the request, close without a byte
    * garbage: answer with bytes that are not HTTP
    * connect_ok_close: answer the CONNECT with 200, then close (the site's TLS fails)
    * connect_ok_junk: answer the CONNECT with 200, then send non-TLS bytes (a bad handshake)
    * connect_ok_hang: answer the CONNECT with 200, then nothing (a slow handshake)
    """

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.requests: list[bytes] = []
        self.server: asyncio.AbstractServer | None = None
        self._writers: list[asyncio.StreamWriter] = []

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._writers.append(writer)
        try:
            head = await reader.readuntil(b"\r\n\r\n")
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError):
            writer.close()
            return
        self.requests.append(head)
        if self.mode == "hang":
            await asyncio.sleep(60)
        elif self.mode == "garbage":
            writer.write(b"\x00\x01 not http at all \xff\r\n\r\n")
            await writer.drain()
        elif self.mode.startswith("connect_ok"):
            writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
            await writer.drain()
            if self.mode == "connect_ok_junk":
                writer.write(b"definitely not a TLS server hello\r\n" * 4)
                await writer.drain()
                await asyncio.sleep(0.2)
            elif self.mode == "connect_ok_hang":
                await asyncio.sleep(60)
        writer.close()

    async def __aenter__(self) -> str:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        port = self.server.sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{port}"

    async def __aexit__(self, *exc) -> None:
        for writer in self._writers:
            writer.close()
        assert self.server is not None
        self.server.close()


@pytest.fixture
def proxy_tool(monkeypatch, dns):
    """The tool with the REAL fetcher (no transport), config {extra}, and the
    Jina client replaced by a recorder."""
    state: dict = {"extra": {}, "jina_calls": []}

    def config():
        cfg = MagicMock()
        tool_cfg = MagicMock()
        tool_cfg.model_extra = dict(state["extra"])
        cfg.get_tool_config.return_value = tool_cfg
        return cfg

    async def fake_crawl(self, url, return_format="html", timeout=10):
        state["jina_calls"].append(url)
        return "<html><body><p>from the jina reader</p></body></html>"

    from omniharness.community.jina_ai.jina_client import JinaClient

    monkeypatch.setattr(tools_module, "get_app_config", config)
    monkeypatch.setattr(JinaClient, "crawl", fake_crawl)
    monkeypatch.delenv(tools_module.PROXY_ENV, raising=False)
    monkeypatch.setenv("JINA_API_KEY", "test-not-a-real-key")
    return state


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["hang", "close", "garbage"])
@pytest.mark.parametrize("url", ["https://example.com/", "http://example.com/"])
async def test_a_proxy_that_never_answers_properly_is_down(proxy_tool, mode, url) -> None:
    from omniharness.community.builtin_fetch.tools import web_fetch_tool

    fake = FakeProxy(mode)
    async with fake as proxy:
        proxy_tool["extra"] = {"proxy": proxy, "timeout": 1, "jina_fallback": True}
        result = await web_fetch_tool.ainvoke({"url": url})
    assert fake.requests, "the request reached the fake proxy"
    assert result.startswith(EGRESS_PROXY_DOWN), (mode, result)
    assert proxy_tool["jina_calls"] == []


@pytest.mark.anyio
async def test_a_blackholed_proxy_surfaces_as_a_connect_timeout(dns) -> None:
    """Connecting gets a share of the budget, so an unreachable proxy is a
    connect timeout, well before the whole budget runs out."""
    assert fetcher_module._connect_timeout(FetchSettings(proxy="http://p:3128")) < fetcher_module.TIMEOUT_CAP / 2
    assert fetcher_module._connect_timeout(FetchSettings(proxy="http://p:3128", timeout=2)) == 1.0

    import httpcore

    real = httpcore.AsyncConnectionPool
    seen: list[float | None] = []

    class Pool(real):  # type: ignore[misc,valid-type]
        """A proxy address that never accepts: the connect step times out."""

        async def handle_async_request(self, request):
            seen.append(request.extensions.get("timeout", {}).get("connect"))
            raise httpcore.ConnectTimeout("blackholed")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(httpcore, "AsyncConnectionPool", Pool)
        mp.setattr(httpcore, "AsyncHTTPProxy", lambda *a, **k: Pool())
        with pytest.raises(EgressProxyDown):
            await fetch("https://example.com/", FetchSettings(proxy="http://192.0.2.1:3128", timeout=4))
    assert seen == [2.0]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "proxy",
    ["ftp://127.0.0.1:3128", "socks9://127.0.0.1:1", "http://127.0.0.1:notaport", "http://[::1", "://", "127.0.0.1:3128"],
)
async def test_an_unusable_proxy_url_is_down_at_call_time(proxy_tool, proxy) -> None:
    from omniharness.community.builtin_fetch.tools import web_fetch_tool

    proxy_tool["extra"] = {"proxy": proxy, "jina_fallback": True}
    result = await web_fetch_tool.ainvoke({"url": "https://example.com/"})
    assert result.startswith(EGRESS_PROXY_DOWN), (proxy, result)
    assert proxy_tool["jina_calls"] == []
    with pytest.raises(EgressProxyDown):
        await fetch("https://example.com/", FetchSettings(proxy=proxy))


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["connect_ok_close", "connect_ok_junk", "connect_ok_hang"])
async def test_a_site_failing_after_the_proxy_answered_is_the_sites_failure(proxy_tool, mode) -> None:
    """After a 200 CONNECT the proxy is up: a TLS failure, a bad handshake or a
    slow one is the site's, an ordinary error (and an enabled fallback may run)."""
    from omniharness.community.builtin_fetch.tools import web_fetch_tool

    fake = FakeProxy(mode)
    async with fake as proxy:
        proxy_tool["extra"] = {"proxy": proxy, "timeout": 2}
        result = await web_fetch_tool.ainvoke({"url": "https://example.com/"})
        assert result.startswith("Error: request failed:"), (mode, result)
        assert not result.startswith(EGRESS_PROXY_DOWN)
        assert proxy_tool["jina_calls"] == []
        proxy_tool["extra"] = {"proxy": proxy, "timeout": 2, "jina_fallback": True}
        result = await web_fetch_tool.ainvoke({"url": "https://example.com/"})
    assert "from the jina reader" in result and proxy_tool["jina_calls"] == ["https://example.com/"]
    assert all(r.startswith(b"CONNECT example.com:443") for r in fake.requests)


@pytest.mark.anyio
async def test_the_client_uses_only_the_configured_proxy_and_never_follows_redirects(dns, monkeypatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://env-proxy.invalid:9")
    monkeypatch.setenv("ALL_PROXY", "http://env-proxy.invalid:9")
    captured: dict = {}
    real = httpx.AsyncClient

    def capture(*args, **kwargs):
        captured.update(kwargs)
        kwargs.pop("proxy")
        return real(*args, transport=httpx.MockTransport(page), **kwargs)

    monkeypatch.setattr(fetcher_module.httpx, "AsyncClient", capture)
    await fetch("https://example.com/", settings())
    assert captured["proxy"] == "http://fetch-egress.test:3128"
    assert captured["trust_env"] is False, "environment proxies must be ignored"
    assert captured["follow_redirects"] is False, "redirects are followed hop by hop, through the guard"


@pytest.mark.anyio
async def test_a_proxy_denial_is_a_refusal(dns) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, headers={"x-squid-error": "ERR_ACCESS_DENIED 0"}, stream=httpx.ByteStream(b"denied"))

    with pytest.raises(FetchRefused, match="egress proxy refused"):
        await fetch("http://example.com/", settings(), transport=Recorder(handler).transport)

    def connect_denied(request: httpx.Request) -> httpx.Response:
        raise httpx.ProxyError("403 Forbidden")

    with pytest.raises(FetchRefused):
        await fetch("https://example.com/", settings(), transport=Recorder(connect_denied).transport)


@pytest.mark.anyio
async def test_a_proxy_dns_failure_is_a_refusal(dns) -> None:
    """The proxy's resolver drops private (rebinding) answers, so its lookup
    failure is policy, not a failure that may be retried elsewhere."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, headers={"x-squid-error": "ERR_DNS_FAIL 0"}, stream=httpx.ByteStream(b"dns"))

    with pytest.raises(FetchRefused):
        await fetch("http://example.com/", settings(), transport=Recorder(handler).transport)

    def connect_unresolved(request: httpx.Request) -> httpx.Response:
        raise httpx.ProxyError("503 Service Unavailable")

    # Fail closed, but say nothing untrue about a public site that is simply down.
    with pytest.raises(FetchRefused, match="could not be fetched through the egress proxy"):
        await fetch("https://example.com/", settings(), transport=Recorder(connect_unresolved).transport)
    with pytest.raises(FetchFailed):
        await fetch("http://example.com/", settings(), transport=Recorder(lambda r: httpx.Response(503)).transport)


@pytest.mark.anyio
async def test_http_errors_and_binary_content_are_failures(dns) -> None:
    with pytest.raises(FetchFailed, match="HTTP 500"):
        await fetch("https://example.com/", settings(), transport=Recorder(lambda r: httpx.Response(500)).transport)
    image = Recorder(lambda r: httpx.Response(200, headers={"content-type": "image/png"}, stream=httpx.ByteStream(b"\x89PNG\r\n")))
    with pytest.raises(FetchFailed, match="unsupported content type"):
        await fetch("https://example.com/a.png", settings(), transport=image.transport)
    # A generic binary body is a PDF only if it starts with %PDF-, whatever the URL says.
    blob = Recorder(lambda r: httpx.Response(200, headers={"content-type": "application/octet-stream"}, stream=httpx.ByteStream(b"PK\x03\x04 not a pdf")))
    with pytest.raises(FetchFailed, match="unsupported content type"):
        await fetch("https://example.com/a.pdf", settings(), transport=blob.transport)


# ── the tool: extraction, Jina only when enabled in config ──────────────────


@pytest.fixture
def tool_env(monkeypatch, dns):
    """The tool with config {extra}, its fetch going to a MockTransport."""
    state: dict = {"extra": {}, "handler": page, "jina_calls": []}

    def config():
        cfg = MagicMock()
        tool_cfg = MagicMock()
        tool_cfg.model_extra = {"proxy": "http://fetch-egress.test:3128", **state["extra"]}
        cfg.get_tool_config.return_value = tool_cfg
        return cfg

    real_fetch = fetcher_module.fetch

    async def fetch_via_mock(url, s, **kwargs):
        return await real_fetch(url, s, transport=Recorder(state["handler"]).transport)

    async def fake_crawl(self, url, return_format="html", timeout=10):
        state["jina_calls"].append(url)
        return "<html><body><p>from the jina reader</p></body></html>"

    from omniharness.community.jina_ai.jina_client import JinaClient

    monkeypatch.setattr(tools_module, "get_app_config", config)
    monkeypatch.setattr(tools_module, "fetch", fetch_via_mock)
    monkeypatch.setattr(JinaClient, "crawl", fake_crawl)
    monkeypatch.delenv("JINA_API_KEY", raising=False)
    return state


@pytest.mark.anyio
async def test_the_tool_returns_readable_markdown(tool_env) -> None:
    from omniharness.community.builtin_fetch.tools import web_fetch_tool

    assert web_fetch_tool.name == "web_fetch"
    result = await web_fetch_tool.ainvoke({"url": "https://example.com/"})
    assert result.startswith("# Hello page") and "Readable paragraph text" in result
    assert len(result) <= 4096
    assert tool_env["jina_calls"] == []


@pytest.mark.anyio
async def test_no_jina_key_means_jina_is_never_called(tool_env) -> None:
    from omniharness.community.builtin_fetch.tools import web_fetch_tool

    tool_env["extra"] = {"jina_fallback": True}
    tool_env["handler"] = lambda r: httpx.Response(503)
    result = await web_fetch_tool.ainvoke({"url": "https://example.com/"})
    assert result.startswith("Error:") and "503" in result
    tool_env["extra"] = {"provider": "jina"}
    result = await web_fetch_tool.ainvoke({"url": "https://example.com/"})
    assert result.startswith("Error:") and "JINA_API_KEY" in result
    assert tool_env["jina_calls"] == []


@pytest.mark.anyio
async def test_jina_is_the_fallback_only_when_enabled_in_config(tool_env, monkeypatch) -> None:
    from omniharness.community.builtin_fetch.tools import web_fetch_tool

    monkeypatch.setenv("JINA_API_KEY", "test-not-a-real-key")
    tool_env["handler"] = lambda r: httpx.Response(503)
    # The key alone (the default config) enables nothing.
    result = await web_fetch_tool.ainvoke({"url": "https://example.com/"})
    assert result.startswith("Error:") and "503" in result and tool_env["jina_calls"] == []
    for not_true in (False, "true", 1, None):
        tool_env["extra"] = {"jina_fallback": not_true}
        result = await web_fetch_tool.ainvoke({"url": "https://example.com/"})
        assert result.startswith("Error:") and tool_env["jina_calls"] == [], not_true
    tool_env["extra"] = {"jina_fallback": True}
    tool_env["handler"] = page
    result = await web_fetch_tool.ainvoke({"url": "https://example.com/"})
    assert tool_env["jina_calls"] == [], "a successful built-in fetch never calls Jina"
    tool_env["handler"] = lambda r: httpx.Response(503)
    result = await web_fetch_tool.ainvoke({"url": "https://example.com/"})
    assert "from the jina reader" in result and tool_env["jina_calls"] == ["https://example.com/"]


@pytest.mark.anyio
async def test_a_down_proxy_never_falls_back_even_with_jina_enabled(tool_env, monkeypatch) -> None:
    from omniharness.community.builtin_fetch.tools import web_fetch_tool

    monkeypatch.setenv("JINA_API_KEY", "test-not-a-real-key")
    tool_env["extra"] = {"jina_fallback": True}

    def proxy_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ProxyError("502 Bad Gateway")

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("[Errno 61] Connection refused")

    for handler in (proxy_error, refused):
        tool_env["handler"] = handler
        result = await web_fetch_tool.ainvoke({"url": "https://example.com/"})
        assert result.startswith(EGRESS_PROXY_DOWN), result
    assert tool_env["jina_calls"] == []


@pytest.fixture
def wire(monkeypatch, dns):
    """The tool with the REAL fetcher and the REAL Jina client, every httpx
    client in the process forced onto one recording transport: what would go
    out on the wire. Config is {extra}; the proxy comes only from it."""
    state: dict = {"extra": {}, "requests": []}

    def config():
        cfg = MagicMock()
        tool_cfg = MagicMock()
        tool_cfg.model_extra = dict(state["extra"])
        cfg.get_tool_config.return_value = tool_cfg
        return cfg

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        if request.url.host == "r.jina.ai":
            return httpx.Response(200, text="<html><body><p>from the jina reader</p></body></html>")
        return httpx.Response(503)

    real = httpx.AsyncClient

    def recording_client(*args, **kwargs):
        kwargs.pop("proxy", None)
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", recording_client)
    monkeypatch.setattr(tools_module, "get_app_config", config)
    monkeypatch.delenv(tools_module.PROXY_ENV, raising=False)
    monkeypatch.setenv("JINA_API_KEY", "test-not-a-real-key")
    return state


@pytest.mark.anyio
async def test_a_jina_key_alone_sends_nothing_to_jina(wire) -> None:
    from omniharness.community.builtin_fetch.tools import web_fetch_tool

    # No proxy configured: the error, and nothing at all on the wire.
    result = await web_fetch_tool.ainvoke({"url": "https://example.com/"})
    assert result.startswith(EGRESS_PROXY_DOWN), result
    assert wire["requests"] == []
    # Proxy configured, the site fails: the site's error, and only the site was asked.
    wire["extra"] = {"proxy": "http://fetch-egress.test:3128"}
    result = await web_fetch_tool.ainvoke({"url": "https://example.com/"})
    assert result.startswith("Error:") and "503" in result
    assert {r.url.host for r in wire["requests"]} == {"example.com"}


@pytest.mark.anyio
async def test_jina_enabled_in_config_goes_to_jina(wire) -> None:
    """The control for the test above: the recorder does see Jina when enabled."""
    from omniharness.community.builtin_fetch.tools import web_fetch_tool

    wire["extra"] = {"proxy": "http://fetch-egress.test:3128", "jina_fallback": True}
    result = await web_fetch_tool.ainvoke({"url": "https://example.com/"})
    assert "from the jina reader" in result
    assert [r.url.host for r in wire["requests"]] == ["example.com", "r.jina.ai"]
    wire["requests"].clear()
    wire["extra"] = {"provider": "jina"}
    result = await web_fetch_tool.ainvoke({"url": "https://example.com/"})
    assert "from the jina reader" in result and [r.url.host for r in wire["requests"]] == ["r.jina.ai"]


@pytest.mark.anyio
async def test_a_refused_url_never_falls_back_to_jina(tool_env, monkeypatch) -> None:
    from omniharness.community.builtin_fetch.tools import web_fetch_tool

    monkeypatch.setenv("JINA_API_KEY", "test-not-a-real-key")
    tool_env["extra"] = {"jina_fallback": True}
    for url in ("http://169.254.169.254/", "http://gateway/", "http://localhost/"):
        result = await web_fetch_tool.ainvoke({"url": url})
        assert result.startswith("Error:"), url
    tool_env["handler"] = lambda r: httpx.Response(302, headers={"location": "http://127.0.0.1/"})
    result = await web_fetch_tool.ainvoke({"url": "https://example.com/"})
    assert result.startswith("Error:")
    tool_env["handler"] = lambda r: httpx.Response(503, headers={"x-squid-error": "ERR_DNS_FAIL 0"})
    result = await web_fetch_tool.ainvoke({"url": "http://example.com/"})
    assert result.startswith("Error:")
    tool_env["extra"] = {"provider": "jina"}
    result = await web_fetch_tool.ainvoke({"url": "http://127.0.0.1/"})
    assert result.startswith("Error:")
    assert tool_env["jina_calls"] == []


@pytest.mark.anyio
async def test_the_selected_jina_provider_is_used_with_a_key(tool_env, monkeypatch) -> None:
    from omniharness.community.builtin_fetch.tools import web_fetch_tool

    monkeypatch.setenv("JINA_API_KEY", "test-not-a-real-key")
    tool_env["extra"] = {"provider": "jina"}
    result = await web_fetch_tool.ainvoke({"url": "https://example.com/"})
    assert "from the jina reader" in result and tool_env["jina_calls"] == ["https://example.com/"]


def test_web_fetch_stays_a_public_result_tool_under_the_same_policy_rule() -> None:
    """The name is what the policy layer keys on; it is unchanged."""
    from pathlib import Path

    import yaml

    from omniharness.tools.tools import PUBLIC_RESULT_TOOL_NAMES

    assert "web_fetch" in PUBLIC_RESULT_TOOL_NAMES
    rules = yaml.safe_load((Path(__file__).resolve().parents[1] / "app/policy/default_rules.yaml").read_text())["policy"]["rules"]
    [rule] = [r for r in rules if r["pattern"] == "web_fetch"]
    assert rule["reads_private"] is False
    assert {"after_private_read": True, "tier": 3} in rule["exceptions"]


def test_the_example_config_uses_the_built_in_fetcher() -> None:
    from pathlib import Path

    import yaml

    cfg = yaml.safe_load((Path(__file__).resolve().parents[2] / "config.example.yaml").read_text())
    [entry] = [t for t in cfg["tools"] if t["name"] == "web_fetch"]
    assert entry["use"] == "omniharness.community.builtin_fetch.tools:web_fetch_tool"


def test_the_jina_key_counts_as_used_only_with_jina_enabled() -> None:
    """A key with Jina off is a dead secret: the unused-secrets line names it."""
    from app.gateway.secret_usage import unused_secret_keys

    builtin = {"name": "web_fetch", "use": "omniharness.community.builtin_fetch.tools:web_fetch_tool"}
    assert unused_secret_keys(["JINA_API_KEY"], {"tools": [builtin]}, {}) == ["JINA_API_KEY"]
    assert unused_secret_keys(["JINA_API_KEY"], {"tools": []}, {}) == ["JINA_API_KEY"]
    assert unused_secret_keys(["JINA_API_KEY"], {"tools": [{**builtin, "jina_fallback": True}]}, {}) == []
    assert unused_secret_keys(["JINA_API_KEY"], {"tools": [{**builtin, "provider": "jina"}]}, {}) == []
    assert unused_secret_keys(["JINA_API_KEY"], {"tools": [{"name": "web_fetch", "use": "omniharness.community.jina_ai.tools:web_fetch_tool"}]}, {}) == []


def test_the_jina_key_is_not_passed_to_the_gateway_by_default() -> None:
    from pathlib import Path

    from app.gateway.secret_usage import GATEWAY_ENV_KEYS, OPT_IN_ENV_KEYS

    assert "JINA_API_KEY" in OPT_IN_ENV_KEYS and "JINA_API_KEY" not in GATEWAY_ENV_KEYS
    repo = Path(__file__).resolve().parents[2]
    for compose in ("docker/docker-compose.yaml", "docker/docker-compose-dev.yaml"):
        assert "      - JINA_API_KEY\n" not in (repo / compose).read_text(), compose


# ── extraction: a killable child process, inside the budget ─────────────────


def _deep_page(depth: int) -> bytes:
    return (b"<html><body>" + b"<div>" * depth + b"x")[: 2 * 1024 * 1024]


def test_pathological_trees_are_detected_before_the_fallback() -> None:
    from omniharness.community.builtin_fetch.extract import tree_too_complex

    assert tree_too_complex(_deep_page(20_000))
    assert tree_too_complex(b"<p>x</p>" * 200_000), "too many elements"
    assert not tree_too_complex(HTML)
    assert not tree_too_complex(b"<div><br><img src=x><p>a</p><br/></div>" * 1000)


def test_a_pathological_tree_never_reaches_the_readability_fallback(monkeypatch) -> None:
    from omniharness.community.builtin_fetch import extract
    from omniharness.community.builtin_fetch.fetcher import FetchResult
    from omniharness.utils import readability

    called = []
    monkeypatch.setattr(readability.ReadabilityExtractor, "extract_article", lambda self, html: called.append(1))
    page = FetchResult(url="https://example.com/", status=200, content_type="text/html", charset=None, body=_deep_page(20_000), truncated=False)
    assert extract.to_markdown(page) == extract.NO_CONTENT
    assert called == []


def _record_workers(monkeypatch) -> list:
    from omniharness.community.builtin_fetch import extract

    procs: list = []
    real = extract.asyncio.create_subprocess_exec

    async def recording(*args, **kwargs):
        proc = await real(*args, **kwargs)
        procs.append(proc)
        return proc

    monkeypatch.setattr(extract.asyncio, "create_subprocess_exec", recording)
    return procs


def _group_gone(pgid: int) -> bool:
    import time

    for _ in range(40):
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        time.sleep(0.05)
    return False


@pytest.mark.anyio
@pytest.mark.parametrize("depth", [20_000, 420_000], ids=["depth-20k", "2mb"])
async def test_a_deeply_nested_page_is_bounded_and_leaves_no_process(monkeypatch, depth: int) -> None:
    from omniharness.community.builtin_fetch.extract import NO_CONTENT, to_markdown_bounded
    from omniharness.community.builtin_fetch.fetcher import FetchResult

    procs = _record_workers(monkeypatch)
    page = FetchResult(url="https://example.com/", status=200, content_type="text/html", charset=None, body=_deep_page(depth), truncated=False)
    loop = asyncio.get_running_loop()
    start = loop.time()
    result = await to_markdown_bounded(page, 15.0)
    assert loop.time() - start < 8.0, "a pathological page must be given up on quickly, not run to the deadline"
    assert result == NO_CONTENT
    assert procs and all(p.returncode is not None for p in procs)
    assert all(_group_gone(p.pid) for p in procs), "a worker (or its node) outlived the call"


_SPINNER = """
import subprocess, sys, time
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
open(sys.argv[1], "w").write(str(child.pid))
time.sleep(60)
"""


def _pid_gone(pid: int) -> bool:
    import time

    for _ in range(60):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


@pytest.mark.anyio
async def test_the_deadline_kills_the_worker_and_everything_it_started(tmp_path) -> None:
    """A stand-in for a spinning node: the worker starts a child and both hang."""
    import sys

    from omniharness.community.builtin_fetch.extract import run_bounded

    pid_file = tmp_path / "child.pid"
    loop = asyncio.get_running_loop()
    start = loop.time()
    with pytest.raises(FetchFailed, match="took longer"):
        await run_bounded([sys.executable, "-c", _SPINNER, str(pid_file)], b"", 1.5)
    assert loop.time() - start < 4.0
    assert _pid_gone(int(pid_file.read_text())), "the worker's child survived the deadline"


@pytest.mark.anyio
async def test_cancelling_the_tool_kills_the_worker_group(tmp_path) -> None:
    import sys

    from omniharness.community.builtin_fetch.extract import run_bounded

    pid_file = tmp_path / "child.pid"
    task = asyncio.create_task(run_bounded([sys.executable, "-c", _SPINNER, str(pid_file)], b"", 30))
    for _ in range(100):
        if pid_file.exists() and pid_file.read_text():
            break
        await asyncio.sleep(0.05)
    loop = asyncio.get_running_loop()
    start = loop.time()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert loop.time() - start < 4.0, "cancelling must kill the group at once, not wait for it"
    assert _pid_gone(int(pid_file.read_text()))


@pytest.mark.anyio
async def test_extraction_gets_only_what_is_left_of_the_15_second_budget(tool_env, monkeypatch) -> None:
    from omniharness.community.builtin_fetch.tools import web_fetch_tool

    budgets: list[float] = []

    async def slow_page(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.5)
        return page(request)

    async def recording(result, timeout):
        budgets.append(timeout)
        return "# ok\n"

    tool_env["handler"] = slow_page
    tool_env["extra"] = {"timeout": 2}
    monkeypatch.setattr(tools_module, "to_markdown_bounded", recording)
    await web_fetch_tool.ainvoke({"url": "https://example.com/"})
    assert budgets and budgets[0] <= 1.55, budgets


# ── extraction workers: how many, what they see, what they leave ────────────

_INTERVAL = """
import sys, time
start = time.monotonic()
time.sleep(0.4)
open(sys.argv[1], "a").write(f"{start} {time.monotonic()}\\n")
"""


@pytest.mark.anyio
async def test_at_most_four_extraction_workers_run_at_once(tmp_path) -> None:
    import sys

    from omniharness.community.builtin_fetch.extract import MAX_WORKERS, run_bounded

    log = tmp_path / "intervals"
    await asyncio.gather(*(run_bounded([sys.executable, "-c", _INTERVAL, str(log)], b"", 15) for _ in range(10)))
    intervals = [tuple(map(float, line.split())) for line in log.read_text().splitlines()]
    assert len(intervals) == 10
    peak = max(sum(1 for a, b in intervals if a <= t < b) for t, _ in intervals)
    assert MAX_WORKERS == 4 and peak <= 4, f"{peak} workers ran at once"


@pytest.mark.anyio
async def test_waiting_for_a_worker_slot_counts_against_the_deadline(monkeypatch) -> None:
    import sys

    from omniharness.community.builtin_fetch.extract import run_bounded

    procs = _record_workers(monkeypatch)
    sleepers = [asyncio.create_task(run_bounded([sys.executable, "-c", "import time; time.sleep(3)"], b"", 10)) for _ in range(4)]
    while len(procs) < 4:
        await asyncio.sleep(0.02)
    loop = asyncio.get_running_loop()
    start = loop.time()
    with pytest.raises(FetchFailed, match="waiting"):
        await run_bounded([sys.executable, "-c", "print('late')"], b"", 0.3)
    assert loop.time() - start < 1.0
    assert len(procs) == 4, "no process may start once the deadline has passed"
    assert _limit_state() == (4, 0), "the timed-out waiter must not stay queued"
    await asyncio.gather(*sleepers)


@pytest.mark.anyio
async def test_the_worker_sees_no_gateway_secrets(monkeypatch) -> None:
    import json
    import sys

    from omniharness.community.builtin_fetch.extract import run_bounded

    for name in ("JINA_API_KEY", "OMNI_HARNESS_INTERNAL_AUTH_TOKEN", "AUTH_JWT_SECRET", "OPENAI_API_KEY", "SOME_SERVICE_TOKEN"):
        monkeypatch.setenv(name, "test-not-a-real-secret")
    out = await run_bounded([sys.executable, "-c", "import json, os; print(json.dumps(dict(os.environ)))"], b"", 10)
    env = json.loads(out)
    assert set(env) - {"__CF_USER_TEXT_ENCODING"} <= {"PATH", "LANG", "LC_ALL", "TMPDIR", "HOME", "NODE_OPTIONS"}, sorted(env)
    assert "test-not-a-real-secret" not in out.decode()
    assert env["HOME"] == env["TMPDIR"] and "omni-extract-" in env["TMPDIR"]


@pytest.mark.anyio
async def test_the_worker_temp_dir_is_removed_after_a_normal_run(tmp_path) -> None:
    import sys

    from omniharness.community.builtin_fetch.extract import run_bounded

    script = "import os, tempfile; d = tempfile.gettempdir(); open(os.path.join(d, 'page.html'), 'w').write('x'); print(d)"
    out = await run_bounded([sys.executable, "-c", script], b"", 10)
    workdir = out.decode().strip()
    assert "omni-extract-" in workdir
    assert not os.path.exists(workdir)


_NODE_LEAVES_A_FILE = """
const fs = require("fs"), os = require("os"), path = require("path");
fs.writeFileSync(path.join(os.tmpdir(), "readabilipy-page.html"), "<html>attacker</html>");
fs.writeFileSync(process.argv[1], os.tmpdir());
setInterval(() => {}, 1000);
"""


@pytest.mark.anyio
async def test_a_killed_node_leaves_no_files_behind(tmp_path) -> None:
    """Readability's node writes the page to a temp file and deletes it only
    when it returns; killed, it cannot, so the whole private TMPDIR goes."""
    import shutil as _shutil

    from omniharness.community.builtin_fetch.extract import run_bounded

    node = _shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    record = tmp_path / "node-tmpdir"
    with pytest.raises(FetchFailed, match="took longer"):
        # A busy CI runner can take seconds just to start node: the deadline
        # must leave it time to write its temp file before it is killed.
        await run_bounded([node, "-e", _NODE_LEAVES_A_FILE, str(record)], b"", 8.0)
    assert record.exists(), "node never started within the deadline (runner too slow?)"
    node_tmp = record.read_text()
    assert "omni-extract-" in node_tmp, "node must write into the private TMPDIR"
    assert not os.path.exists(node_tmp), "the killed node's files were left behind"


def test_the_worker_kills_itself_at_its_own_deadline() -> None:
    """A worker that outlives its gateway (crash, reload) still dies."""
    import signal as _signal
    import subprocess
    import sys

    from omniharness.community.builtin_fetch.extract import WORKER_MODULE

    proc = subprocess.Popen([sys.executable, "-I", "-m", WORKER_MODULE, "1"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, start_new_session=True)
    try:
        # stdin is never closed: the worker blocks reading it until its alarm fires.
        assert proc.wait(timeout=8) == -_signal.SIGKILL
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, _signal.SIGKILL)
            proc.wait()


def test_the_worker_cpu_limit_stops_a_spinning_child() -> None:
    import signal as _signal
    import subprocess
    import sys

    script = "from omniharness.community.builtin_fetch.extract_worker import limit_resources\nlimit_resources(1)\nwhile True: pass\n"
    proc = subprocess.Popen([sys.executable, "-c", script], start_new_session=True)
    try:
        assert proc.wait(timeout=10) in (-_signal.SIGXCPU, -_signal.SIGKILL)
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, _signal.SIGKILL)
            proc.wait()


def test_attribute_floods_and_huge_tags_skip_the_fallback() -> None:
    from omniharness.community.builtin_fetch.extract import tree_too_complex

    assert tree_too_complex(b"<html><body><div " + b"a=1 " * 200_000 + b">x</div></body></html>")
    assert tree_too_complex(b"<p " + b"x" * 40_000 + b">x</p>")
    assert tree_too_complex(b"".join(b"<p a=1 b=2 c=3>x</p>" for _ in range(40_000)))
    # Bare attributes (no "=") count too: 30 tags of 5000, each under the tag-size cap.
    assert tree_too_complex(b"".join(b"<p " + b"a " * 5000 + b">x</p>" for _ in range(30)))
    assert not tree_too_complex(b'<a href="/x" class="y" id="z">link</a>' * 1000)


# ── the process-wide worker limit: no leaked slot, loop or directory ────────


def _limit_state():
    from omniharness.community.builtin_fetch import extract

    limit = extract._limit()
    return limit.active, len(limit.waiters)


@pytest.mark.anyio
async def test_a_failed_temp_dir_never_leaks_a_slot(monkeypatch) -> None:
    import sys

    from omniharness.community.builtin_fetch import extract

    def no_space(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(extract.tempfile, "mkdtemp", no_space)
    for _ in range(6):
        with pytest.raises(FetchFailed, match="could not prepare"):
            await extract.run_bounded([sys.executable, "-c", "pass"], b"", 5)
    assert _limit_state() == (0, 0)


@pytest.mark.anyio
async def test_a_second_cancellation_while_reaping_still_cleans_up(monkeypatch, tmp_path) -> None:
    import sys

    from omniharness.community.builtin_fetch import extract

    procs = _record_workers(monkeypatch)
    dirs: list[str] = []
    real_mkdtemp = extract.tempfile.mkdtemp
    monkeypatch.setattr(extract.tempfile, "mkdtemp", lambda **kw: dirs.append(real_mkdtemp(**kw)) or dirs[-1])
    task = asyncio.create_task(extract.run_bounded([sys.executable, "-c", "import time; time.sleep(30)"], b"", 30))
    while not procs:
        await asyncio.sleep(0.02)
    proc = procs[0]
    real_wait = proc.wait

    async def slow_wait():
        await asyncio.sleep(5)
        return await real_wait()

    proc.wait = slow_wait
    task.cancel()
    await asyncio.sleep(0.1)  # now inside the finally, reaping slowly
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert _limit_state() == (0, 0), "the slot leaked"
    assert dirs and not os.path.exists(dirs[0]), "the temp dir leaked"
    await real_wait()


def test_short_lived_loops_under_contention_leave_nothing_behind() -> None:
    import sys

    from omniharness.community.builtin_fetch.extract import run_bounded

    async def burst():
        # 10 jobs of 0.5 s for 4 slots and a 0.7 s deadline: some time out while queued.
        jobs = [run_bounded([sys.executable, "-c", "import time; time.sleep(0.5)"], b"", 0.7) for _ in range(10)]
        results = await asyncio.gather(*jobs, return_exceptions=True)
        assert all(r == b"" or isinstance(r, FetchFailed) for r in results), results

    for _ in range(5):
        asyncio.run(burst())
    assert _limit_state() == (0, 0)


def test_the_limit_is_four_per_process_across_event_loops(tmp_path) -> None:
    import sys
    import threading

    from omniharness.community.builtin_fetch.extract import run_bounded

    log = tmp_path / "intervals"

    def loop_thread():
        async def main():
            await asyncio.gather(*(run_bounded([sys.executable, "-c", _INTERVAL, str(log)], b"", 15) for _ in range(5)))

        asyncio.run(main())

    threads = [threading.Thread(target=loop_thread) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    intervals = [tuple(map(float, line.split())) for line in log.read_text().splitlines()]
    assert len(intervals) == 10
    peak = max(sum(1 for a, b in intervals if a <= t < b) for t, _ in intervals)
    assert peak <= 4, f"{peak} workers ran at once across two event loops"
    assert _limit_state() == (0, 0)


_EXITS_LEAVING_A_CHILD = """
import subprocess, sys
# Like readabilipy's node: its own stdout/stderr, so the worker's pipe closes when the worker exits.
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
open(sys.argv[1], "w").write(str(child.pid))
sys.exit(int(sys.argv[2]))
"""


@pytest.mark.anyio
async def test_a_child_of_a_worker_that_died_on_its_own_is_killed(tmp_path) -> None:
    """A worker that exits non-zero (SIGXCPU, alarm, crash) leaves no child."""
    import sys

    from omniharness.community.builtin_fetch.extract import run_bounded

    pid_file = tmp_path / "child.pid"
    with pytest.raises(FetchFailed, match="could not be read"):
        await run_bounded([sys.executable, "-c", _EXITS_LEAVING_A_CHILD, str(pid_file), "1"], b"", 10)
    assert _pid_gone(int(pid_file.read_text())), "a node-like child outlived its worker"


@pytest.mark.anyio
async def test_a_clean_exit_does_not_signal_the_reaped_group(tmp_path, monkeypatch) -> None:
    """After a clean exit (readability already waited for node) the reaped
    PID's group is not signalled, which keeps the PID-reuse window shut."""
    import sys

    from omniharness.community.builtin_fetch import extract

    kills: list[int] = []
    monkeypatch.setattr(extract, "_kill_group", lambda proc: kills.append(proc.pid))
    assert await extract.run_bounded([sys.executable, "-c", "print('ok', end='')"], b"", 10) == b"ok"
    assert kills == []
    with pytest.raises(FetchFailed):
        await extract.run_bounded([sys.executable, "-c", "raise SystemExit(3)"], b"", 10)
    assert len(kills) == 1


# ── WorkerLimit hand-offs, driven directly ──────────────────────────────────


@pytest.mark.anyio
async def test_a_slot_handed_to_a_waiter_cancelled_first_is_passed_on() -> None:
    """release() pops the waiter and schedules the hand-off; the waiter is
    cancelled before it runs: the hand-off must give the slot back."""
    from omniharness.community.builtin_fetch.extract import WorkerLimit

    limit = WorkerLimit(4)
    for _ in range(4):
        await limit.acquire(1)
    waiter = asyncio.create_task(limit.acquire(5))
    await asyncio.sleep(0)
    assert (limit.active, len(limit.waiters)) == (4, 1)
    limit.release()  # hand-off scheduled, not yet run
    waiter.cancel()  # its future is cancelled before the hand-off runs
    with pytest.raises(asyncio.CancelledError):
        await waiter
    await asyncio.sleep(0)
    assert (limit.active, len(limit.waiters)) == (3, 0), "the slot was lost"


@pytest.mark.anyio
async def test_a_slot_that_reached_a_waiter_cancelled_before_resuming_is_returned() -> None:
    """The hand-off ran (the future has its result), then the waiter is
    cancelled before it resumes: the waiter must give the slot back."""
    from omniharness.community.builtin_fetch.extract import WorkerLimit

    limit = WorkerLimit(4)
    for _ in range(4):
        await limit.acquire(1)
    waiter = asyncio.create_task(limit.acquire(5))
    await asyncio.sleep(0)
    limit.release()
    await asyncio.sleep(0)  # the hand-off runs and sets the result
    assert not waiter.done()
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert (limit.active, len(limit.waiters)) == (3, 0), "the slot was kept by a cancelled waiter"


def test_a_waiter_whose_loop_closed_in_between_is_skipped() -> None:
    from omniharness.community.builtin_fetch.extract import WorkerLimit

    class ClosingLoop:
        def is_closed(self) -> bool:
            return False

        def call_soon_threadsafe(self, *args):
            raise RuntimeError("Event loop is closed")

    limit = WorkerLimit(4)
    limit.active = 4
    limit.waiters.append((ClosingLoop(), None))
    limit.release()
    assert (limit.active, len(limit.waiters)) == (3, 0)


def test_worker_limit_stress_across_loops_with_timeouts_and_cancels() -> None:
    import random
    import threading

    from omniharness.community.builtin_fetch.extract import WorkerLimit

    limit = WorkerLimit(4)
    lock = threading.Lock()
    state = {"inside": 0, "peak": 0}

    async def job(rng: random.Random) -> None:
        try:
            await limit.acquire(rng.uniform(0.005, 0.08))
        except TimeoutError:
            return
        try:
            with lock:
                state["inside"] += 1
                state["peak"] = max(state["peak"], state["inside"])
            await asyncio.sleep(rng.uniform(0, 0.02))
        finally:
            with lock:
                state["inside"] -= 1
            limit.release()

    async def loop_body(seed: int) -> None:
        rng = random.Random(seed)
        tasks = [asyncio.create_task(job(rng)) for _ in range(25)]
        for task in rng.sample(tasks, 8):
            asyncio.get_running_loop().call_later(rng.uniform(0, 0.05), task.cancel)
        await asyncio.gather(*tasks, return_exceptions=True)

    def thread_body(n: int) -> None:
        for i in range(3):
            asyncio.run(loop_body(n * 100 + i))

    threads = [threading.Thread(target=thread_body, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert state["peak"] <= 4
    assert (limit.active, len(limit.waiters)) == (0, 0)


def test_only_the_result_reaches_the_worker_stdout(monkeypatch) -> None:
    """readabilipy prints node's stderr with print(); that must not end up in the page text."""
    import io
    import sys

    from omniharness.community.builtin_fetch import extract_worker
    from omniharness.community.builtin_fetch.extract import encode_result
    from omniharness.community.builtin_fetch.fetcher import FetchResult

    def noisy(result):
        print("node: some warning")
        return "# real page"

    page = FetchResult(url="https://example.com/", status=200, content_type="text/html", charset=None, body=HTML, truncated=False)
    stdout = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    stderr = io.StringIO()
    monkeypatch.setattr(extract_worker, "to_markdown", noisy)
    monkeypatch.setattr(extract_worker, "arm_deadline", lambda seconds: None)
    monkeypatch.setattr(extract_worker, "limit_resources", lambda seconds: None)
    monkeypatch.setattr(sys, "argv", ["worker", "5"])
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(encode_result(page))))
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)
    assert extract_worker.main() == 0
    assert stdout.buffer.getvalue() == b"# real page"
    assert "node: some warning" in stderr.getvalue()


# ── PDFs: same proxy path and guard, 10 MB, 200 pages, 30 s ─────────────────


def make_pdf(pages: list[str | None], *, title: str | None = None, password: str | None = None) -> bytes:
    """A PDF built with pypdf's writer: one page per entry, with that text in
    Helvetica, or a blank page (no text layer, like a scan) for None."""
    import io

    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    font = writer._add_object(DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")}))
    for text in pages:
        page = writer.add_blank_page(612, 792)
        if text is None:
            continue
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
        content = DecodedStreamObject()
        content.set_data(f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1"))
        page[NameObject("/Contents")] = writer._add_object(content)
    if title:
        writer.add_metadata({"/Title": title})
    if password:
        writer.encrypt(user_password=password, owner_password=password, algorithm="RC4-128")
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def pdf_response(body: bytes, content_type: str = "application/pdf"):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": content_type}, stream=httpx.ByteStream(body))

    return handler


@pytest.mark.anyio
@pytest.mark.parametrize("content_type", ["application/pdf", "application/octet-stream"])
async def test_a_small_pdf_extracts_with_url_and_page_count(tool_env, content_type) -> None:
    from omniharness.community.builtin_fetch.tools import web_fetch_tool

    tool_env["handler"] = pdf_response(make_pdf(["Quarterly results first page", "Second page body text"], title="Test Report"), content_type)
    result = await web_fetch_tool.ainvoke({"url": "https://example.com/report"})
    assert result.startswith("# Test Report\n"), result
    assert "Source: https://example.com/report" in result and "Pages: 2\n" in result
    assert "Quarterly results first page" in result and "Second page body text" in result
    assert len(result) <= 4096
    assert tool_env["jina_calls"] == []


@pytest.mark.anyio
async def test_a_pdf_output_is_cut_to_the_same_bound_as_a_page(tool_env) -> None:
    from omniharness.community.builtin_fetch.tools import web_fetch_tool

    tool_env["handler"] = pdf_response(make_pdf(["word " * 150] * 20))
    result = await web_fetch_tool.ainvoke({"url": "https://example.com/long.pdf"})
    assert result.startswith("# PDF document\n") and "Pages: 20\n" in result
    assert len(result) == 4096


@pytest.mark.anyio
async def test_an_oversized_pdf_is_refused_while_streaming(dns) -> None:
    sent = 0
    chunk = b"%PDF-1.4\n" + b"0" * 65527

    async def endless():
        nonlocal sent
        for _ in range(800):  # 50 MB available, no Content-Length
            sent += len(chunk)
            yield chunk

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=endless())

    with pytest.raises(PdfUnreadable) as info:
        await fetch("https://example.com/big.pdf", settings(), transport=Recorder(handler).transport)
    assert str(info.value) == f"{PDF_UNREADABLE} it is larger than the 10 MB limit"
    assert sent <= fetcher_module.PDF_MAX_BYTES + len(chunk), f"read {sent} bytes, past the 10 MB cap"


@pytest.mark.anyio
async def test_a_pdf_announced_over_10_mb_is_refused_without_reading_it(dns) -> None:
    sent = 0

    async def body():
        nonlocal sent
        sent += 1
        yield b"%PDF-1.4\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/pdf", "content-length": str(11 * 1024 * 1024)}, content=body())

    with pytest.raises(PdfUnreadable, match="larger than the 10 MB limit"):
        await fetch("https://example.com/big.pdf", settings(), transport=Recorder(handler).transport)
    assert sent == 0


@pytest.mark.anyio
async def test_a_pdf_just_under_10_mb_is_read(dns) -> None:
    body = b"%PDF-1.4\n" + b"0" * (fetcher_module.PDF_MAX_BYTES - 9)
    result = await fetch("https://example.com/ok.pdf", settings(max_bytes=1000), transport=Recorder(pdf_response(body)).transport)
    assert result.content_type == "application/pdf" and len(result.body) == fetcher_module.PDF_MAX_BYTES


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("body", "reason"),
    [
        (make_pdf(["Secret contents"], password="hunter2"), "it is encrypted"),
        (make_pdf([None, None, None]), "it has no extractable text (it may be scanned or image-only)"),
        (b"%PDF-1.7\nthis is not really a pdf\n%%EOF", "it is malformed or not a PDF"),
    ],
    ids=["encrypted", "scanned", "malformed"],
)
async def test_unreadable_pdfs_fail_cleanly_and_never_reach_jina(tool_env, monkeypatch, body, reason) -> None:
    from omniharness.community.builtin_fetch.tools import web_fetch_tool

    monkeypatch.setenv("JINA_API_KEY", "test-not-a-real-key")
    tool_env["extra"] = {"jina_fallback": True}
    tool_env["handler"] = pdf_response(body)
    result = await web_fetch_tool.ainvoke({"url": "https://example.com/doc.pdf"})
    assert result == f"{PDF_UNREADABLE} {reason}"
    assert "Secret contents" not in result
    assert tool_env["jina_calls"] == []


@pytest.mark.anyio
async def test_an_oversized_pdf_through_the_tool_never_reaches_jina(tool_env, monkeypatch) -> None:
    from omniharness.community.builtin_fetch.tools import web_fetch_tool

    monkeypatch.setenv("JINA_API_KEY", "test-not-a-real-key")
    tool_env["extra"] = {"jina_fallback": True}
    tool_env["handler"] = lambda r: httpx.Response(200, headers={"content-type": "application/pdf", "content-length": str(20 * 1024 * 1024)}, content=b"")
    result = await web_fetch_tool.ainvoke({"url": "https://example.com/big.pdf"})
    assert result == f"{PDF_UNREADABLE} it is larger than the 10 MB limit"
    assert tool_env["jina_calls"] == []


def test_only_the_first_200_pages_are_read_and_the_header_says_so() -> None:
    from omniharness.community.builtin_fetch.pdf import PDF_MAX_PAGES, extract_pdf_text, format_result

    assert PDF_MAX_PAGES == 200
    # Text only after page 200: never read, so there is no text to return.
    late = extract_pdf_text(make_pdf([None] * 200 + ["Page 201 text"]))
    assert late == {"error": "it has no extractable text (it may be scanned or image-only)"}
    data = extract_pdf_text(make_pdf(["First page text"] + [None] * 204))
    assert data["pages"] == 205 and data["read"] == 200
    out = format_result("https://example.com/long.pdf", data)
    assert "Pages: 205 (text read from the first 200 only)" in out and "First page text" in out


@pytest.mark.anyio
@pytest.mark.parametrize("location", ["http://10.0.0.5/doc.pdf", "http://169.254.169.254/latest/meta-data/", "http://private.example/doc.pdf"])
async def test_a_pdf_url_redirecting_to_a_private_address_is_refused(tool_env, location) -> None:
    from omniharness.community.builtin_fetch.tools import web_fetch_tool

    tool_env["extra"] = {}
    requested: list[str] = []
    pdf = make_pdf(["should never be fetched"])

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.host == "example.com":
            return httpx.Response(302, headers={"location": location})
        return pdf_response(pdf)(request)

    guard_table = guard._getaddrinfo.table  # type: ignore[attr-defined]
    guard_table["private.example"] = [["10.1.2.3"]]
    tool_env["handler"] = handler
    result = await web_fetch_tool.ainvoke({"url": "https://example.com/paper.pdf"})
    assert result.startswith("Error:") and "should never be fetched" not in result, result
    assert requested == ["https://example.com/paper.pdf"], "the private hop must never be requested"


@pytest.mark.anyio
async def test_a_pdf_redirect_to_a_private_address_is_a_refusal(dns) -> None:
    rec = Recorder(lambda r: httpx.Response(302, headers={"location": "http://192.168.1.10/doc.pdf"}))
    with pytest.raises(FetchRefused):
        await fetch("https://example.com/paper.pdf", settings(), transport=rec.transport)
    assert rec.urls == ["https://example.com/paper.pdf"]


@pytest.mark.anyio
@pytest.mark.parametrize("error", [httpx.ConnectError("[Errno 61] Connection refused"), httpx.ProxyError("502 Bad Gateway")])
async def test_proxy_down_while_fetching_a_pdf_says_so(tool_env, monkeypatch, error) -> None:
    from omniharness.community.builtin_fetch.tools import web_fetch_tool

    monkeypatch.setenv("JINA_API_KEY", "test-not-a-real-key")
    tool_env["extra"] = {"jina_fallback": True}

    def down(request: httpx.Request) -> httpx.Response:
        raise error

    tool_env["handler"] = down
    result = await web_fetch_tool.ainvoke({"url": "https://example.com/paper.pdf"})
    assert result.startswith(EGRESS_PROXY_DOWN), result
    assert tool_env["jina_calls"] == []


@pytest.mark.anyio
async def test_a_pdf_gets_the_longer_pdf_budget_and_no_more(dns, monkeypatch) -> None:
    """The fetch budget moves from the page timeout to the PDF one once the
    response says PDF, counted from the start of the fetch."""
    monkeypatch.setattr(fetcher_module, "PDF_TIMEOUT_CAP", 1.0)
    pdf = make_pdf(["slow but fine"])

    def slow(delay: float):
        async def body():
            yield pdf[:10]
            await asyncio.sleep(delay)
            yield pdf[10:]

        return lambda r: httpx.Response(200, headers={"content-type": "application/pdf"}, content=body())

    # Past the 0.3 s page budget, inside the (patched) 1 s PDF budget.
    result = await fetch("https://example.com/a.pdf", settings(timeout=0.3), transport=Recorder(slow(0.5)).transport)
    assert result.body == pdf
    with pytest.raises(FetchFailed, match="timed out after 1 s"):
        await fetch("https://example.com/a.pdf", settings(timeout=0.3), transport=Recorder(slow(1.5)).transport)


@pytest.mark.anyio
async def test_pdf_extraction_runs_in_a_bounded_worker() -> None:
    from omniharness.community.builtin_fetch.fetcher import FetchResult
    from omniharness.community.builtin_fetch.pdf import pdf_to_markdown_bounded

    result = FetchResult(url="https://example.com/a.pdf", status=200, content_type="application/pdf", charset=None, body=make_pdf(["worker text"]), truncated=False)
    assert "worker text" in await pdf_to_markdown_bounded(result, 20)
    # No time left: no worker, and the failure is a PDF failure, not a crash.
    with pytest.raises(PdfUnreadable, match="could not be read in time"):
        await pdf_to_markdown_bounded(result, 0)


def test_pypdf_is_pinned_to_an_exact_version() -> None:
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "packages/harness/pyproject.toml").read_text()
    assert re.search(r'"pypdf==\d+\.\d+\.\d+"', text)


@pytest.mark.anyio
async def test_a_body_the_proxy_finds_too_big_is_a_plain_failure(dns) -> None:
    rec = Recorder(lambda r: httpx.Response(403, headers={"x-squid-error": "ERR_TOO_BIG 0", "content-type": "text/html"}, content=b"too big"))
    with pytest.raises(FetchFailed, match="larger than the egress proxy allows"):
        await fetch("http://example.com/huge.pdf", settings(), transport=rec.transport)
