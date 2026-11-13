"""The layout check of a coding job's web app (spec 009): run by the gateway
after a passing build, before the app is published.

Every app made here is responsive by default (the worker's rules say so);
this checks it instead of trusting it. The gateway writes `layout_probe.py`
into the sandbox, runs it only if its checksum is the one computed here,
with the image's root-owned Python and browser (not tools the worker could
have replaced), and reads back one small JSON file, which `parse` checks
strictly. The page under test is the worker's code: it runs as the sandbox
user with the network closed, can reach only the check's own local server,
and can make the check fail or time out, nothing more. Its strings (element
names, an error message) are shown as page text, never as instructions.

What it checks at 360, 560 and 1280 px:
  * no sideways page overflow (documentElement.scrollWidth <= clientWidth + 1);
  * no chart cut off by its own <svg> box (drawn shapes past the box by more
    than max(6 px, 4 %); text alone only warns);
  * the page loaded, rendered something, and threw no uncaught error.
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
from pathlib import Path

WIDTHS = (360, 560, 1280)
#: The probe's own budget is 38 s; this is the hard stop around it.
TIMEOUT_SECONDS = 45
PYTHON = "/usr/bin/python3.10"
SCRIPT = Path(__file__).with_name("layout_probe.py").read_text(encoding="utf-8")
DIGEST = hashlib.sha256(SCRIPT.encode()).hexdigest()
MAX_RESULT_CHARS = 65536
MAX_FAILURES = 8
MAX_WARNINGS = 5
_WHERE = re.compile(r"[^A-Za-z0-9_#.\- ]")


def command(directory: str, root: str, job_id: str, path_env: str) -> str:
    """The shell command that runs the probe from `directory` (fresh, the
    system's own) against the site in `root`. No proxy variables: the page
    gets no way out of the sandbox."""
    q = shlex.quote
    script, out = f"{directory}/layout_probe.py", f"{directory}/result.json"
    return (
        f'f={q(script)}; [ "$(sha256sum "$f" | cut -c1-64)" = {DIGEST} ] || exit 97; '
        f"cd {q(directory)} && env -i {path_env} HOME={q(directory)} TMPDIR={q(directory)} OMNI_JOB_ID={q(job_id)} "
        f'timeout -k 5 {TIMEOUT_SECONDS} {PYTHON} -I -S "$f" {q(root)} {q(out)} < /dev/null > /dev/null 2>&1'
    )


def _text(value, n: int) -> str:
    text = value if isinstance(value, str) else ""
    return "".join(c if c.isprintable() else " " for c in text)[:n].strip()


def _where(value) -> str:
    return _WHERE.sub("", _text(value, 120))[:100] or "svg"


def _int(value, limit: int = 1_000_000) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 <= value <= limit else None


def _widths(ws: list[int]) -> str:
    return ", ".join(str(w) for w in ws) + " px"


def parse(raw: str | None, *, exit_code: int | None, mode: str, seconds: float = 0.0) -> dict:
    """The probe's result file, checked field by field. `outcome` is
    `pass`, `fail` (the page's fault: counted unless the mode is `warn`) or
    `error` (the check itself could not run: never counted, always shown)."""
    # `summary` holds the failures in the system's own words only (no text
    # from the page): it becomes the job's reason, which is not fenced.
    base = {"widths": list(WIDTHS), "mode": mode, "seconds": round(seconds, 1), "failures": [], "summary": [], "warnings": [], "error": None}

    def error(why: str) -> dict:
        return {**base, "outcome": "error", "error": why}

    def fail(why: str) -> dict:
        return {**base, "outcome": "fail", "failures": [why], "summary": [why]}

    if exit_code == 97:
        return error("the check script did not match its checksum")
    data = None
    if raw is not None and len(raw) <= MAX_RESULT_CHARS:
        try:
            data = json.loads(raw)
        except ValueError:
            data = None
    if raw is None or not isinstance(data, dict) or data.get("v") != 1:
        if exit_code in (124, 137):
            return fail(f"the page kept the browser busy past the check's {TIMEOUT_SECONDS} s limit")
        return error("the check left no readable result" if exit_code is not None else "the sandbox did not answer")
    if data.get("setup_error") is not None:
        return error(_text(data.get("setup_error"), 160) or "the check could not start")
    pages = data.get("pages")
    if not isinstance(pages, list) or len(pages) > len(WIDTHS):
        return error("the check left no readable result")

    failures: list[str] = []
    summary: list[str] = []
    warnings: list[str] = []
    # Repeated findings (the same chart, the same error) are listed once, with their widths.
    clipped: dict[str, list] = {}
    labels: dict[str, list] = {}
    errors: dict[str, list[int]] = {}
    blank: list[int] = []
    for i, page in enumerate(pages):
        width = WIDTHS[i]
        if not isinstance(page, dict) or page.get("width") != width:
            return error("the check left no readable result")
        if page.get("crashed") is True:
            failures.append(f"the page crashed the browser at {width} px")
            summary.append(failures[-1])
            continue
        if page.get("loaded") is not True:
            failures.append(f"did not load at {width} px ({_text(page.get('load_error'), 80) or 'no reason given'})")
            summary.append(f"did not load at {width} px")
            continue
        overflow, client = _int(page.get("overflow_px")), _int(page.get("client_width"), 100_000)
        offenders = page.get("offenders")
        svgs = page.get("svgs")
        if overflow is None or client is None or not isinstance(page.get("rendered"), bool) or not isinstance(offenders, list) or not isinstance(svgs, list):
            return error("the check left no readable result")
        count = _int(page.get("errors")) or 0
        if count:
            errors.setdefault(_text(page.get("first_error"), 160) or "an error", []).append(width)
        if not page["rendered"]:
            blank.append(width)
        if overflow > 1:
            names = [_where(o) for o in offenders[:3] if isinstance(o, str)]
            summary.append(f"overflows sideways at {width} px by {overflow} px")
            failures.append(summary[-1] + (f" (sticking out: {', '.join(names)})" if names else ""))
        for svg in svgs[:5]:
            if not isinstance(svg, dict) or _int(svg.get("px")) is None or svg.get("side") not in ("left", "right", "top", "bottom"):
                continue
            entry = (svg["side"], svg["px"])
            bucket = labels if svg.get("kind") == "text" else clipped
            found = bucket.setdefault(_where(svg.get("where")), [entry, []])
            found[0] = max(found[0], entry, key=lambda e: e[1])
            found[1].append(width)
    if blank:
        failures.append(f"rendered nothing at {_widths(blank)}")
        summary.append(failures[-1])
    for message, ws in errors.items():
        failures.append(f"uncaught error on load at {_widths(ws)}: {message}")
        summary.append(f"uncaught error on load at {_widths(ws)}")
    for where, ((side, px), ws) in clipped.items():
        failures.append(f"chart clipped: {where} (cut off {px} px on the {side}) at {_widths(ws)}")
        summary.append(f"a chart is cut off by {px} px at {_widths(ws)}")
    for where, ((side, px), ws) in labels.items():
        warnings.append(f"chart labels may be cut: {where} ({px} px past the {side}) at {_widths(ws)}")
    if len(pages) < len(WIDTHS):
        missing = WIDTHS[len(pages)]
        if data.get("timed_out") is True:
            failures.append(f"the page kept the browser busy past the check's time limit (at {missing} px)")
        elif data.get("browser_exit") is True:
            failures.append(f"the browser closed while loading the page (at {missing} px)")
        else:
            return error("the check left no readable result")
        summary.append(failures[-1])
    return {**base, "outcome": "fail" if failures else "pass", "failures": failures[:MAX_FAILURES], "summary": summary[:MAX_FAILURES], "warnings": warnings[:MAX_WARNINGS]}


def counts_against(layout: dict | None) -> bool:
    """A failed check stops `verified` unless config says `warn`."""
    return bool(layout) and layout.get("outcome") == "fail" and layout.get("mode") == "enforce"


def reason(layout: dict) -> str:
    """The job's reason: the system's words only (the page's text stays in
    the fenced failure list)."""
    items = layout.get("summary") or []
    shown = "; ".join(items[:3])
    more = len(items) - 3
    return "the layout check failed: " + shown + (f"; and {more} more" if more > 0 else "")


def report_lines(layout: dict, fenced) -> list[str]:
    """The lead's report. Element names and error text come from the page
    (the worker's code): fenced as data."""
    head = f"- Layout check (a headless browser at {' / '.join(str(w) for w in WIDTHS)} px, run by the system):"
    outcome = layout.get("outcome")
    if outcome == "error":
        return [f"{head} could not run ({layout.get('error')}); not counted either way."]
    lines: list[str] = []
    if outcome == "pass":
        lines.append(f"{head} the page fits at every width.")
    else:
        counted = "counted: the result is not verified" if layout.get("mode") == "enforce" else "NOT counted (config: code_jobs.layout_check = warn)"
        lines.append(f"{head} FAILED, {counted}. Failures (element names and error text come from the page):")
        lines += fenced("LAYOUT FAILURES", "\n".join(layout.get("failures", [])))
    if layout.get("warnings"):
        lines.append("  Warnings (not counted):")
        lines += fenced("LAYOUT WARNINGS", "\n".join(layout["warnings"]))
    return lines
