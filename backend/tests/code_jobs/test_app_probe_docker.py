"""The app probe in the real sandbox image (Spec 011 FR-026): the gateway's own
pipeline builds each fixture's mock document exactly as a job does (inline,
mock shim and sample data first, the app CSP with Trusted Types), and the
probe (layout_probe.py in app mode, the image's root-owned Python and
browser, no network) checks it. A fixture app that follows the rules passes;
each broken copy of it must fail for its own reason.

Needs Docker and the sandbox image (no download): OMNI_APP_PROBE_DOCKER_E2E=1,
SANDBOX_IMAGE (default omni-harness-sandbox:1.11.0-oh5).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from app.gateway.apps import bundle as bundle_mod
from app.gateway.code_jobs import app_checks, app_kit, layout

from .test_app_mode import app_result as app_result_json

FIXTURE = Path(__file__).with_name("app_fixtures") / "pass"
IMAGE = os.environ.get("SANDBOX_IMAGE", "omni-harness-sandbox:1.11.0-oh5")

#: name -> (change to app.js, change to app.css, a failure that must be listed)
BROKEN: dict[str, tuple] = {
    "wrong_time_zone": (None, None, "the event 'Team standup' shows 2:30 PM; expected 9:30 AM (America/New_York"),
    "cut_title": (None, ".omni-list-main { max-width: 12px; }", "a row's title is cut to almost nothing"),
    "chart_label_spill": (
        ('class: "omni-series" }));', 'class: "omni-series" }));\n    const lbl = svg("text", { x: Math.max(0, x0) + 1, y: 26 }); lbl.textContent = item.title || ""; chart.appendChild(lbl);'),
        None,
        "chart label overflows its block",
    ),
    "few_items": (
        ('for (const item of data.items || []) {\n    const li = el("li");\n    const a = el(', 'for (const item of (data.items || []).slice(0, 1)) {\n    const li = el("li");\n    const a = el('),
        None,
        "a tile shows fewer than half of its sample items (source gh_review)",
    ),
    "overflow": (None, ".omni-page { min-width: 900px; }", "overflows sideways at 360 px"),
    "clipped_chart": (("x: Math.max(0, x0),", "x: Math.max(0, x0) + 200,"), ".load-chart { overflow: hidden; }", "chart clipped: svg.omni-chart.load-chart"),
    "missing_state": (('result.state === "empty" ? tile.empty : words.label', "tile.empty"), None, 'failed state: says "Nothing today"'),
    "low_contrast": (None, ".omni-list-main { color: #c8c8c8; }", "text below AA contrast in light"),
    "uses_fetch": (("// A small app", 'fetch("https://example.com/x").catch(() => {});\n// A small app'), None, "the page tried a network request"),
    "uses_innerhtml": (("// A small app", 'document.getElementById("clock").innerHTML = "<b>now</b>";\n// A small app'), None, "HTML or script from a string (Trusted Types)"),
    "has_iframe": (("// A small app", 'document.body.appendChild(document.createElement("iframe"));\n// A small app'), None, "the page has a nested frame or embedded object"),
}


#: A correct New York app whose chart holds each event's title (an SVG
#: <title>) beside hour labels that read "19:00": text inside a chart is
#: never taken as an event's shown time.
CHART_TITLES_NY = [
    ("d.toISOString().slice(11, 16)", 'new Intl.DateTimeFormat("en-GB", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(d)'),
    ('class: "omni-series" }));', 'class: "omni-series" })).appendChild(svg("title")).textContent = item.title || "";'),
    ('[["08", 0], ["13", 120], ["18", 240]]', '[["09:00", 0], ["12:00", 120], ["19:00", 240]]'),
    ("    t.textContent = h;", '    t.textContent = h + " ";'),
    ("const x0 = ((s.getUTCHours()", "const x0 = ((s.getUTCHours() - 5"),
    ("const x1 = ((e.getUTCHours()", "const x1 = ((e.getUTCHours() - 5"),
]
TIMES: dict[str, dict] = {}
FRONTEND = Path(__file__).resolve().parents[3] / "frontend"
#: The kit's own starter must pass its own checks in each of these zones.
STARTER_ZONES = ("America/New_York", "Europe/Berlin", "Asia/Kolkata", "UTC")
STARTER_SOURCES = ["calendar", "gh_review", "inbox", "ledger"]


def _counts(data: dict) -> dict:
    return {n: len(f["fresh"].get("items") or []) for n, f in data["sources"].items()}


COUNTS: dict[str, dict] = {}


def _site(root: Path, name: str, js_change, css_change, prod_js_change=None) -> list[str]:
    files = {n: (FIXTURE / n).read_bytes() for n in ("index.html", "app.js", "app.css")}
    files["graphite.css"] = app_kit.graphite_css().encode()
    for old, new in [js_change] if isinstance(js_change, tuple) else js_change or []:
        assert old.encode() in files["app.js"], name
        files["app.js"] = files["app.js"].replace(old.encode(), new.encode())
    if css_change:
        files["app.css"] += b"\n" + css_change.encode()
    raw = json.loads((FIXTURE / "omni-app.json").read_text())
    if name in ("wrong_time_zone", "chart_titles_ny"):
        raw["sources"]["calendar"]["params"] = {"tz": "America/New_York"}
    manifest = app_kit.read_manifest(json.dumps(raw))
    return _write_case(root, name, files, manifest, prod_js_change)


#: Changes to the kit for starter cases: (old, new) in omni-react.tsx.
KIT_CHANGES = {
    # A broken kit: event times formatted in UTC, the rest unchanged.
    "utc-rows": ('const time = new Intl.DateTimeFormat("en-US", { timeZone: tz,', 'const time = new Intl.DateTimeFormat("en-US", { timeZone: "UTC",'),
    # A correct app whose hour axis reads "19:00": in New York that is also
    # 14:00 in UTC, which a page-wide search took for a wrong-zone time.
    "axis-24h": ('            {h % 12 || 12}\n            {h < 12 ? "a" : "p"}\n', "            {`${h}:00`}\n"),
}


def _starter_site(root: Path, tz: str, kit_change: str | None = None) -> str:
    """The kit's starter for a Today app in *tz*, built as a job builds it
    (the kit files written, the starter copied to src/), bundled without a
    download, then checked like any app."""
    manifest = app_kit.manifest_from_spec({"name": "Today", "sources": STARTER_SOURCES, "timezone": tz})
    project = root.parent / f"proj-{tz.replace('/', '-')}"
    suffix = f"-{kit_change}" if kit_change else ""
    project = project.with_name(project.name + suffix)
    for rel, content in app_kit.kit_files(manifest).items():
        if kit_change and rel == "omni-kit/omni-react.tsx":
            old, new = KIT_CHANGES[kit_change]
            assert old in content, kit_change
            content = content.replace(old, new)
        (project / rel).parent.mkdir(parents=True, exist_ok=True)
        (project / rel).write_text(content)
    (project / "src").mkdir()
    for n in ("App.tsx", "main.tsx"):
        shutil.copy(project / "omni-kit" / "starter" / n, project / "src" / n)
    subprocess.run(["node", str(FIXTURE.with_name("bundle_starter.mjs")), str(project), str(FRONTEND), str(project / "app.js")], check=True, timeout=120)
    files = {
        "index.html": (
            b'<!doctype html><html lang="en"><head><meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" />'
            b'<title>Today</title><link rel="stylesheet" href="./graphite.css" /></head><body><div id="root"></div><script src="./app.js"></script></body></html>'
        ),
        "app.js": (project / "app.js").read_bytes(),
        "graphite.css": app_kit.graphite_css().encode(),
    }
    name = "starter-" + tz.replace("/", "-") + suffix
    _write_case(root, name, files, manifest)
    return name


def _write_case(root: Path, name: str, files: dict, manifest: dict, prod_js_change=None) -> list[str]:
    html, _ = bundle_mod.inline(files)
    data = app_kit.fixtures(manifest)
    mock, hashes = bundle_mod.inline({"index.html": html}, platform_shim=app_kit.mock_script(data))
    d = root / name
    for part in ("site", "prod"):
        (d / "www" / part).mkdir(parents=True)
        (d / "www" / part / "index.html").write_bytes(mock)
    site_hashes = hashes
    if prod_js_change:
        # Only the production bytes differ (a development-only guard in the app).
        files["app.js"] = files["app.js"].replace(prod_js_change[0].encode(), prod_js_change[1].encode())
        bad, bad_hashes = bundle_mod.inline({"index.html": bundle_mod.inline(files)[0]}, platform_shim=app_kit.mock_script(data))
        (d / "www" / "prod" / "index.html").write_bytes(bad)
        hashes = bad_hashes
    (d / "check.json").write_text(
        json.dumps(
            {
                "csp": app_checks.probe_csp(hashes),
                "csp_site": app_checks.probe_csp(site_hashes),
                "sentinels": app_kit.sentinels(data),
                "times": app_kit.expected_times(data),
                "counts": {n: len(f["fresh"].get("items") or []) for n, f in data["sources"].items()},
                "reason": app_kit.MOCK_REASON,
            }
        )
    )
    TIMES[name] = app_kit.expected_times(data)
    COUNTS[name] = {n: len(f["fresh"].get("items") or []) for n, f in data["sources"].items()}
    shutil.copy(Path(layout.__file__).with_name("layout_probe.py"), d / "layout_probe.py")
    return list(manifest["sources"])


@pytest.mark.skipif(os.environ.get("OMNI_APP_PROBE_DOCKER_E2E") != "1", reason="needs Docker and the sandbox image: OMNI_APP_PROBE_DOCKER_E2E=1")
def test_the_app_probe_passes_a_good_app_and_fails_each_broken_copy(tmp_path) -> None:
    root = tmp_path / "probe"
    root.mkdir()
    sources = _site(root, "pass", None, None)
    for name, (js, css, _why) in BROKEN.items():
        _site(root, name, js, css)
    # Network and a frame only in the production build: caught there.
    _site(root, "prod_only_violation", None, None, ("// A small app", 'fetch("https://example.com/x").catch(() => {});\ndocument.body.appendChild(document.createElement("iframe"));\n// A small app'))
    # A result already in the probe's folder: the probe refuses to run.
    _site(root, "pre_written", None, None)
    (root / "pre_written" / "result.json").write_text(app_result_json())
    _site(root, "chart_titles_ny", CHART_TITLES_NY, None)
    starters = [_starter_site(root, tz) for tz in STARTER_ZONES]
    starters.append(_starter_site(root, "America/New_York", "axis-24h"))
    utc_rows = _starter_site(root, "America/New_York", "utc-rows")
    os.chmod(root, 0o777)
    for d in root.rglob("*"):
        os.chmod(d, 0o777)
    # Four containers side by side: the whole set stays well inside the
    # suite's per-test time limit.
    names = sorted(d.name for d in root.iterdir() if (d / "check.json").exists())
    procs, containers = [], []
    try:
        for part in range(4):
            dirs = " ".join(f"/w/{n}" for n in names[part::4])
            loop = f"for d in {dirs}; do cd $d && /usr/bin/timeout -k 5 170 /usr/bin/python3.10 -I -S layout_probe.py $d/www $d/result.json app < /dev/null > /dev/null 2>&1; rc=$?; echo $(basename $d) $rc; done"
            name = f"oh-app-probe-e2e-{uuid.uuid4().hex[:8]}"
            containers.append(name)
            cmd = ["docker", "run", "--rm", "--name", name, "--network", "none", "--user", "1000:1000", "--entrypoint", "/bin/bash", "-v", f"{root}:/w", IMAGE, "-c", loop]
            procs.append(subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
        outs = [p.communicate(timeout=900) for p in procs]
    finally:
        for name in containers:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    assert all(p.returncode == 0 for p in procs), [o[1][-500:] for o in outs]

    class run:  # noqa: N801 - the joined output, read below
        stdout = "".join(o[0] for o in outs)

    codes = dict(line.split() for line in run.stdout.split("\n") if line.strip())
    results = {}
    for n in names:
        d = root / n
        raw = (d / "result.json").read_text() if (d / "result.json").exists() else None
        srcs = STARTER_SOURCES if n.startswith("starter-") else sources
        results[n] = app_checks.parse(raw, exit_code=int(codes.get(n, "0")), data_sources=srcs, item_counts=COUNTS.get(n), time_events=TIMES.get(n))
    assert results["pre_written"]["error_code"] == "tampered"
    bad = results["prod_only_violation"]
    assert bad["outcome"] == "fail" and any("production/" in f and "connect-src" in f for f in bad["failures"]), bad["failures"]
    assert any("nested frame" in f and "production/" in f for f in bad["failures"])

    good = results["pass"]
    assert good["outcome"] == "pass", good["failures"]
    assert len(good["shots"]) == 6
    for shot in good["shots"]:
        assert (root / "pass" / shot["file"]).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert not good["errors_detail"]
    crash = results["uses_innerhtml"]["errors_detail"]
    assert crash and "TrustedHTML" in crash[0]["message"] and crash[0]["frames"]
    for name in [*starters, "chart_titles_ny"]:
        r = results[name]
        assert r["outcome"] == "pass", (name, r["failures"], r.get("error"))
    # The kit's marked event times, read and compared per event: a kit that
    # formats them in UTC fails, naming the event.
    r = results[utc_rows]
    assert r["outcome"] == "fail" and any(f.startswith("the event 'Team standup' shows 2:30 PM; expected 9:30 AM (America/New_York") for f in r["failures"]), (r["failures"], r.get("error"))
    for name, (_js, _css, why) in BROKEN.items():
        r = results[name]
        assert r["outcome"] == "fail" and any(why in f for f in r["failures"]), (name, r["failures"], r.get("error"))
