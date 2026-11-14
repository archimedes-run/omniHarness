"""Inlining reads untrusted markup in linear time (Spec 011 FR-028): adversarial
documents of about 2 MB (thousands of unclosed tags, attributes, url( and
calls) finish, accepted or refused, within a tight time budget, and the
input is capped before anything is parsed."""

from __future__ import annotations

import time

import pytest

from app.gateway.apps import bundle

#: Linear: x4 input is about x4 time; quadratic would be about x16.
RATIO = 8.0
ABSOLUTE_S = 20.0
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


def _cpu_seconds(unit: str, size: int) -> float:
    """Best of three, in process CPU time (a loaded runner's wall clock
    is not the code's speed)."""
    doc = ("<html><head></head><body>" + unit * (size // len(unit)))[:size].encode()
    files = {"index.html": doc, "a.js": b"1", "s.css": b"p{}", "x": b"x"}
    best = float("inf")
    for _ in range(3):
        t0 = time.process_time()
        try:
            bundle.inline(files)
        except bundle.BundleError:
            pass
        best = min(best, time.process_time() - t0)
    return best


@pytest.mark.parametrize("name", list(ADVERSARIAL))
def test_adversarial_markup_takes_linear_time(name):
    """Four times the input takes about four times as long (a quadratic
    reading takes sixteen), and the full size stays far under the minutes a
    backtracking reading needs."""
    unit = ADVERSARIAL[name]
    small = _cpu_seconds(unit, N // 4)
    large = _cpu_seconds(unit, N)
    assert large < ABSOLUTE_S, (name, large)
    assert large / max(small, 0.02) < RATIO, (name, small, large)


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
