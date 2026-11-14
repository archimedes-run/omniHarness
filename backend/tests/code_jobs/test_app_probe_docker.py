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
    "overflow": (None, ".omni-page { min-width: 900px; }", "overflows sideways at 360 px"),
    "clipped_chart": (("x: Math.max(0, x0),", "x: Math.max(0, x0) + 200,"), ".load-chart { overflow: hidden; }", "chart clipped: svg.omni-chart.load-chart"),
    "missing_state": (('result.state === "empty" ? tile.empty : words.label', "tile.empty"), None, 'failed state: says "Nothing today"'),
    "low_contrast": (None, ".omni-list-main { color: #c8c8c8; }", "text below AA contrast in light"),
    "uses_fetch": (("// A small app", 'fetch("https://example.com/x").catch(() => {});\n// A small app'), None, "the page tried a network request"),
    "uses_innerhtml": (("// A small app", 'document.getElementById("clock").innerHTML = "<b>now</b>";\n// A small app'), None, "HTML or script from a string (Trusted Types)"),
    "has_iframe": (("// A small app", 'document.body.appendChild(document.createElement("iframe"));\n// A small app'), None, "the page has a nested frame or embedded object"),
}


def _site(root: Path, name: str, js_change, css_change, prod_js_change=None) -> list[str]:
    files = {n: (FIXTURE / n).read_bytes() for n in ("index.html", "app.js", "app.css")}
    files["graphite.css"] = app_kit.graphite_css().encode()
    if js_change:
        old, new = js_change
        assert old.encode() in files["app.js"], name
        files["app.js"] = files["app.js"].replace(old.encode(), new.encode())
    if css_change:
        files["app.css"] += b"\n" + css_change.encode()
    manifest = app_kit.read_manifest((FIXTURE / "omni-app.json").read_text())
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
    (d / "check.json").write_text(json.dumps({"csp": app_checks.probe_csp(hashes), "csp_site": app_checks.probe_csp(site_hashes), "sentinels": app_kit.sentinels(data), "reason": app_kit.MOCK_REASON}))
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
    os.chmod(root, 0o777)
    for d in root.rglob("*"):
        os.chmod(d, 0o777)
    loop = "for d in /w/*/; do cd $d && /usr/bin/timeout -k 5 170 /usr/bin/python3.10 -I -S layout_probe.py $d/www $d/result.json app < /dev/null > /dev/null 2>&1; rc=$?; echo $(basename $d) $rc; done"
    name = f"oh-app-probe-e2e-{uuid.uuid4().hex[:8]}"
    try:
        run = subprocess.run(
            ["docker", "run", "--rm", "--name", name, "--network", "none", "--user", "1000:1000", "--entrypoint", "/bin/bash", "-v", f"{root}:/w", IMAGE, "-c", loop],
            capture_output=True,
            text=True,
            timeout=1500,
        )
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    assert run.returncode == 0, run.stderr[-2000:]
    codes = dict(line.split() for line in run.stdout.split("\n") if line.strip())
    results = {}
    for d in root.iterdir():
        raw = (d / "result.json").read_text() if (d / "result.json").exists() else None
        results[d.name] = app_checks.parse(raw, exit_code=int(codes.get(d.name, "0")), data_sources=sources)
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
    for name, (_js, _css, why) in BROKEN.items():
        r = results[name]
        assert r["outcome"] == "fail" and any(why in f for f in r["failures"]), (name, r["failures"], r.get("error"))
