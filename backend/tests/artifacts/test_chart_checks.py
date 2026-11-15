"""The artifact chart checks (Spec 012 FR-018): the gateway's reading of the
probe's chart measurements (layout_probe.CHART_MEASURE), and the guards that
keep the shared probe's app and coding-job behaviour unchanged.

The browser side runs in test_code_sandbox_live.py (opt-in, a throwaway
sandbox container) against good, bad and ordinary pages (chart_pages.py)."""

from __future__ import annotations

import ast
import hashlib
import inspect
import json

import pytest
from fake_sandbox import WIDTHS, charts, page, passing

from app.gateway.artifacts_store import checks
from app.gateway.code_jobs import layout as layout_mod
from app.gateway.code_jobs import layout_probe
from omniharness.tools.builtins.artifact_tools import artifact_create_tool

CHECK = {"nonce": "n" * 32}
DOC = "<!doctype html><p>x</p>"


def result(*, light=None, dark=None, widths=WIDTHS):
    """A probe answer whose pages at `widths` carry these chart measurements."""
    out = passing(CHECK, DOC)
    for run, over in zip(out["runs"], (light, dark), strict=True):
        if over is not None:
            run["pages"] = [page(w, charts=charts(**over)) if w in widths else page(w) for w in WIDTHS]
    return out


def parse(answer) -> dict:
    return checks.parse(json.dumps(answer), exit_code=0, nonce=CHECK["nonce"], prod_sha256=hashlib.sha256(DOC.encode()).hexdigest())


def test_charts_with_nothing_wrong_pass_and_the_model_hears_charts_were_checked():
    out = parse(result(light={"seen": 2}, dark={"seen": 2}))
    assert out["outcome"] == "pass" and out["charts"] == 2
    line = checks.model_lines(out, "passed")[0]
    assert "charts readable" in line and "3:1" in line
    # A page without charts is not told about charts.
    assert "chart" not in checks.model_lines(parse(result()), "passed")[0]


def test_overlapping_svg_labels_fail_in_words_the_model_can_act_on():
    out = parse(result(light={"seen": 1, "overlap": [{"where": "svg.chart in div.card", "labels": ["Entertainment", "Groceries"]}]}, widths=(360,)))
    assert out["outcome"] == "fail"
    assert "chart labels overlap at 360 px (light): wrap, rotate, shorten or thin them" in out["summary"]
    assert any(f.startswith("chart labels overlap: svg.chart in div.card at 360 px (light)") and "'Entertainment' and 'Groceries'" in f for f in out["failures"])
    assert checks.model_lines(out, "failed")[0].startswith("System checks FAILED: ") and "chart labels overlap at 360 px" in checks.model_lines(out, "failed")[0]


def test_overlapping_labels_in_an_html_row_fail():
    out = parse(result(dark={"row_overlap": [{"where": "div.bars", "labels": ["Housing", "Groceries"]}]}, widths=(360, 560)))
    assert out["outcome"] == "fail"
    assert "labels in a row overlap at 360 px (dark): let them wrap or shorten them" in out["summary"]
    assert "labels in a row overlap at 560 px (dark): let them wrap or shorten them" in out["summary"]


def test_cut_off_chart_text_fails():
    out = parse(result(light={"clipped": [{"where": "svg", "labels": ["Entertainment"], "px": 30}]}, dark={"clipped": [{"where": "svg", "labels": ["Entertainment"], "px": 30}]}, widths=(360,)))
    assert out["outcome"] == "fail"
    assert "chart text is cut off at 360 px (light, dark): keep every label inside the chart" in out["summary"]


@pytest.mark.parametrize(("kind", "words"), [("bars", "chart bars"), ("points", "chart points"), ("lines", "chart lines"), ("slices", "chart slices or areas")])
def test_faint_marks_fail_per_theme_with_the_worst_ratio(kind, words):
    out = parse(result(dark={"seen": 1, "contrast": [{"where": "svg", "kind": kind, "ratio": 1.14}]}))
    assert out["outcome"] == "fail"
    assert f"{words} have too little contrast with the background in dark (worst 1.14:1, needs 3:1): use a theme colour such as var(--primary)" in out["summary"]
    assert not any("in light" in s for s in out["summary"])


def test_colours_that_cannot_be_measured_are_a_warning_not_a_failure():
    out = parse(result(light={"seen": 1, "unmeasured": 3}))
    assert out["outcome"] == "pass"
    assert "some chart colours (gradients, patterns or images behind them) were not measured" in out["warnings"]


@pytest.mark.parametrize(
    "bad",
    [
        None,  # a probe that did not measure charts
        {"failed": True},  # the chart measurement threw
        "x",
        {**charts(), "seen": -1},
        {**charts(), "overlap": "svg"},
        {**charts(), "contrast": [{"where": "svg", "kind": "bars", "ratio": 4.5}]},  # not a failure: not the probe's
        {**charts(), "contrast": [{"where": "svg", "kind": "logos", "ratio": 1.2}]},
        {**charts(), "contrast": [{"where": "svg", "kind": "bars", "ratio": True}]},
        {k: v for k, v in charts().items() if k != "unmeasured"},
    ],
)
def test_missing_or_malformed_chart_measurements_are_not_checked(bad):
    answer = passing(CHECK, DOC)
    for p in answer["runs"][1]["pages"]:
        if bad is None:
            p.pop("charts")
        else:
            p["charts"] = bad
    out = parse(answer)
    assert out["outcome"] == "error" and checks.state_of(out) == "not_checked"


# -- the shared probe: app and coding-job behaviour unchanged ---------------------------

#: The page measurement and the app measurement as they were before the chart
#: check: the app check (Spec 011) and the coding jobs' layout check (Spec 009)
#: run exactly this code. PAGE_HELPERS is spliced into APP_MEASURE unchanged.
MEASURE_SHA256 = "376d9394e52f613ec3276b3341c9b6529aebebb17aca274236d75ec45f092be2"
APP_MEASURE_SHA256 = "26d1051a35f7b220ff9359dad55168ffe75580807c040e0e71804fb83c144ba3"


def test_the_app_and_layout_measurements_are_byte_for_byte_unchanged():
    assert hashlib.sha256(layout_probe.MEASURE.encode()).hexdigest() == MEASURE_SHA256
    assert hashlib.sha256(layout_probe.APP_MEASURE.encode()).hexdigest() == APP_MEASURE_SHA256
    assert layout_probe.PAGE_HELPERS in layout_probe.APP_MEASURE and layout_probe.PAGE_HELPERS in layout_probe.CHART_MEASURE


def test_only_the_artifact_run_measures_charts():
    assert "CHART_MEASURE" in inspect.getsource(layout_probe.Check.check_artifact_run)
    for other in (layout_probe.Check.check_app_run, layout_probe.Check.check_width, layout_probe.Check.run):
        assert "CHART_MEASURE" not in inspect.getsource(other)
    # The app and coding-job parsers never read the chart fields.
    from app.gateway.code_jobs import app_checks

    assert "charts" not in inspect.getsource(layout_mod.parse) and "row_overlap" not in inspect.getsource(app_checks)


def test_the_probe_stays_python_310_and_ascii():
    source = layout_mod.SCRIPT
    ast.parse(source, feature_version=(3, 10))
    assert source.isascii()


# -- the guidance the model reads ------------------------------------------------------


def test_the_create_tool_states_the_chart_rules_next_to_the_frame_rules():
    text = artifact_create_tool.description
    frame_at = text.index('The frame sets class "dark"')
    rules = text.index("Charts (inline SVG or HTML)")
    assert rules > frame_at
    for words in ("3:1", "light AND dark", "var(--primary)", "never --accent, --muted or --border", "360 px", "11 px", "<tspan>", "every 2nd or 3rd label", "<title>/aria-label or a table"):
        assert words in text, words
