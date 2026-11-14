"""The system checks of a code artifact version (Spec 012 FR-018, Slice 2).

Before an `html` or `react` version is shown as "checked", the gateway runs
the coding jobs' layout probe (code_jobs/layout_probe.py, artifact mode) in
the chat's sandbox on the EXACT frame document the frame route serves
(artifacts_store/frame.frame_document), under the artifact CSP:

* layout at 360, 560 and 1280 px, in the light and the dark theme: no
  sideways overflow, no chart cut off by its own box;
* the render check: the page loaded and rendered something at every width
  and threw no uncaught error (a react bundle that fails to mount renders
  nothing);
* no network attempted: any CSP violation (from an isolated world and the
  browser's own reports) or any request to anything but the probe's own
  server fails the check.

Fail closed, as in app mode: a fresh, unguessable probe folder per run, the
probe script run only when its checksum matches, a per-run nonce and the
SHA-256 of the document it loaded both echoed back in the result. A result
without them (or with others), an unreadable result, a missing sandbox: the
version is `not_checked`, never shown as checked. A version that fails is
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
    if data.get("mode") != "artifact" or data.get("nonce") != nonce or data.get("prod_sha256") != prod_sha256 or exit_code == 98:
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
    shots = [s for s in (data.get("shots") or []) if isinstance(s, dict) and s.get("file") and s.get("theme") in THEMES and _int(s.get("bytes"), SHOT_MAX_BYTES)]
    return {**base(seconds), "outcome": "fail" if failures else "pass", "summary": summary[:8], "failures": failures[:14], "warnings": list(dict.fromkeys(warnings))[:5], "shots": shots[:2]}


def state_of(result: dict) -> str:
    return {"pass": "passed", "fail": "failed"}.get(result.get("outcome"), "not_checked")


def read_small(ops, path: str, limit: int) -> str | None:
    """A regular file (never a link) of at most `limit` bytes, or None."""
    _, size = ops.sh(f"[ -f {_q(path)} ] && [ ! -L {_q(path)} ] && {B}/stat -c %s {_q(path)} 2>/dev/null || echo none", timeout=15)
    size = size.strip().splitlines()[-1] if size.strip() else ""
    if not size.isdigit():
        return None
    if int(size) > limit:
        return ""
    return ops.read_text(path)


def run(ops, stored: bytes, *, beat: Callable[[], None] | None = None) -> tuple[dict, dict[str, bytes]]:
    """Run the checks on `stored` (a version's stored document) in the sandbox
    behind `ops`. Returns (result, {theme: png}). Never raises: a failure to
    run is an `error` result (not_checked)."""
    from app.gateway.code_jobs.app_mode import read_png

    document = frame.frame_document(stored)
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
        csp = frame.CSP
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
                    png = read_png(ops, f"{directory}/{shot['file']}")
                except Exception:  # noqa: BLE001 - a screenshot is shown, never evidence
                    png = None
                if png:
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
        return [f"System checks passed (layout at {widths} px in light and dark, no network, it renders)."]
    if state == "failed":
        return ["System checks FAILED: " + "; ".join(result.get("summary") or ["see the details"]) + "."]
    return ["System checks gave no answer: " + "; ".join(result.get("summary") or ["the checks did not run"]) + ". The version is not shown as checked."]
