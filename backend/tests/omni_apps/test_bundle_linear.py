"""Inlining reads untrusted markup in linear time (Spec 011 FR-028): adversarial
documents of about 2 MB (thousands of unclosed tags, attributes, url( and
calls) finish, accepted or refused, within a tight time budget, and the
input is capped before anything is parsed."""

from __future__ import annotations

import time

import pytest

from app.gateway.apps import bundle

BUDGET_S = 3.0
N = bundle.BUNDLE_MAX_BYTES - 64

ADVERSARIAL = {
    "unclosed script": "<script>",
    "unclosed script src": "<script src=a.js>",
    "unclosed style": "<style>",
    "unclosed style url": "<style>url(",
    "unclosed head": "<head",
    "unclosed link": '<link rel="stylesheet" href="s.css">',
    "unclosed comment": "<!--",
    "inline style url": '<p style="a:url(x)">',
    "srcdoc setAttribute": "setAttribute(",
    "lt iframe text": "< x",
    "end tags": "</script",
}


@pytest.mark.parametrize("name", list(ADVERSARIAL))
def test_adversarial_markup_finishes_within_the_budget(name):
    unit = ADVERSARIAL[name]
    doc = ("<html><head></head><body>" + unit * (N // len(unit)))[:N].encode()
    files = {"index.html": doc, "a.js": b"1", "s.css": b"p{}", "x": b"x"}
    t0 = time.monotonic()
    try:
        bundle.inline(files)
    except bundle.BundleError:
        pass
    assert time.monotonic() - t0 < BUDGET_S, name


def test_the_input_is_capped_before_parsing():
    big = {"index.html": b"<html></html>", "pad.bin": b"x" * bundle.BUNDLE_MAX_BYTES}
    with pytest.raises(bundle.BundleError) as exc:
        bundle.inline(big)
    assert exc.value.code == "bundle_too_large"


def test_a_nul_placeholder_is_refused_not_an_index_error():
    with pytest.raises(bundle.BundleError) as exc:
        bundle.inline({"index.html": b"<html><body>\x0099\x00<script>1</script></body></html>"})
    assert exc.value.code == "invalid_bundle"


def test_an_unclosed_attribute_is_refused():
    with pytest.raises(bundle.BundleError) as exc:
        bundle.inline({"index.html": b'<html><body><img src="x></body></html>'})
    assert exc.value.code == "invalid_bundle"
