"""Inlining reads untrusted markup in linear time (Spec 011 FR-028): adversarial
documents of about 2 MB (thousands of unclosed tags, attributes, url( and
calls) finish, accepted or refused, within a tight time budget, and the
input is capped before anything is parsed."""

from __future__ import annotations

import gc
import math
import time

import pytest

from app.gateway.apps import bundle

#: The growth exponent across sizes: time ~ size**k. Linear is k = 1, a
#: quadratic reading k = 2; the fit allows timing noise, not a quadratic.
MAX_EXPONENT = 1.5
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


def _document(unit: str, size: int) -> dict[str, bytes]:
    doc = ("<html><head></head><body>" + unit * (size // len(unit)))[:size].encode()
    return {"index.html": doc, "a.js": b"1", "s.css": b"p{}", "x": b"x"}


def _inline(files: dict[str, bytes]) -> None:
    try:
        bundle.inline(files)
    except bundle.BundleError:
        pass


def _cpu_seconds(unit: str, size: int) -> float:
    """The least of three, in THIS thread's CPU time, with the garbage
    collector paused: what the scanner itself costs.

    Not the process's CPU time: under xdist the worker carries threads left
    by earlier tests (event loops, database workers), and their CPU counted
    too; a burst of it landing in the larger run read as superlinear growth
    (CI: 0.055 s at N/4, 0.97 s at N). Reproduced with three busy threads
    beside the test: 0.048 s and 0.86 s. Not with the collector running: a
    full collection walks every live object in the process (the worker's
    whole heap), and locally the same case reads 0.046, 0.092, 0.184 s
    across N/4, N/2, N with it paused but bends upward with it running."""
    files = _document(unit, size)
    best = float("inf")
    gc.collect()
    gc.disable()
    try:
        for _ in range(3):
            t0 = time.thread_time()
            _inline(files)
            best = min(best, time.thread_time() - t0)
    finally:
        gc.enable()
    return best


def _growth_exponent(sizes: list[int], seconds: list[float]) -> float:
    """The least-squares slope of log(time) against log(size)."""
    xs = [math.log(s) for s in sizes]
    ys = [math.log(max(t, 1e-4)) for t in seconds]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sum((x - mx) ** 2 for x in xs)


@pytest.mark.parametrize("name", list(ADVERSARIAL))
def test_adversarial_markup_takes_linear_time(name):
    """Time grows with the input as size**k with k near 1 across four sizes
    (N/8 to N, N the input cap; a quadratic reading has k = 2), and the full
    size stays far under the minutes a backtracking reading needs."""
    unit = ADVERSARIAL[name]
    sizes = [N // 8, N // 4, N // 2, N]
    seconds = [_cpu_seconds(unit, size) for size in sizes]
    exponent = _growth_exponent(sizes, seconds)
    assert seconds[-1] < ABSOLUTE_S, (name, seconds[-1])
    assert exponent < MAX_EXPONENT, (name, round(exponent, 2), [round(t, 4) for t in seconds])


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
