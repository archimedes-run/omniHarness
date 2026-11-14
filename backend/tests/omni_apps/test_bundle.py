"""Inlining, scanning and the exact CSP (Spec 011 FR-016, FR-018, FR-028). Pure."""

from __future__ import annotations

import base64
import hashlib

import pytest

from app.gateway.apps import bundle


def _sha(text: str) -> str:
    return base64.b64encode(hashlib.sha256(text.encode()).digest()).decode()


def test_inlines_scripts_styles_and_images_and_hashes_each_script() -> None:
    files = {
        "index.html": b'<html><head><link rel="stylesheet" href="s.css"></head><body><img src="i.png"><script src="a.js"></script><script>var b=1;</script></body></html>',
        "a.js": b"var a='</script>';",
        "s.css": b"body{background:url(bg.png)}",
        "i.png": b"\x89PNG",
        "bg.png": b"\x89PNG2",
    }
    html, hashes = bundle.inline(files)
    text = html.decode()
    assert 'src="a.js"' not in text and 's.css"' not in text and 'src="data:image/png;base64,' in text and 'url("data:image/png;base64,' in text
    assert "<script>var a='<\\/script>';</script>" in text
    assert hashes == [_sha(bundle.shim()), _sha("var a='<\\/script>';"), _sha("var b=1;")]


def test_csp_is_exact() -> None:
    assert bundle.csp(["AAA", "BBB"]) == (
        "sandbox allow-scripts; default-src 'none'; script-src 'sha256-AAA' 'sha256-BBB'; style-src 'unsafe-inline'; "
        "img-src data: blob:; font-src data:; media-src 'none'; connect-src 'none'; frame-src 'none'; "
        "child-src 'none'; worker-src 'none'; object-src 'none'; manifest-src 'none'; base-uri 'none'; "
        "form-action 'none'; frame-ancestors 'self'; require-trusted-types-for 'script'; trusted-types 'none'"
    )
    assert "script-src 'none';" in bundle.csp([])


@pytest.mark.parametrize(
    "html,code",
    [
        (b'<script src="https://cdn.example/x.js"></script>', "remote_url"),
        (b'<script src="//cdn.example/x.js"></script>', "remote_url"),
        (b'<link rel="stylesheet" href="https://fonts.example/a.css">', "remote_url"),
        (b'<img src="https://tracker.example/p.gif">', "remote_url"),
        (b'<style>@import url("https://x.example/a.css");</style>', "remote_url"),
        (b"<style>body{background:url(https://x.example/a.png)}</style>", "remote_url"),
        (b'<div style="background:url(https://x.example/a.png)"></div>', "remote_url"),
        (b'<form action="https://x.example/steal"></form>', "remote_url"),
        (b'<a href="javascript:alert(1)">x</a>', "remote_url"),
        (b'<meta http-equiv="refresh" content="0;url=https://x.example">', "remote_url"),
        (b'<base href="https://x.example/">', "remote_url"),
        (b"<script>new RTCPeerConnection()</script>", "forbidden_api"),
        (b"<script>window['RTCDataChannel']</script>", "forbidden_api"),
        (b"<script>new WebSocket('wss://x')</script>", "forbidden_api"),
        (b"<script>eval('1')</script>", "forbidden_api"),
        (b"<script>new Function('return 1')()</script>", "forbidden_api"),
        (b'<script src="missing.js"></script>', "missing_file"),
        (b'<script src="../../etc/passwd"></script>', "missing_file"),
    ],
)
def test_refused_bundles(html, code) -> None:
    with pytest.raises(bundle.BundleError) as err:
        bundle.inline({"index.html": html})
    assert err.value.code == code


def test_template_literals_in_scripts_are_code_not_file_references() -> None:
    html, _ = bundle.inline({"index.html": b'<script>const a = `<a href="${url}">x</a>`; x.evaluate(1)</script>'})
    assert b"${url}" in html


def test_size_cap_after_inlining() -> None:
    big = b"x" * (bundle.BUNDLE_MAX_BYTES + 1)
    with pytest.raises(bundle.BundleError) as err:
        bundle.inline({"index.html": b'<script src="a.js"></script>', "a.js": b"//" + big})
    assert err.value.code == "bundle_too_large"
