"""Per-kind validation (Spec 012 FR-014, FR-020 to FR-024, FR-028): content is
data, checked before anything is stored."""

from __future__ import annotations

import json
import random

import pytest

from app.gateway.artifacts_store import caps, kinds
from app.gateway.artifacts_store.kinds import InvalidContent, TooLarge

SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><defs>'
    '<linearGradient id="g"><stop offset="0" stop-color="red"/></linearGradient></defs>'
    '<rect width="10" height="10" fill="url(#g)"/><use href="#g"/><text x="1" y="5">Hi</text></svg>'
)


def test_a_plain_svg_is_accepted_and_stored_as_given():
    canon = kinds.canonical("svg", SVG)
    assert canon.data == SVG.encode() and canon.media_type == "image/svg+xml"


HOSTILE_SVG = {
    "script element": '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
    "foreignObject": '<svg xmlns="http://www.w3.org/2000/svg"><foreignObject><div xmlns="http://www.w3.org/1999/xhtml">x</div></foreignObject></svg>',
    "event attribute": '<svg xmlns="http://www.w3.org/2000/svg"><rect onload="alert(1)"/></svg>',
    "event attribute, upper case": '<svg xmlns="http://www.w3.org/2000/svg" ONLOAD="alert(1)"></svg>',
    "external href": '<svg xmlns="http://www.w3.org/2000/svg"><use href="https://evil.example/x.svg#a"/></svg>',
    "external xlink:href": '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"><image xlink:href="https://evil.example/t.png"/></svg>',
    "javascript href": '<svg xmlns="http://www.w3.org/2000/svg"><use href="javascript:alert(1)"/></svg>',
    "anchor element": '<svg xmlns="http://www.w3.org/2000/svg"><a href="#x"><rect/></a></svg>',
    "set element": '<svg xmlns="http://www.w3.org/2000/svg"><set attributeName="href" to="javascript:alert(1)"/></svg>',
    "external url() in style": '<svg xmlns="http://www.w3.org/2000/svg"><rect style="fill:url(https://evil.example/a)"/></svg>',
    "external url() in fill": '<svg xmlns="http://www.w3.org/2000/svg"><rect fill="url(http://evil.example/#a)"/></svg>',
    "@import in style block": '<svg xmlns="http://www.w3.org/2000/svg"><style>@import "https://evil.example/a.css";</style></svg>',
    "css escape in style": '<svg xmlns="http://www.w3.org/2000/svg"><rect style="fill:u\\72l(https://evil.example)"/></svg>',
    "doctype with entity": '<!DOCTYPE svg [<!ENTITY x "y">]><svg xmlns="http://www.w3.org/2000/svg">&x;</svg>',
    "external entity": '<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg xmlns="http://www.w3.org/2000/svg">&x;</svg>',
    "xml-stylesheet": '<?xml-stylesheet href="https://evil.example/a.css"?><svg xmlns="http://www.w3.org/2000/svg"/>',
    "no svg namespace": "<svg><rect/></svg>",
    "allowed name in a foreign namespace": '<svg xmlns="http://www.w3.org/2000/svg"><h:style xmlns:h="http://www.w3.org/1999/xhtml">p{}</h:style></svg>',
    "html root": '<html xmlns="http://www.w3.org/1999/xhtml"><script>alert(1)</script></html>',
    "unknown attribute": '<svg xmlns="http://www.w3.org/2000/svg"><rect formaction="x"/></svg>',
    "not well formed": '<svg xmlns="http://www.w3.org/2000/svg"><rect></svg>',
}


@pytest.mark.parametrize("name", sorted(HOSTILE_SVG))
def test_hostile_svg_is_refused_with_a_reason(name):
    with pytest.raises(InvalidContent) as caught:
        kinds.canonical("svg", HOSTILE_SVG[name])
    reason = str(caught.value)
    assert reason and "evil.example" not in reason and "alert" not in reason, "the reason must not echo the content"


def test_an_embedded_png_image_is_allowed_in_svg():
    kinds.canonical("svg", '<svg xmlns="http://www.w3.org/2000/svg"><image href="data:image/png;base64,iVBORw0KGgo="/></svg>')
    with pytest.raises(InvalidContent):
        kinds.canonical("svg", '<svg xmlns="http://www.w3.org/2000/svg"><image href="data:image/svg+xml;base64,PHN2Zz4="/></svg>')


CHART = {"type": "bar", "title": "CI", "x": {"field": "day", "type": "time"}, "series": [{"field": "rate", "label": "Rate"}], "data": [{"day": "2026-11-10", "rate": 0.9}, {"day": "2026-11-11T10:00:00", "rate": None}]}


def test_a_chart_spec_is_canonical_and_round_trips():
    canon = kinds.canonical("chart", CHART)
    stored = json.loads(canon.data)
    assert stored["schema"] == "omni-chart/1" and stored["data"] == CHART["data"]
    assert kinds.canonical("chart", json.dumps(CHART)).data == canon.data, "a JSON string and an object give the same canonical bytes"
    assert kinds.canonical("chart", dict(reversed(list(CHART.items())))).data == canon.data, "key order does not change the hash"


BAD_CHARTS = {
    "expression key": {**CHART, "formatter": "function(){}"},
    "html in x": {**CHART, "x": {"field": "day", "type": "time", "render": "<b>"}},
    "unknown type": {**CHART, "type": "html"},
    "nine series": {**CHART, "series": [{"field": f"s{i}", "label": "L"} for i in range(9)]},
    "pie with two series": {**CHART, "type": "pie", "series": [{"field": "a", "label": "A"}, {"field": "b", "label": "B"}]},
    "series value text": {**CHART, "data": [{"day": "2026-11-10", "rate": "high"}]},
    "time not iso": {**CHART, "data": [{"day": "yesterday", "rate": 1}]},
    "nan": {**CHART, "data": [{"day": "2026-11-10", "rate": float("nan")}]},
    "nested value": {**CHART, "data": [{"day": "2026-11-10", "rate": {"$f": 1}}]},
    "missing x": {**CHART, "data": [{"rate": 1}]},
    "too many rows": {**CHART, "data": [{"day": "2026-11-10", "rate": 1}] * 5001},
    "control char title": {**CHART, "title": "a‮b"},
    "series field is x": {**CHART, "series": [{"field": "day", "label": "D"}]},
    "not an object": ["bar"],
}


@pytest.mark.parametrize("name", sorted(BAD_CHARTS))
def test_bad_chart_specs_are_refused(name):
    with pytest.raises(InvalidContent):
        kinds.canonical("chart", BAD_CHARTS[name])


def test_chart_fuzz_never_crashes_and_never_accepts_unknown_keys():
    """Random mutations: each is either refused with InvalidContent or yields a
    spec with only the schema's keys."""
    rng = random.Random(12)
    values = [None, 1, -1.5, "x", True, [], {}, {"a": 1}, "<script>", 10**400 if False else 1e308, "2026-01-01"]
    for _ in range(600):
        spec = json.loads(json.dumps(CHART))
        target = rng.choice(["top", "x", "series", "row"])
        key = rng.choice(["type", "title", "field", "label", "units", "evil", "data", "x", "series", "schema"])
        value = rng.choice(values)
        if target == "top":
            spec[key] = value
        elif target == "x":
            spec["x"][key] = value
        elif target == "series":
            spec["series"][0][key] = value
        else:
            spec["data"][0][key] = value
        try:
            out = json.loads(kinds.canonical("chart", spec).data)
        except InvalidContent:
            continue
        assert set(out) <= {"schema", "type", "title", "x", "series", "data", "units"}
        assert set(out["x"]) <= {"field", "type", "label"}
        assert all(set(s) == {"field", "label"} for s in out["series"])


def test_image_kinds_are_known_by_their_magic_bytes():
    assert kinds.canonical_image(b"\x89PNG\r\n\x1a\n" + b"0" * 10).media_type == "image/png"
    assert kinds.canonical_image(b"\xff\xd8\xff\xe0" + b"0" * 10).media_type == "image/jpeg"
    assert kinds.canonical_image(b"GIF89a" + b"0" * 10).media_type == "image/gif"
    assert kinds.canonical_image(b"RIFF\x00\x00\x00\x00WEBPVP8 ").media_type == "image/webp"
    for not_image in (b"<svg xmlns='http://www.w3.org/2000/svg'/>", b"<html><script>", b"%PDF-1.7", b""):
        with pytest.raises(InvalidContent):
            kinds.canonical_image(not_image)


def test_mermaid_config_cannot_loosen_the_renderer():
    kinds.canonical("mermaid", "graph TD\n  A-->B")
    for src in ('%%{init: {"securityLevel": "loose"}}%%\ngraph TD; A-->B', "---\nconfig:\n  htmlLabels: true\n---\ngraph TD; A-->B"):
        with pytest.raises(InvalidContent):
            kinds.canonical("mermaid", src)


def test_code_is_canonical_language_and_text():
    canon = kinds.canonical("code", "print(1)", language="Python")
    assert json.loads(canon.data) == {"language": "python", "text": "print(1)"} and canon.language == "python"
    with pytest.raises(InvalidContent):
        kinds.canonical("code", "x", language="../../etc")


def test_text_caps_refuse_before_anything_is_stored(monkeypatch):
    monkeypatch.setattr(caps, "TEXT_VERSION_BYTES", 100)
    with pytest.raises(TooLarge) as caught:
        kinds.canonical("markdown", "x" * 101)
    assert caught.value.cap == 100
    kinds.canonical("markdown", "x" * 100)
    monkeypatch.setattr(caps, "BINARY_VERSION_BYTES", 50)
    with pytest.raises(TooLarge):
        kinds.canonical_image(b"\x89PNG\r\n\x1a\n" + b"0" * 60)


def test_event_attributes_are_refused_even_if_the_allowlist_named_one(monkeypatch):
    """The on* check stands on its own, not only on the attribute allowlist."""
    monkeypatch.setattr(kinds, "SVG_ATTRIBUTES", kinds.SVG_ATTRIBUTES | {"onload"})
    with pytest.raises(InvalidContent):
        kinds.canonical("svg", '<svg xmlns="http://www.w3.org/2000/svg" onload="x()"></svg>')


def test_any_doctype_is_refused():
    with pytest.raises(InvalidContent):
        kinds.canonical("svg", '<!DOCTYPE svg><svg xmlns="http://www.w3.org/2000/svg"/>')
