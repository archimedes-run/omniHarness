"""The inliner's work is bounded, its tokenizer reads comments as browsers
do, and the platform shim is the first script by position, not by parsing."""

from __future__ import annotations

import re
import time
import tracemalloc

import pytest

from app.gateway.apps import bundle

BIG = b"\x89PNG" + b"x" * (1_900_000 - 4)


def _bounded(files: dict[str, bytes], code: str) -> None:
    """Refused with `code` in under 2 s and under 40 MB of peak allocation."""
    tracemalloc.start()
    t0 = time.perf_counter()
    try:
        with pytest.raises(bundle.BundleError) as err:
            bundle.inline(files, platform_shim="/*S*/")
        seconds = time.perf_counter() - t0
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert err.value.code == code, err.value
    assert seconds < 2.0, seconds
    assert peak < 40 * 1024 * 1024, peak


@pytest.mark.parametrize("refs", [50, 200])
def test_one_large_asset_referenced_many_times_is_refused_at_once(refs):
    html = b"<!doctype html><body>" + b'<img src="a.png">' * refs + b"</body>"
    _bounded({"index.html": html, "a.png": BIG}, "bundle_too_large")


def test_css_urls_to_one_large_asset_are_refused_at_once():
    css = b"".join(b".c%d{background:url(a.png)}" % i for i in range(60))
    _bounded({"index.html": b'<!doctype html><link rel="stylesheet" href="s.css">', "s.css": css, "a.png": BIG[:1_500_000]}, "bundle_too_large")


def test_one_script_or_stylesheet_referenced_many_times_is_refused_at_once():
    js = b"var x=1;" * 120_000
    _bounded({"index.html": b'<!doctype html><script src="a.js"></script>' * 40, "a.js": js}, "bundle_too_large")
    css = b"a{color:red}" * 80_000
    _bounded({"index.html": b'<!doctype html><link rel="stylesheet" href="s.css">' * 40, "s.css": css}, "bundle_too_large")


def test_local_references_are_capped():
    html = b"<!doctype html>" + b'<img src="a.png">' * (bundle.MAX_LOCAL_REFS + 1)
    with pytest.raises(bundle.BundleError, match=f"more than {bundle.MAX_LOCAL_REFS} times") as err:
        bundle.inline({"index.html": html, "a.png": b"\x89PNG"}, platform_shim="/*S*/")
    assert err.value.code == "bundle_too_large"
    ok = b"<!doctype html>" + b'<img src="a.png">' * bundle.MAX_LOCAL_REFS
    data, _ = bundle.inline({"index.html": ok, "a.png": b"\x89PNG"}, platform_shim="/*S*/")
    assert data.count(b"data:image/png;base64,iVBORw==") == bundle.MAX_LOCAL_REFS


#: (document, the start tags the tokenizer must report, in order)
COMMENTS = [
    ("<!--><script>a</script>", ["script"]),  # abrupt closing
    ("<!---><script>a</script>", ["script"]),  # abrupt closing
    ("<!----><script>a</script>", ["script"]),
    ("<!-----><script>a</script>", ["script"]),
    ("<!-- x --><script>a</script>", ["script"]),
    ("<!-- x --!><script>a</script>", ["script"]),  # ended by --!>
    ("<!-- x -- y --><script>a</script>", ["script"]),
    ("<!-- <!-- nested --><script>a</script>", ["script"]),
    ("<!-- x -- ><script>a</script>--><b>", ["b"]),
    ("<!--->--><b>", ["b"]),
    ("<!-- unclosed <script>a</script>", []),
    ("<!x><script>a</script>", ["script"]),  # bogus comment
    ("<! --><script>a</script>", ["script"]),
    ("<!DOCTYPE html><!--><script>a</script>", ["script"]),
    ("<?php x ?><script>a</script>", ["script"]),
    ("</ x><script>a</script>", ["script"]),
    ("</><script>a</script>", ["script"]),
    ("</div title='>'><b>", ["b"]),  # an end tag's quoted attribute
    ("<textarea><!--</textarea><script>a</script>", ["textarea", "script"]),
    ("<title><!--</title><script>a</script>", ["title", "script"]),
    ("<noscript><!--</noscript><script>a</script>", ["noscript", "script"]),
    ("<style>/*<!--*/</style><script>a</script>", ["style", "script"]),
    ("<script><!--</script><b>", ["script", "b"]),
    ("<textarea></textareax><script>a</script></textarea><b>", ["textarea", "b"]),
    ("<TEXTAREA><!--</TeXtArEa ><script>a</script>", ["textarea", "script"]),
    ("<plaintext><script>a</script>", ["plaintext"]),
]


@pytest.mark.parametrize(("doc", "tags"), COMMENTS)
def test_the_tokenizer_reads_comments_as_browsers_do(doc, tags):
    assert [t.name for t in bundle._tags(doc)] == tags


TRICKS = [doc for doc, _ in COMMENTS if "<script" in doc and "plaintext" not in doc and not doc.startswith("<!DOCTYPE")] + [
    "<!--><script>a</script><!-- --><html><head></head><body></body></html>",
    "<!--><SCRIPT>a</SCRIPT><head><title>t</title></head>",
    "<!-- x --!><ScRiPt>a</ScRiPt>",
]


@pytest.mark.parametrize("prefix", ["<!doctype html>", "<!DOCTYPE HTML>", "﻿<!doctype html>\n", ""])
@pytest.mark.parametrize("doc", TRICKS)
def test_the_shim_is_the_first_script_by_position(prefix, doc):
    html, _ = bundle.inline({"index.html": (prefix + doc).encode()}, platform_shim="/*SHIM*/")
    text = html.decode()
    first = re.search(r"<script", text, re.IGNORECASE)
    assert first is not None and text[first.start() :].startswith("<script>/*SHIM*/</script>"), text[:200]
    if prefix or not doc.lower().startswith("<!doctype"):
        assert text.startswith(prefix.rstrip("\n") + "<script>/*SHIM*/</script>")


def test_a_malformed_doctype_is_refused():
    with pytest.raises(bundle.BundleError, match="doctype"):
        bundle.inline({"index.html": b"<!doctype html<script>a</script>>"}, platform_shim="/*S*/")
