"""The system's checks of an app-mode coding job (Spec 011 FR-026, FR-027).

After the build passes, the gateway (never the worker):

  1. reads the project's omni-app.json and validates it against the catalog;
  2. reads the build output and inlines it, in process, with the SAME code
     registration uses (app.gateway.apps.bundle.inline): one HTML file, no
     remote reference, none of the names registration refuses, at most 2 MB
     with the platform shim;
  3. scans the worker's source files for the APIs the app rules forbid (the
     network, HTML from strings, eval, frames, workers, dynamic import);
  4. builds the MOCK document (the mock shim and the sample data as its first
     script) and runs the layout probe in app mode (layout_probe.py): every
     theme x state x width, under the app's CSP with Trusted Types, measuring
     overflow, clipped charts, contrast, text sizes, touch targets, nested
     frames, blocked requests and the tile words, and taking screenshots.

`parse` turns the probe's file into the result, strictly: the summary is in
the system's own words; element names and error text come from the page and
are listed only as fenced data. Layout, contrast, state and safety failures
block registration (`outcome: fail`). What the system measures but does not
block on (small text, small targets, own empty wording) is listed as design
findings for the lead's design passes; the rest of the design checklist is
the lead's judgement from the screenshots.
"""

from __future__ import annotations

import json
import re
import shlex

from . import layout as layout_mod

THEMES = ("light", "dark")
STATES = ("fresh", "empty", "not_connected", "failed")
#: The probe's own budget in app mode is 100 s; this is the hard stop around it.
TIMEOUT_SECONDS = layout_mod.APP_TIMEOUT_SECONDS
MAX_RESULT_CHARS = 131072
MAX_FAILURES = 14
MAX_DESIGN = 8
#: The design passes a single app may have (FR-027).
DESIGN_PASSES = 3
#: Screenshots: at most this many, each at most this large (the probe caps too).
MAX_SHOTS = 6
SHOT_MAX_BYTES = 1_500_000
#: The build output read into the gateway for inlining.
DIST_MAX_FILES = 300
DIST_MAX_BYTES = 2 * 1024 * 1024  # = the bundle cap: inlining only grows it
TEXT_EXTENSIONS = (".html", ".htm", ".js", ".mjs", ".cjs", ".css", ".json", ".svg", ".txt", ".webmanifest")

#: The fixed design checklist (FR-027): (key, words, measured by the system?).
CHECKLIST: tuple[tuple[str, str, bool], ...] = (
    ("hierarchy", "Hierarchy: the page title, tile titles, key numbers and meta text read in that order of weight", False),
    ("spacing", "Spacing rhythm: gaps and padding on a 4 px grid, equal between tiles", False),
    ("grid", "Alignment to the grid: tiles line up in columns and rows, edges aligned", False),
    ("states", "Tile state completeness: every tile shows fresh, empty, not connected and failed with the standard words", True),
    ("empty_failed", 'Empty and failed states: "Nothing today" only when empty; "Can\'t tell" with the reason when failed', True),
    ("type", "Typography scale: 12 / 14 / 16 / 20 / 28 px; no text under 12 px", True),
    ("charts", "Charts: a title or label, axis or value labels, a legend when there is more than one series", False),
    ("overflow", "No overflow or clipping: nothing scrolls sideways, no chart or label is cut off", True),
    ("phone", "Phone layout at 360 px: one column, readable, nothing cramped", False),
    ("themes", "Both themes: light and dark both look intended, no hard-coded colours", False),
    ("contrast", "Contrast: text AA (4.5:1, large 3:1) in both themes", True),
    ("targets", "Touch targets at least 24 px", True),
)

#: The worker's source files are scanned for these (the app rules' "Never").
#: (code, words, GNU grep ERE). Code inside node_modules, dist, omni-kit and
#: build configuration is not scanned; the built page is checked under the
#: app's CSP as well.
SOURCE_RULES: tuple[tuple[str, str, str], ...] = (
    ("network", "a network call (fetch, XMLHttpRequest, EventSource, sendBeacon)", r"(^|[^A-Za-z0-9_$.])fetch[[:space:]]*\(|XMLHttpRequest|EventSource|sendBeacon"),
    ("socket", "WebSocket or WebRTC", r"WebSocket|RTCPeerConnection|RTCDataChannel"),
    ("html_string", "HTML from a string (innerHTML, outerHTML, insertAdjacentHTML, dangerouslySetInnerHTML, document.write)", r"innerHTML|outerHTML|insertAdjacentHTML|dangerouslySetInnerHTML|document\.write|createContextualFragment"),
    ("eval", "eval or new Function", r"(^|[^A-Za-z0-9_$.])eval[[:space:]]*\(|new[[:space:]]+Function([^A-Za-z0-9_$]|$)"),
    ("frame", "a frame, popup or embedded object (iframe, srcdoc, object, embed, window.open, target _blank)", r"<iframe|['\"`]iframe['\"`]|srcdoc|<object|<embed|window\.open|_blank"),
    ("dynamic_import", "a dynamic import()", r"(^|[^A-Za-z0-9_$.])import[[:space:]]*\("),
    ("worker", "a web worker or service worker", r"new[[:space:]]+(Shared)?Worker[[:space:]]*\(|serviceWorker"),
)
_SOURCE_INCLUDE = ("*.js", "*.jsx", "*.ts", "*.tsx", "*.mjs", "*.cjs", "*.vue", "*.svelte", "*.html", "*.htm")
_SOURCE_SKIP_DIRS = ("node_modules", "dist", "build", "omni-kit", ".git", ".vite", ".cache", "coverage")
_SOURCE_SKIP_FILES = ("*.config.*", "*.d.ts", "*.test.*", "*.spec.*")

#: CSP directives the page broke, in words.
_VIOLATION_WORDS = {
    "connect-src": "a network request",
    "require-trusted-types-for": "HTML or script from a string (Trusted Types)",
    "trusted-types": "a Trusted Types policy",
    "frame-src": "a nested frame",
    "child-src": "a nested frame or worker",
    "worker-src": "a worker",
    "img-src": "an image from the network",
    "font-src": "a font from the network",
    "style-src": "a stylesheet from the network",
    "style-src-elem": "a stylesheet from the network",
    "script-src": "a script that is not inlined (or an inline event handler)",
    "script-src-elem": "a script that is not inlined",
    "script-src-attr": "an inline event handler attribute",
    "media-src": "media from the network",
    "object-src": "an embedded object",
    "form-action": "a form submission",
    "base-uri": "a <base> element",
    "manifest-src": "a web manifest",
}
_WHERE = re.compile(r"[^A-Za-z0-9_#.\- ]")


def probe_csp(script_hashes: list[str]) -> str:
    """The app's CSP (FR-016) for the mock document, with Trusted Types."""
    from app.gateway.apps.bundle import csp

    policy = csp(script_hashes)
    if "require-trusted-types-for" not in policy:
        policy += "; require-trusted-types-for 'script'; trusted-types 'none'"
    return policy


def probe_command(directory: str, root: str, job_id: str) -> str:
    """layout.command in app mode, with its longer hard stop."""
    return layout_mod.command(directory, root, job_id, app=True)


# -- the source scan ---------------------------------------------------------------


def scan_command(project: str, out: str) -> str:
    """grep over the worker's source files, by absolute path with a fixed
    PATH; matches (file NUL line:text) go to `out`, at most 200 lines."""
    q = shlex.quote
    include = " ".join(f"--include={q(p)}" for p in _SOURCE_INCLUDE)
    skip_dirs = " ".join(f"--exclude-dir={q(d)}" for d in _SOURCE_SKIP_DIRS)
    skip_files = " ".join(f"--exclude={q(f)}" for f in _SOURCE_SKIP_FILES)
    patterns = " ".join(f"-e {q(rule[2])}" for rule in SOURCE_RULES)
    return f"cd {q(project)} 2>/dev/null && /usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C /usr/bin/grep -rnoIEZ {include} {skip_dirs} {skip_files} {patterns} . 2>/dev/null | /usr/bin/head -n 200 > {q(out)}; true"


def parse_scan(raw: str | None) -> list[dict]:
    """Findings: [{code, words, file, line}] (file names are the worker's)."""
    found: dict[tuple[str, str], dict] = {}
    compiled = [(code, words, re.compile(_ere_to_python(pattern))) for code, words, pattern in SOURCE_RULES]
    for row in (raw or "").splitlines()[:200]:
        if "\x00" not in row:
            continue
        path, rest = row.split("\x00", 1)
        line, _, text = rest.partition(":")
        for code, words, pattern in compiled:
            if pattern.search(text):
                key = (code, path)
                if key not in found:
                    found[key] = {"code": code, "words": words, "file": _text(path.removeprefix("./"), 120), "line": int(line) if line.isdigit() else 0}
                break
    return list(found.values())[:20]


def _ere_to_python(pattern: str) -> str:
    return pattern.replace("[[:space:]]", r"\s")


# -- the probe's result ---------------------------------------------------------------


def _text(value, n: int) -> str:
    text = value if isinstance(value, str) else ""
    return "".join(c if c.isprintable() else " " for c in text)[:n].strip()


def _where(value) -> str:
    return _WHERE.sub("", _text(value, 120))[:100] or "an element"


def _int(value, limit: int = 1_000_000) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 <= value <= limit else None


def _num(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _join(items: list[str]) -> str:
    return ", ".join(dict.fromkeys(items))


def base_result(*, mode: str = "enforce", seconds: float = 0.0) -> dict:
    return {
        "kind": "app",
        "widths": list(layout_mod.WIDTHS),
        "themes": list(THEMES),
        "states": list(STATES),
        "mode": mode,
        "seconds": round(seconds, 1),
        "outcome": "pass",
        "failures": [],
        "summary": [],
        "design": [],
        "warnings": [],
        "shots": [],
        "error": None,
        "error_code": None,
        "counted": False,
        "publishable": True,
        "bundle": None,
        "scan": [],
    }


def failed_before_probe(why: str, detail: str | None = None, *, publishable: bool = False, mode: str = "enforce", bundle: dict | None = None, scan: list[dict] | None = None) -> dict:
    """A failure found before the page was loaded (manifest, bundle, scan).
    `why` is the system's words; `detail` may carry the worker's names."""
    out = base_result(mode=mode)
    out.update(outcome="fail", summary=[why], failures=[why + (f": {detail}" if detail else "")], publishable=publishable, bundle=bundle, scan=scan or [])
    return out


def parse(raw: str | None, *, exit_code: int | None, mode: str = "enforce", seconds: float = 0.0, data_sources: list[str] | None = None) -> dict:
    """The app probe's result file, checked field by field."""
    base = base_result(mode=mode, seconds=seconds)

    def error(code: str) -> dict:
        wording, counted = layout_mod.ERRORS[code]
        return {**base, "outcome": "error", "error": wording, "error_code": code, "counted": counted}

    def broken(why: str) -> dict:
        return {**base, "outcome": "fail", "failures": [why], "summary": [why], "publishable": False}

    if exit_code == 97:
        return error("checksum")
    data = None
    if raw is not None and len(raw) <= MAX_RESULT_CHARS:
        try:
            data = json.loads(raw)
        except (ValueError, RecursionError):
            data = None
    if raw is None or not isinstance(data, dict) or data.get("v") != 1:
        if exit_code in (124, 137):
            return broken(f"the page kept the browser busy past the check's {TIMEOUT_SECONDS} s limit")
        if exit_code is None:
            return error("no_answer")
        if exit_code in (126, 127) and raw is None:
            return error("no_python")
        return error("unreadable")
    if data.get("setup_error") is not None:
        code = data.get("setup_error")
        return error(code if isinstance(code, str) and code in layout_mod.ERRORS and code not in ("no_answer", "no_python", "checksum") else "unreadable")
    runs = data.get("runs")
    if data.get("mode") != "app" or not isinstance(runs, list) or len(runs) > len(THEMES) * len(STATES):
        return error("unreadable")

    sources = list(data_sources or [])
    failures: list[str] = []
    summary: list[str] = []
    design: list[str] = []
    warnings: list[str] = []
    is_broken = False
    overflow: dict[int, list] = {}  # width -> [max px, names, where]
    clipped: dict[str, list] = {}
    labels: dict[str, list] = {}
    errors: dict[str, list[str]] = {}
    blank: list[str] = []
    contrast: dict[str, list] = {}  # theme -> [worst ratio, need, where, count]
    small_text: dict[str, float] = {}
    small_targets: dict[str, tuple[int, int]] = {}
    violations: dict[str, list[str]] = {}
    frames: list[str] = []
    junk: list[str] = []
    missing_data: dict[str, list[str]] = {}
    state_problems: dict[str, list[str]] = {}
    own_empty_words: list[str] = []
    unwatched = False

    expected = [(t, s) for t in THEMES for s in STATES]
    for i, run in enumerate(runs):
        if not isinstance(run, dict) or (run.get("theme"), run.get("state")) != expected[i]:
            return error("unreadable")
        theme, state = expected[i]
        label = f"{theme}/{state.replace('_', ' ')}"
        if run.get("crashed") is True:
            failures.append(f"the page crashed the browser ({label})")
            summary.append(failures[-1])
            is_broken = True
            continue
        if run.get("loaded") is not True:
            failures.append(f"did not load ({label}: {layout_mod.LOAD_ERRORS.get(run.get('load_error'), 'no reason given')})")
            summary.append(f"did not load ({label})")
            is_broken = True
            continue
        pages = run.get("pages")
        if not isinstance(pages, list) or len(pages) != len(layout_mod.WIDTHS):
            return error("unreadable")
        if run.get("watched") is not True:
            unwatched = True
        for v in run.get("violations") or []:
            directive = _text(v, 40)
            if directive:
                violations.setdefault(directive, []).append(label)
        count = _int(run.get("errors")) or 0
        if count:
            errors.setdefault(_text(run.get("first_error"), 120) or "an error", []).append(label)
        for j, page in enumerate(pages):
            width = layout_mod.WIDTHS[j]
            if not isinstance(page, dict) or page.get("width") != width or not isinstance(page.get("app"), dict):
                return error("unreadable")
            app = page["app"]
            px = _int(page.get("overflow_px"))
            words = app.get("words")
            if px is None or not isinstance(page.get("rendered"), bool) or not isinstance(words, dict) or not isinstance(app.get("sentinels"), dict):
                return error("unreadable")
            if not page["rendered"]:
                blank.append(f"{label} at {width} px")
            if px > 1:
                slot = overflow.setdefault(width, [0, [], []])
                slot[0] = max(slot[0], px)
                slot[1] += [_where(o) for o in (page.get("offenders") or [])[:3] if isinstance(o, str)]
                slot[2].append(label)
            for svg in (page.get("svgs") or [])[:5]:
                if not isinstance(svg, dict) or _int(svg.get("px")) is None or svg.get("side") not in ("left", "right", "top", "bottom"):
                    continue
                bucket = labels if svg.get("kind") == "text" else clipped
                found = bucket.setdefault(_where(svg.get("where")), [(svg["side"], svg["px"]), []])
                found[0] = max(found[0], (svg["side"], svg["px"]), key=lambda e: e[1])
                found[1].append(f"{width} px")
            low = _int(app.get("contrast_low")) or 0
            if low:
                slot = contrast.setdefault(theme, [99.0, 4.5, "", 0])
                slot[3] = max(slot[3], low)
                for c in (app.get("contrast") or [])[:6]:
                    ratio = _num(c.get("ratio")) if isinstance(c, dict) else None
                    if ratio is not None and ratio < slot[0]:
                        slot[0], slot[1], slot[2] = ratio, _num(c.get("need")) or 4.5, _where(c.get("where"))
            for s in (app.get("small_text_where") or [])[:4]:
                if isinstance(s, dict) and _num(s.get("px")) is not None:
                    small_text.setdefault(_where(s.get("where")), float(s["px"]))
            for s in (app.get("small_targets_where") or [])[:4]:
                if isinstance(s, dict) and _int(s.get("w")) is not None and _int(s.get("h")) is not None:
                    small_targets.setdefault(_where(s.get("where")), (s["w"], s["h"]))
            if (_int(app.get("frames")) or 0) > 0:
                frames.append(label)
            if (_int(words.get("junk")) or 0) > 0:
                junk.append(label)
            if j != 0:
                continue  # the words are read once per theme and state (at 360 px)
            n = {k: _int(words.get(k)) or 0 for k in ("updated", "ago", "nothing", "not_connected", "cant_tell", "connect")}
            shown = {k: v is True for k, v in app["sentinels"].items()}
            problems = state_problems.setdefault(state, [])
            if state == "fresh":
                for name in sources:
                    if not shown.get(name):
                        missing_data.setdefault(name, []).append(theme)
                if not n["ago"]:
                    problems.append('no "updated N min ago"')
            elif state == "empty":
                if any(shown.values()):
                    problems.append("still shows sample data")
                if n["cant_tell"] or n["not_connected"]:
                    problems.append('says "Can\'t tell" or "Not connected"')
                if not n["nothing"]:
                    own_empty_words.append(theme)
            elif state == "not_connected":
                if not n["not_connected"]:
                    problems.append('no "Not connected"')
                if not n["connect"]:
                    problems.append("no Connect button")
                if n["nothing"]:
                    problems.append('says "Nothing today"')
                if any(shown.values()):
                    problems.append("shows sample data")
            elif state == "failed":
                if not n["cant_tell"]:
                    problems.append('no "Can\'t tell"')
                if words.get("reason") is not True:
                    problems.append("the failure reason is not shown")
                if n["nothing"]:
                    problems.append('says "Nothing today"')
                if any(shown.values()):
                    problems.append("shows sample data")

    def add(full: str, short: str | None = None) -> None:
        failures.append(full)
        summary.append(short or full)

    if blank:
        add(f"rendered nothing ({_join(blank[:4])})")
        is_broken = True
    for message, where in errors.items():
        add(f"uncaught error on load ({_join(where[:4])}): {message}", f"uncaught error on load ({_join(where[:4])})")
    for width in sorted(overflow):
        px, names, where = overflow[width]
        names = list(dict.fromkeys(names))[:3]
        short = f"overflows sideways at {width} px by {px} px"
        add(short + (f" (sticking out: {', '.join(names)})" if names else ""), short)
    for where, ((side, px), at) in clipped.items():
        add(f"chart clipped: {where} (cut off {px} px on the {side}) at {_join(at)}", f"a chart is cut off by {px} px at {_join(at)}")
    for where, ((side, px), at) in labels.items():
        warnings.append(f"chart labels may be cut: {where} ({px} px past the {side}) at {_join(at)}")
    for theme in THEMES:
        if theme in contrast:
            ratio, need, where, count = contrast[theme]
            add(f"text below AA contrast in {theme} ({count} element{'s' if count != 1 else ''}; worst {ratio:.2f}:1 where {need:g}:1 is needed: {where})", f"text below AA contrast in {theme} (worst {ratio:.2f}:1)")
    for directive, where in violations.items():
        what = _VIOLATION_WORDS.get(directive, "something")
        add(f"the page tried {what}, which the app's CSP blocks ({directive}; {_join(where[:3])})", f"the page tried {what}, which apps may not do")
    if frames:
        add(f"the page has a nested frame or embedded object ({_join(frames[:3])})")
    if junk:
        add(f'the page shows "undefined", "NaN", "Invalid Date" or "[object Object]" ({_join(junk[:4])})')
    for name, themes in missing_data.items():
        add(f"the fresh state shows none of the sample data of source {name} ({_join(themes)})", "a tile shows none of its data in the fresh state")
    for state in STATES:
        for problem in dict.fromkeys(state_problems.get(state) or []):
            add(f"{state.replace('_', ' ')} state: {problem}")
    if len(runs) < len(expected):
        missing = expected[len(runs)]
        if data.get("timed_out") is True:
            add(f"the page kept the browser busy past the check's time limit (at {missing[0]}/{missing[1].replace('_', ' ')})")
        elif data.get("browser_exit") is True:
            add(f"the browser closed while loading the page (at {missing[0]}/{missing[1].replace('_', ' ')})")
        else:
            return error("unreadable")
        is_broken = True
    if small_text:
        design.append("text under 12 px: " + ", ".join(f"{w} ({px:g} px)" for w, px in list(small_text.items())[:4]))
    if small_targets:
        design.append("touch targets under 24 px: " + ", ".join(f"{w} ({a}x{b} px)" for w, (a, b) in list(small_targets.items())[:4]))
    if own_empty_words:
        design.append('the empty state does not say "Nothing today": check that every tile has its own wording of nothing')
    if unwatched:
        add("the check could not watch the page for blocked requests in every run")

    shots = []
    for shot in (data.get("shots") or [])[:MAX_SHOTS]:
        if not isinstance(shot, dict) or shot.get("theme") not in THEMES or shot.get("width") not in layout_mod.WIDTHS:
            continue
        name = f"shot-{shot['theme']}-{shot['width']}.png"
        size = _int(shot.get("bytes"), SHOT_MAX_BYTES)
        if shot.get("file") == name and size:
            shots.append({"theme": shot["theme"], "width": shot["width"], "file": name, "bytes": size})
    return {
        **base,
        "outcome": "fail" if failures else "pass",
        "publishable": not is_broken,
        "failures": failures[:MAX_FAILURES],
        "summary": summary[:MAX_FAILURES],
        "design": design[:MAX_DESIGN],
        "warnings": warnings[:5],
        "shots": shots,
    }


# -- the lead's report ---------------------------------------------------------------


def blocks(result: dict | None) -> bool:
    """App mode fails closed: anything but a clean pass blocks registration
    (no answer, a browser or server that did not start, an unreadable or
    oversized result, a checksum mismatch, an unwatched run)."""
    return not result or result.get("outcome") != "pass"


def reason(result: dict) -> str:
    if result.get("outcome") == "error":
        return f"the app checks gave no answer: {result.get('error')}"
    items = result.get("summary") or []
    more = len(items) - 3
    return "the app checks failed: " + "; ".join(items[:3]) + (f"; and {more} more" if more > 0 else "")


def checklist_lines() -> list[str]:
    lines = []
    for _key, words, measured in CHECKLIST:
        lines.append(f"  - {words} ({'measured by the system' if measured else 'your judgement from the screenshots'})")
    return lines


def report_lines(result: dict, fenced) -> list[str]:
    widths = " / ".join(str(w) for w in layout_mod.WIDTHS)
    head = f"- App checks (run by the system on the mock build with sample data: {widths} px x light and dark x every tile fresh, empty, not connected and failed, under the app's CSP):"
    lines: list[str] = []
    bundle = result.get("bundle") or {}
    if bundle.get("bytes"):
        lines.append(f"- Single-file bundle: {round(bundle['bytes'] / 1024)} KB of {round(bundle.get('limit', 0) / 1024)} KB, the platform shim included.")
    outcome = result.get("outcome")
    if outcome == "error":
        lines.append(f"{head} gave no answer ({result.get('error')}); counted: the app is not registered.")
    elif outcome == "pass":
        lines.append(f"{head} all passed: no overflow, no clipped chart, contrast AA, every tile state worded, nothing blocked.")
    else:
        lines.append(f"{head} FAILED, counted: the app is not registered. Failures (element names, file names and error text come from the worker's page):")
        lines += fenced("APP CHECK FAILURES", "\n".join(result.get("failures") or []))
    if result.get("design"):
        lines.append("  Design findings the system measured (not blocking; fix them in a design pass):")
        lines += fenced("DESIGN FINDINGS", "\n".join(result["design"]))
    if result.get("warnings"):
        lines.append("  Warnings (not counted):")
        lines += fenced("APP CHECK WARNINGS", "\n".join(result["warnings"]))
    return lines


def scan_failure(findings: list[dict]) -> str:
    """The source scan's findings as one failure line (file names fenced by the caller)."""
    by_code: dict[str, list[str]] = {}
    for f in findings:
        by_code.setdefault(f["words"], []).append(f"{f['file']}:{f['line']}")
    return "; ".join(f"{words} in {', '.join(where[:3])}" for words, where in by_code.items())
