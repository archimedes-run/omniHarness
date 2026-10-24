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
from unittest.mock import MagicMock

import httpx
import pytest

from omniharness.community.builtin_fetch import fetcher as fetcher_module
from omniharness.community.builtin_fetch import guard
from omniharness.community.builtin_fetch import tools as tools_module
from omniharness.community.builtin_fetch.fetcher import MAX_BYTES_CAP, FetchSettings, fetch
from omniharness.community.builtin_fetch.guard import FetchFailed, FetchRefused, check_url, is_blocked_ip, resolve_and_check

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
    with pytest.raises(FetchFailed, match="no fetch egress proxy"):
        await fetch("https://example.com/", FetchSettings(proxy=None))
    assert built == []


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

    with pytest.raises(FetchRefused):
        await fetch("https://example.com/", settings(), transport=Recorder(connect_unresolved).transport)
    with pytest.raises(FetchFailed):
        await fetch("http://example.com/", settings(), transport=Recorder(lambda r: httpx.Response(503)).transport)


@pytest.mark.anyio
async def test_http_errors_and_binary_content_are_failures(dns) -> None:
    with pytest.raises(FetchFailed, match="HTTP 500"):
        await fetch("https://example.com/", settings(), transport=Recorder(lambda r: httpx.Response(500)).transport)
    pdf = Recorder(lambda r: httpx.Response(200, headers={"content-type": "application/pdf"}, stream=httpx.ByteStream(b"%PDF")))
    with pytest.raises(FetchFailed, match="unsupported content type"):
        await fetch("https://example.com/a.pdf", settings(), transport=pdf.transport)


# ── the tool: extraction, Jina only as a keyed fallback ─────────────────────


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

    tool_env["handler"] = lambda r: httpx.Response(503)
    result = await web_fetch_tool.ainvoke({"url": "https://example.com/"})
    assert result.startswith("Error:") and "503" in result
    tool_env["extra"] = {"provider": "jina"}
    result = await web_fetch_tool.ainvoke({"url": "https://example.com/"})
    assert result.startswith("Error:") and "JINA_API_KEY" in result
    assert tool_env["jina_calls"] == []


@pytest.mark.anyio
async def test_jina_is_the_fallback_when_the_key_is_set_and_the_fetch_failed(tool_env, monkeypatch) -> None:
    from omniharness.community.builtin_fetch.tools import web_fetch_tool

    monkeypatch.setenv("JINA_API_KEY", "test-not-a-real-key")
    result = await web_fetch_tool.ainvoke({"url": "https://example.com/"})
    assert tool_env["jina_calls"] == [], "a successful built-in fetch never calls Jina"
    tool_env["handler"] = lambda r: httpx.Response(503)
    result = await web_fetch_tool.ainvoke({"url": "https://example.com/"})
    assert "from the jina reader" in result and tool_env["jina_calls"] == ["https://example.com/"]
    tool_env["jina_calls"].clear()
    tool_env["extra"] = {"jina_fallback": False}
    result = await web_fetch_tool.ainvoke({"url": "https://example.com/"})
    assert result.startswith("Error:") and tool_env["jina_calls"] == []


@pytest.mark.anyio
async def test_a_refused_url_never_falls_back_to_jina(tool_env, monkeypatch) -> None:
    from omniharness.community.builtin_fetch.tools import web_fetch_tool

    monkeypatch.setenv("JINA_API_KEY", "test-not-a-real-key")
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


def test_the_jina_key_counts_as_used_by_the_built_in_fetcher() -> None:
    """Its fallback reads JINA_API_KEY, so the unused-secrets line must not name it."""
    from app.gateway.secret_usage import unused_secret_keys

    config = {"tools": [{"name": "web_fetch", "use": "omniharness.community.builtin_fetch.tools:web_fetch_tool"}]}
    assert unused_secret_keys(["JINA_API_KEY"], config, {}) == []
    assert unused_secret_keys(["JINA_API_KEY"], {"tools": []}, {}) == ["JINA_API_KEY"]


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
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
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
