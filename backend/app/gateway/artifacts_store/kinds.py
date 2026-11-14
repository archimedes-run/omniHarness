"""Per-kind content schemas and their server-side checks (Spec 012 FR-003, FR-014, FR-020 to FR-024, FR-028).

Every kind's content is DATA. Nothing here runs any of it. `canonical()`
returns the exact bytes that are hashed and stored, or raises
`InvalidContent` (with a reason in fixed words, never an echo of the content)
or `TooLarge` before anything is written.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.gateway.artifacts_store import caps

#: Kinds the chat tools make in Slice 1.
TOOL_KINDS = ("markdown", "code", "svg", "mermaid", "chart", "image")
#: Kinds a stored artifact may have in Slice 1 (`file`: the importer only).
STORED_KINDS = (*TOOL_KINDS, "file")
TEXT_KINDS = frozenset({"markdown", "code", "svg", "mermaid", "chart"})
#: Kinds the owner edits in place in Slice 1 (FR-010; document and spreadsheet arrive in S4).
OWNER_EDIT_KINDS = frozenset({"markdown", "code", "mermaid"})
#: Kinds `artifact_update` may change with exact {old, new} edits.
EDIT_KINDS = frozenset({"markdown", "code", "mermaid", "svg"})
#: Kinds whose latest text is kept for search.
SEARCH_KINDS = frozenset({"markdown", "code", "mermaid"})

MEDIA_TYPES = {"markdown": "text/markdown", "mermaid": "text/vnd.mermaid", "code": "text/plain", "svg": "image/svg+xml", "chart": "application/json", "file": "application/octet-stream"}
IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")
_LANGUAGE = re.compile(r"^[a-z0-9+#._-]{1,32}$")


class InvalidContent(ValueError):
    """Content that fails its kind's schema. The reason is fixed wording."""


class TooLarge(ValueError):
    def __init__(self, size: int, cap: int) -> None:
        super().__init__(f"content is {size} bytes; the cap is {cap}")
        self.size = size
        self.cap = cap


@dataclass(frozen=True)
class Canonical:
    data: bytes
    media_type: str
    language: str | None = None
    #: The text kept for search (SEARCH_KINDS), else None.
    search_text: str | None = None


def cap_for(kind: str) -> int:
    return caps.TEXT_VERSION_BYTES if kind in TEXT_KINDS else caps.BINARY_VERSION_BYTES


def _check_size(kind: str, size: int) -> None:
    cap = cap_for(kind)
    if size > cap:
        raise TooLarge(size, cap)


def _text(value: Any, what: str = "content") -> str:
    if not isinstance(value, str):
        raise InvalidContent(f"{what} must be text.")
    if "\x00" in value:
        raise InvalidContent(f"{what} contains a NUL character.")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise InvalidContent(f"{what} is not valid UTF-8.") from None
    return value


def dumps(value: Any) -> bytes:
    """Canonical JSON: sorted keys, compact, UTF-8."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def language_of(value: Any) -> str:
    if value is None or value == "":
        return "text"
    if not isinstance(value, str) or not _LANGUAGE.match(value.strip().lower()):
        raise InvalidContent("language must be a short name like python or typescript.")
    return value.strip().lower()


def canonical(kind: str, content: Any, *, language: str | None = None) -> Canonical:
    """The stored bytes for one version of a text kind (images: `canonical_image`)."""
    if kind == "markdown":
        text = _text(content)
        data = text.encode("utf-8")
        _check_size(kind, len(data))
        return Canonical(data, MEDIA_TYPES[kind], None, text)
    if kind == "mermaid":
        text = _text(content)
        data = text.encode("utf-8")
        _check_size(kind, len(data))
        check_mermaid(text)
        return Canonical(data, MEDIA_TYPES[kind], None, text)
    if kind == "code":
        if isinstance(content, dict):
            if set(content) - {"language", "text"}:
                raise InvalidContent("code content is {language, text} only.")
            language = content.get("language", language)
            content = content.get("text")
        text = _text(content)
        lang = language_of(language)
        data = dumps({"language": lang, "text": text})
        _check_size(kind, len(data))
        return Canonical(data, MEDIA_TYPES[kind], lang, text)
    if kind == "svg":
        text = _text(content)
        data = text.encode("utf-8")
        _check_size(kind, len(data))
        check_svg(text)
        return Canonical(data, MEDIA_TYPES[kind])
    if kind == "chart":
        if isinstance(content, str):
            raw = content.encode("utf-8", "replace")
            _check_size(kind, len(raw))
            try:
                content = json.loads(content)
            except ValueError:
                raise InvalidContent("chart content must be an omni-chart/1 object (JSON).") from None
        spec = check_chart(content)
        data = dumps(spec)
        _check_size(kind, len(data))
        return Canonical(data, MEDIA_TYPES[kind])
    raise InvalidContent("this kind cannot be made this way.")


def text_of(kind: str, data: bytes) -> str:
    """The editable text of a stored text-kind version."""
    if kind == "code":
        return json.loads(data)["text"]
    return data.decode("utf-8")


def content_for_api(kind: str, data: bytes) -> Any:
    if kind in ("markdown", "mermaid"):
        return data.decode("utf-8")
    if kind in ("code", "chart"):
        return json.loads(data)
    return None


# -- images (FR-028: magic bytes) ------------------------------------------------------


def sniff_image(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def canonical_image(data: bytes) -> Canonical:
    _check_size("image", len(data))
    media_type = sniff_image(data)
    if media_type is None:
        raise InvalidContent("an image must be PNG, JPEG, WebP or GIF (checked by its first bytes).")
    return Canonical(bytes(data), media_type)


# -- mermaid ---------------------------------------------------------------------------------

_DIRECTIVE = re.compile(r"%%\{(.*?)\}%%", re.S)
_FRONTMATTER = re.compile(r"^\s*---\s*\n(.*?)\n\s*---", re.S)
_MERMAID_FORBIDDEN = ("securitylevel", "htmllabels", "secure", "dompurify")


def check_mermaid(text: str) -> None:
    blocks = [m.group(1) for m in _DIRECTIVE.finditer(text)]
    front = _FRONTMATTER.match(text)
    if front:
        blocks.append(front.group(1))
    for block in blocks:
        lowered = block.lower()
        if any(word in lowered for word in _MERMAID_FORBIDDEN):
            raise InvalidContent("a mermaid config block may not set securityLevel, htmlLabels, secure or dompurifyConfig.")


# -- svg (FR-014: allowlist, parsed with defusedxml) ------------------------------------

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
XML_NS = "http://www.w3.org/XML/1998/namespace"

SVG_ELEMENTS = frozenset(
    """svg g defs title desc symbol use path rect circle ellipse line polyline polygon text tspan textPath
    linearGradient radialGradient stop pattern clipPath mask marker filter image style
    feBlend feColorMatrix feComponentTransfer feFuncR feFuncG feFuncB feFuncA feComposite feConvolveMatrix
    feDiffuseLighting feDisplacementMap feDistantLight feDropShadow feFlood feGaussianBlur feMerge feMergeNode
    feMorphology feOffset fePointLight feSpecularLighting feSpotLight feTile feTurbulence""".split()
)
SVG_ATTRIBUTES = frozenset(
    """id class style transform x y x1 y1 x2 y2 cx cy r rx ry fx fy fr width height d points viewBox
    preserveAspectRatio version baseProfile fill fill-opacity fill-rule stroke stroke-width stroke-opacity
    stroke-linecap stroke-linejoin stroke-dasharray stroke-dashoffset stroke-miterlimit opacity color display
    visibility overflow clip-path clip-rule mask filter marker-start marker-mid marker-end font-family font-size
    font-weight font-style font-variant font-stretch text-anchor dominant-baseline alignment-baseline baseline-shift
    letter-spacing word-spacing text-decoration writing-mode dx dy rotate textLength lengthAdjust startOffset
    offset stop-color stop-opacity gradientUnits gradientTransform spreadMethod patternUnits patternContentUnits
    patternTransform clipPathUnits maskUnits maskContentUnits markerWidth markerHeight markerUnits refX refY orient
    filterUnits primitiveUnits in in2 result stdDeviation mode type values operator k1 k2 k3 k4 flood-color
    flood-opacity lighting-color radius scale xChannelSelector yChannelSelector baseFrequency numOctaves seed
    stitchTiles tableValues slope intercept amplitude exponent kernelMatrix order divisor bias targetX targetY
    edgeMode preserveAlpha surfaceScale diffuseConstant specularConstant specularExponent azimuth elevation z
    pointsAtX pointsAtY pointsAtZ limitingConeAngle kernelUnitLength href lang role media vector-effect
    shape-rendering text-rendering image-rendering color-interpolation color-interpolation-filters paint-order
    mix-blend-mode isolation pathLength""".split()
)
_ATTR_PREFIXES = ("aria-", "data-")
_URL = re.compile(r"url\s*\(\s*(['\"]?)(.*?)\1\s*\)", re.I | re.S)
_DATA_IMAGE = re.compile(r"^data:image/(png|jpeg|gif|webp);base64,[A-Za-z0-9+/=\s]*$", re.I)
_BAD_VALUE = re.compile(r"javascript:|vbscript:|expression\(|-moz-binding|behavior:|@import", re.I)


def _squash(value: str) -> str:
    """Whitespace and control characters removed, so `java\\tscript:` is caught."""
    return re.sub(r"[\x00-\x20]+", "", value)


def _check_value(value: str, where: str) -> None:
    # A CSS escape (`u\\72l(`) could spell what the checks below look for.
    if "\\" in value or _BAD_VALUE.search(_squash(value)):
        raise InvalidContent(f"{where} holds a script or an import.")
    for match in _URL.finditer(value):
        if not match.group(2).strip().startswith("#"):
            raise InvalidContent(f"{where} refers to an outside resource with url(); only url(#id) is allowed.")


def _safe_name(name: str) -> str:
    return name if re.fullmatch(r"[A-Za-z][A-Za-z0-9:_-]{0,39}", name) else "(unnamed)"


def check_svg(text: str) -> None:
    from xml.etree.ElementTree import ParseError

    from defusedxml import DefusedXmlException
    from defusedxml.ElementTree import fromstring

    if re.search(r"<\?xml-stylesheet", text, re.I):
        raise InvalidContent("an xml-stylesheet instruction is not allowed.")
    try:
        root = fromstring(text, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except DefusedXmlException:
        raise InvalidContent("a DOCTYPE or entity declaration is not allowed.") from None
    except (ParseError, ValueError):
        raise InvalidContent("the SVG is not well-formed XML.") from None
    if root.tag != f"{{{SVG_NS}}}svg":
        raise InvalidContent('the root element must be <svg xmlns="http://www.w3.org/2000/svg">.')
    for element in root.iter():
        tag = element.tag if isinstance(element.tag, str) else ""
        if not tag.startswith(f"{{{SVG_NS}}}"):
            raise InvalidContent("an element outside the SVG namespace is not allowed.")
        name = tag[len(SVG_NS) + 2 :]
        if name not in SVG_ELEMENTS:
            raise InvalidContent(f"the element <{_safe_name(name)}> is not allowed.")
        for key, value in element.attrib.items():
            if key.startswith("{"):
                ns, local = key[1:].split("}", 1)
                if ns == XLINK_NS and local == "href":
                    attr = "href"
                elif ns == XML_NS and local in ("space", "lang"):
                    continue
                else:
                    raise InvalidContent("an attribute outside the SVG namespace is not allowed.")
            else:
                attr = key
            if attr.lower().startswith("on"):
                raise InvalidContent("event attributes (on...) are not allowed.")
            if attr not in SVG_ATTRIBUTES and not attr.startswith(_ATTR_PREFIXES):
                raise InvalidContent(f"the attribute {_safe_name(attr)} is not allowed.")
            if attr == "href":
                target = value.strip()
                if not (target.startswith("#") or (name == "image" and _DATA_IMAGE.match(target))):
                    raise InvalidContent("links must point inside the SVG (#id); <image> may only embed a PNG, JPEG, GIF or WebP.")
                continue
            _check_value(value, f"the attribute {attr}")
        if name == "style":
            _check_value("".join(element.itertext()), "a <style> block")


# -- chart (FR-024: omni-chart/1) --------------------------------------------------------------

CHART_SCHEMA = "omni-chart/1"
CHART_TYPES = ("bar", "line", "area", "scatter", "pie", "donut")
X_TYPES = ("category", "time", "number")
MAX_SERIES = 8
MAX_ROWS = 5000
MAX_ROW_KEYS = 32
_FIELD = re.compile(r"^[A-Za-z0-9_ .-]{1,64}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f  ‪-‮⁦-⁩]")


def _chart_text(value: Any, what: str, limit: int, *, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise InvalidContent(f"chart {what} must be text of 1 to {limit} characters.")
    if _CONTROL.search(value):
        raise InvalidContent(f"chart {what} contains control characters.")
    return value


def _keys(obj: Any, allowed: set[str], required: set[str], what: str) -> dict:
    if not isinstance(obj, dict):
        raise InvalidContent(f"chart {what} must be an object.")
    extra = set(obj) - allowed
    if extra:
        named = sorted(k for k in extra if isinstance(k, str) and _FIELD.match(k))
        raise InvalidContent(f"chart {what} has keys that are not allowed: {', '.join(named) or '(unnamed)'}.")
    missing = required - set(obj)
    if missing:
        raise InvalidContent(f"chart {what} is missing: {', '.join(sorted(missing))}.")
    return obj


def _number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _is_time(value: Any) -> bool:
    if not isinstance(value, str) or not 4 <= len(value) <= 40:
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def check_chart(spec: Any) -> dict:
    spec = _keys(spec, {"schema", "type", "title", "x", "series", "data", "units"}, {"type", "title", "x", "series", "data"}, "spec")
    if spec.get("schema", CHART_SCHEMA) != CHART_SCHEMA:
        raise InvalidContent(f"chart schema must be {CHART_SCHEMA}.")
    if spec["type"] not in CHART_TYPES:
        raise InvalidContent(f"chart type must be one of {', '.join(CHART_TYPES)}.")
    title = _chart_text(spec["title"], "title", 200)
    x = _keys(spec["x"], {"field", "type", "label"}, {"field", "type"}, "x")
    if not isinstance(x["field"], str) or not _FIELD.match(x["field"]):
        raise InvalidContent("chart x.field must be a field name.")
    if x["type"] not in X_TYPES:
        raise InvalidContent(f"chart x.type must be one of {', '.join(X_TYPES)}.")
    x_label = _chart_text(x.get("label"), "x.label", 80, required=False)
    series = spec["series"]
    if not isinstance(series, list) or not 1 <= len(series) <= MAX_SERIES:
        raise InvalidContent(f"chart series must list 1 to {MAX_SERIES} series.")
    if spec["type"] in ("pie", "donut") and len(series) != 1:
        raise InvalidContent("a pie or donut chart takes exactly one series.")
    fields: list[str] = []
    clean_series = []
    for item in series:
        item = _keys(item, {"field", "label"}, {"field", "label"}, "series item")
        if not isinstance(item["field"], str) or not _FIELD.match(item["field"]) or item["field"] == x["field"] or item["field"] in fields:
            raise InvalidContent("each chart series needs its own field name, not the x field.")
        fields.append(item["field"])
        clean_series.append({"field": item["field"], "label": _chart_text(item["label"], "series label", 80)})
    data = spec["data"]
    if not isinstance(data, list) or not 1 <= len(data) <= MAX_ROWS:
        raise InvalidContent(f"chart data must have 1 to {MAX_ROWS} rows.")
    for row in data:
        if not isinstance(row, dict) or len(row) > MAX_ROW_KEYS:
            raise InvalidContent(f"each chart row must be an object of at most {MAX_ROW_KEYS} fields.")
        for key, value in row.items():
            if not isinstance(key, str) or not _FIELD.match(key):
                raise InvalidContent("a chart row has a field name that is not allowed.")
            if value is None or isinstance(value, bool) or _number(value):
                continue
            if isinstance(value, str):
                if len(value) > 200 or _CONTROL.search(value):
                    raise InvalidContent("a chart value is too long or contains control characters.")
                continue
            raise InvalidContent("chart values must be text, numbers, true/false or null.")
        if x["field"] not in row:
            raise InvalidContent("every chart row needs the x field.")
        xv = row[x["field"]]
        ok = {"category": isinstance(xv, str) or _number(xv), "time": _is_time(xv), "number": _number(xv)}[x["type"]]
        if not ok:
            raise InvalidContent(f"a chart row's x value does not fit x.type {x['type']}.")
        for field in fields:
            if field in row and row[field] is not None and not _number(row[field]):
                raise InvalidContent("chart series values must be numbers or null.")
    units = _chart_text(spec.get("units"), "units", 40, required=False)
    out: dict[str, Any] = {"schema": CHART_SCHEMA, "type": spec["type"], "title": title, "x": {"field": x["field"], "type": x["type"]}, "series": clean_series, "data": data}
    if x_label is not None:
        out["x"]["label"] = x_label
    if units is not None:
        out["units"] = units
    return out
