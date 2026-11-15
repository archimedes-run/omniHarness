"""The system checks of a code artifact version (Spec 012 FR-018, Slice 2).

Before an `html` or `react` version is shown as "checked", the gateway runs
the coding jobs' layout probe (code_jobs/layout_probe.py, artifact mode) in
the chat's sandbox on the EXACT frame document the frame route serves
(artifacts_store/frame.frame_document), under the artifact CSP:

* layout at 360, 560 and 1280 px, in the light and the dark theme: no
  sideways overflow, no chart cut off by its own box;
* readable charts at every width and theme (layout_probe.CHART_MEASURE):
  chart labels that do not overlap and are not cut off, and chart marks
  (bars, lines, points, slices) at 3:1 or more against what is behind them;
* the render check: the page loaded and rendered something at every width
  and threw no uncaught error (a react bundle that fails to mount renders
  nothing);
* no network attempted: any CSP violation (from an isolated world and the
  browser's own reports) or any request to anything but the probe's own
  server fails the check.

Fail closed, as in app mode: a fresh, unguessable probe folder per run, the
probe script run only when its checksum matches, a per-run nonce and the
SHA-256 of the document it loaded both echoed back in the result, and a
clean exit. A result without them (or with others), an unreadable result, a
missing sandbox: the version is `not_checked`, never shown as checked.

The result is produced INSIDE the chat's sandbox, which the chat's own code
shares: it is a quality signal for the owner, NOT a security boundary. The
frame isolates every version the same way whatever its checks say (the
gateway never kills the sandbox's other processes to run them). A version that fails is
still stored and viewable, labelled with what failed (artifacts are the
owner's drafts).

`summary` is in the system's own words only (it reaches the model in a
trusted tool result); `failures` may carry the page's own element names and
error text and are shown to the owner as text and given to the model only
fenced, through artifact_read.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import shlex
import time
from collections.abc import Callable

from app.gateway.artifacts_store import frame
from app.gateway.code_jobs import layout as layout_mod

logger = logging.getLogger(__name__)

WIDTHS = layout_mod.WIDTHS
THEMES = ("light", "dark")
MAX_RESULT_CHARS = 65536
SHOT_MAX_BYTES = 1_500_000
B = "/usr/bin"
_LOAD = layout_mod.LOAD_ERRORS


def _q(text: str) -> str:
    return shlex.quote(text)


def _int(value, limit: int = 1_000_000) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 <= value <= limit else None


def _widths(ws: list[int]) -> str:
    return ", ".join(str(w) for w in ws) + " px"


#: The chart marks the probe names, in the words the model reads.
MARKS = {"bars": "chart bars", "points": "chart points", "lines": "chart lines", "slices": "chart slices or areas"}
CHART_CONTRAST = 3.0


def _labels(entry: dict) -> str:
    names = [layout_mod._text(v, 24) for v in (entry.get("labels") or [])[:2] if isinstance(v, str)]  # noqa: SLF001
    names = [n for n in names if n]
    return " (" + " and ".join(f"'{n}'" for n in names) + ")" if names else ""


def _charts(page: dict) -> dict | None:
    """The page's chart measurements, or None when missing or malformed (the
    run is then unreadable: fail closed)."""
    charts = page.get("charts")
    if not isinstance(charts, dict) or charts.get("failed") is not None:
        return None
    if _int(charts.get("seen")) is None or _int(charts.get("unmeasured")) is None:
        return None
    for key in ("overlap", "row_overlap", "clipped", "contrast"):
        if not isinstance(charts.get(key), list) or not all(isinstance(e, dict) for e in charts[key]):
            return None
    for entry in charts["contrast"]:
        if entry.get("kind") not in MARKS or isinstance(entry.get("ratio"), bool) or not isinstance(entry.get("ratio"), (int, float)) or not 1 <= entry["ratio"] < CHART_CONTRAST:
            return None
    return charts


def base(seconds: float = 0.0) -> dict:
    return {"kind": "artifact", "widths": list(WIDTHS), "themes": list(THEMES), "seconds": round(seconds, 1), "outcome": "pass", "summary": [], "failures": [], "warnings": [], "error": None, "error_code": None, "shots": []}


def error(code: str, seconds: float = 0.0) -> dict:
    wording = layout_mod.ERRORS.get(code, ("the checks gave no answer", True))[0]
    return {**base(seconds), "outcome": "error", "error": wording, "error_code": code, "summary": [f"the checks gave no answer: {wording}"]}


def parse(raw: str | None, *, exit_code: int | None, nonce: str, prod_sha256: str, seconds: float = 0.0) -> dict:
    """The probe's artifact-mode result, checked field by field. Anything
    malformed is an error (not_checked), never an exception."""
    try:
        return _parse(raw, exit_code=exit_code, nonce=nonce, prod_sha256=prod_sha256, seconds=seconds)
    except (TypeError, AttributeError, KeyError, ValueError, IndexError):
        return error("unreadable", seconds)


def _parse(raw: str | None, *, exit_code: int | None, nonce: str, prod_sha256: str, seconds: float) -> dict:
    if exit_code == 97:
        return error("checksum", seconds)
    data = None
    if raw is not None and len(raw) <= MAX_RESULT_CHARS:
        try:
            data = json.loads(raw)
        except (ValueError, RecursionError):
            data = None
    if not isinstance(data, dict) or data.get("v") != 1:
        if exit_code is None:
            return error("no_answer", seconds)
        if exit_code in (124, 137):
            out = base(seconds)
            why = f"the page kept the browser busy past the checks' {layout_mod.ARTIFACT_TIMEOUT_SECONDS} s limit"
            return {**out, "outcome": "fail", "summary": [why], "failures": [why]}
        return error("no_python" if exit_code in (126, 127) and raw is None else "unreadable", seconds)
    if data.get("setup_error") is not None:
        code = data.get("setup_error")
        return error(code if code in layout_mod.ERRORS and code not in ("no_answer", "no_python", "checksum") else "unreadable", seconds)
    # Made by THIS run of the probe on THESE bytes, or it does not count.
    # A result counts only from a probe that EXITED 0 having written it itself.
    if data.get("mode") != "artifact" or data.get("nonce") != nonce or data.get("prod_sha256") != prod_sha256 or exit_code != 0:
        return error("tampered", seconds)
    runs = data.get("runs")
    if not isinstance(runs, list) or len(runs) > len(THEMES):
        return error("unreadable", seconds)
    summary: list[str] = []
    failures: list[str] = []
    warnings: list[str] = []
    overflow: dict[str, list[str]] = {}
    clipped: list[str] = []
    blank: list[str] = []
    errors: dict[str, list[str]] = {}
    network: list[str] = []
    overlap: dict[str, list[str]] = {}
    row_overlap: dict[str, list[str]] = {}
    cut: dict[str, list[str]] = {}
    faint: dict[str, dict] = {}  # theme -> {"ratio", "kinds", "widths"}
    seen = unmeasured = 0
    for i, run in enumerate(runs):
        theme = THEMES[i]
        if not isinstance(run, dict) or run.get("theme") != theme:
            return error("unreadable", seconds)
        if run.get("loaded") is not True:
            why = _LOAD.get(run.get("load_error"), "no reason given")
            summary.append(f"did not load in the {theme} theme ({why})")
            failures.append(summary[-1])
            continue
        pages = run.get("pages")
        if not isinstance(pages, list) or len(pages) != len(WIDTHS):
            return error("unreadable", seconds)
        violations = [v for v in (run.get("violations") or []) if isinstance(v, str)]
        blocked = _int(run.get("blocked")) or 0
        rtc = _int(run.get("rtc")) or 0
        if run.get("rtc_watched") is not True:
            return error("unreadable", seconds)
        if rtc:
            network.append(theme)
            failures.append(f"tried WebRTC in the {theme} theme ({rtc} attempt(s) seen by the system)")
        if violations or blocked:
            network.append(theme)
            names = ", ".join(sorted({v for v in violations if v})[:6])
            failures.append(f"tried to reach the network in the {theme} theme" + (f" (blocked: {names})" if names else "") + (f"; {blocked} request(s) to outside stopped" if blocked else ""))
        count = _int(run.get("errors")) or 0
        if count:
            message = layout_mod._text(run.get("first_error"), 120) or "an error"  # noqa: SLF001
            errors.setdefault(message, []).append(theme)
        for j, page in enumerate(pages):
            width = WIDTHS[j]
            if not isinstance(page, dict) or page.get("width") != width:
                return error("unreadable", seconds)
            over = _int(page.get("overflow_px"))
            if over is None or not isinstance(page.get("rendered"), bool) or not isinstance(page.get("svgs"), list):
                return error("unreadable", seconds)
            charts = _charts(page)
            if charts is None:
                return error("unreadable", seconds)
            seen = max(seen, charts["seen"])
            unmeasured = max(unmeasured, charts["unmeasured"])
            for entry in charts["overlap"][:3]:
                overlap.setdefault(f"{width}", []).append(theme)
                failures.append(f"chart labels overlap: {layout_mod._where(entry.get('where'))} at {width} px ({theme}){_labels(entry)}")  # noqa: SLF001
            for entry in charts["row_overlap"][:3]:
                row_overlap.setdefault(f"{width}", []).append(theme)
                failures.append(f"labels in a row overlap: {layout_mod._where(entry.get('where'))} at {width} px ({theme}){_labels(entry)}")  # noqa: SLF001
            for entry in charts["clipped"][:3]:
                cut.setdefault(f"{width}", []).append(theme)
                failures.append(f"chart text cut off: {layout_mod._where(entry.get('where'))} at {width} px ({theme}){_labels(entry)}")  # noqa: SLF001
            for entry in charts["contrast"][:3]:
                slot = faint.setdefault(theme, {"ratio": 99.0, "kinds": [], "widths": []})
                slot["ratio"] = min(slot["ratio"], float(entry["ratio"]))
                if entry["kind"] not in slot["kinds"]:
                    slot["kinds"].append(entry["kind"])
                if width not in slot["widths"]:
                    slot["widths"].append(width)
                failures.append(f"{MARKS[entry['kind']]} too faint against the background: {layout_mod._where(entry.get('where'))} at {width} px ({theme}; {float(entry['ratio']):.2f}:1, needs 3:1)")  # noqa: SLF001
            if not page["rendered"]:
                blank.append(f"{width} px {theme}")
            if over > 1:
                names = [layout_mod._where(o) for o in (page.get("offenders") or [])[:3] if isinstance(o, str)]  # noqa: SLF001
                overflow.setdefault(f"{width}", []).append(theme)
                failures.append(f"overflows sideways at {width} px ({theme}) by {over} px" + (f" (sticking out: {', '.join(names)})" if names else ""))
            for svg in page["svgs"][:3]:
                if isinstance(svg, dict) and svg.get("kind") != "text" and _int(svg.get("px")) is not None:
                    clipped.append(f"{width} px {theme}")
                    failures.append(f"chart clipped: {layout_mod._where(svg.get('where'))} at {width} px ({theme})")  # noqa: SLF001
                elif isinstance(svg, dict) and svg.get("kind") == "text":
                    warnings.append(f"chart labels may be cut at {width} px ({theme})")
    if len(runs) < len(THEMES):
        if data.get("timed_out") is True or data.get("browser_exit") is True:
            why = "the page kept the browser busy past the checks' time limit" if data.get("timed_out") else "the browser closed while loading the page"
            summary.append(why)
            failures.append(why)
        else:
            return error("unreadable", seconds)
    if network:
        summary.append(f"tried to reach the network ({', '.join(network)}); the frame blocks it")
    if blank:
        summary.append(f"rendered nothing ({'; '.join(blank[:3])})")
        failures.append(summary[-1])
    for message, themes in errors.items():
        summary.append(f"uncaught error on load ({', '.join(themes)})")
        failures.append(f"uncaught error on load ({', '.join(themes)}): {message}")
    for width, themes in overflow.items():
        summary.append(f"overflows sideways at {width} px ({', '.join(themes)})")
    if clipped:
        summary.append(f"a chart is cut off ({'; '.join(clipped[:3])})")
    for width, themes in overlap.items():
        summary.append(f"chart labels overlap at {width} px ({', '.join(dict.fromkeys(themes))}): wrap, rotate, shorten or thin them")
    for width, themes in row_overlap.items():
        summary.append(f"labels in a row overlap at {width} px ({', '.join(dict.fromkeys(themes))}): let them wrap or shorten them")
    for width, themes in cut.items():
        summary.append(f"chart text is cut off at {width} px ({', '.join(dict.fromkeys(themes))}): keep every label inside the chart")
    for theme, slot in faint.items():
        kinds = " and ".join(MARKS[k] for k in slot["kinds"][:2])
        summary.append(f"{kinds} have too little contrast with the background in {theme} (worst {slot['ratio']:.2f}:1, needs 3:1): use a theme colour such as var(--primary)")
    if unmeasured:
        warnings.append("some chart colours (gradients, patterns or images behind them) were not measured")
    shots = [s for s in (data.get("shots") or []) if isinstance(s, dict) and s.get("file") and s.get("theme") in THEMES and _int(s.get("bytes"), SHOT_MAX_BYTES)]
    return {**base(seconds), "outcome": "fail" if failures else "pass", "summary": summary[:8], "failures": failures[:14], "warnings": list(dict.fromkeys(warnings))[:5], "shots": shots[:2], "charts": seen}


def state_of(result: dict) -> str:
    return {"pass": "passed", "fail": "failed"}.get(result.get("outcome"), "not_checked")


def capped_read(ops, path: str, cap: int, *, timeout: int = 30) -> bytes | None:
    """A regular file (not a link) read in ONE command through `head -c cap+1`,
    its bytes coming back on that command's own output: whatever the file
    becomes meanwhile (it grows, it is swapped), at most cap+1 bytes are read,
    and more than `cap` is refused. None when missing, a link, or over."""
    import base64 as b64

    _, out = ops.sh(f"[ -f {_q(path)} ] && [ ! -L {_q(path)} ] && {B}/head -c {cap + 1} {_q(path)} | {B}/base64 -w0; echo", timeout=timeout)
    text = (out or "").strip()
    if not text or len(text) > (cap + 3) * 4 // 3 + 4:
        return None
    try:
        data = b64.b64decode(text, validate=True)
    except ValueError:
        return None
    return data if len(data) <= cap else None


def read_small(ops, path: str, limit: int) -> str | None:
    """A small text file through capped_read, or None."""
    data = capped_read(ops, path, limit)
    if data is None:
        return None
    return data.decode("utf-8", "replace")


def with_findings(result: dict, blocking_findings: list[str]) -> dict:
    """A page the strict profile will not run fails the check, in those words."""
    if not blocking_findings or result.get("outcome") == "error":
        return result
    words = [f.split(": ", 1)[1] if ": " in f else f for f in blocking_findings]
    out = dict(result)
    out["outcome"] = "fail"
    out["summary"] = [f"will not run in the frame: {w}" for w in words][:3] + list(result.get("summary") or [])
    out["failures"] = [f"will not run in the frame: {w}" for w in words] + list(result.get("failures") or [])
    return out


def run(ops, stored: bytes, *, beat: Callable[[], None] | None = None) -> tuple[dict, dict[str, bytes]]:
    """Run the checks on `stored` (a version's stored document) in the sandbox
    behind `ops`. Returns (result, {theme: png}). Never raises: a failure to
    run is an `error` result (not_checked)."""
    document, hashes = frame.frame_document(stored)
    text = document.decode("utf-8")
    nonce = secrets.token_hex(16)
    directory = f"/tmp/omni-art-{secrets.token_hex(16)}"
    prod = f"{directory}/www/prod"
    t0 = time.monotonic()
    code: int | None = None
    raw: str | None = None
    shots: dict[str, bytes] = {}
    try:
        _, made = ops.sh(f"{B}/mkdir -m 700 {_q(directory)} && {B}/mkdir -p -m 755 {_q(prod)} && echo __made__", timeout=15)
        if "__made__" not in made:
            return error("server", time.monotonic() - t0), {}
        ops.write(f"{directory}/layout_probe.py", layout_mod.SCRIPT)
        ops.write(f"{prod}/index.html", text)
        csp = frame.csp(hashes)
        ops.write(f"{directory}/check.json", json.dumps({"csp": csp, "nonce": nonce}))
        if beat:
            beat()
        cmd = layout_mod.command(directory, f"{directory}/www", "artifact-check", nonce=nonce, artifact=True)
        code, _ = ops.sh(cmd, timeout=layout_mod.ARTIFACT_TIMEOUT_SECONDS + 20)
        if beat:
            beat()
        raw = read_small(ops, f"{directory}/result.json", MAX_RESULT_CHARS)
        result = parse(raw, exit_code=code, nonce=nonce, prod_sha256=hashlib.sha256(document).hexdigest(), seconds=time.monotonic() - t0)
        if result["outcome"] in ("pass", "fail"):
            for shot in result.get("shots") or []:
                try:
                    png = capped_read(ops, f"{directory}/{shot['file']}", SHOT_MAX_BYTES, timeout=60)
                except Exception:  # noqa: BLE001 - a screenshot is shown, never evidence
                    png = None
                if png and png.startswith(b"\x89PNG\r\n\x1a\n"):
                    shots[shot["theme"]] = png
        return result, shots
    except Exception:  # noqa: BLE001 - the sandbox API failed: no answer (fail closed)
        logger.warning("artifact checks could not run", exc_info=True)
        return error("no_answer", time.monotonic() - t0), {}
    finally:
        try:
            ops.sh(f"{B}/rm -rf {_q(directory)}", timeout=15)
        except Exception:  # noqa: BLE001
            pass


def model_lines(result: dict, state: str) -> list[str]:
    """What the model reads in the (trusted) tool result: system words only."""
    widths = "/".join(str(w) for w in WIDTHS)
    if state == "passed":
        charts = "; charts readable (labels neither overlap nor cut off, marks at 3:1 or more)" if result.get("charts") else ""
        return [f"System checks passed: no network attempts seen, it renders, layout fits at {widths} px in light and dark{charts} (a quality check, not a guarantee)."]
    if state == "failed":
        return ["System checks FAILED: " + "; ".join(result.get("summary") or ["see the details"]) + "."]
    return ["System checks gave no answer: " + "; ".join(result.get("summary") or ["the checks did not run"]) + ". The version is not shown as checked."]
