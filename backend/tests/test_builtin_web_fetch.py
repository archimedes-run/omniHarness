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

    # Fail closed, but say nothing untrue about a public site that is simply down.
    with pytest.raises(FetchRefused, match="could not be fetched through the egress proxy"):
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
        await run_bounded([node, "-e", _NODE_LEAVES_A_FILE, str(record)], b"", 2.0)
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
