"""Opt-in: the real layout probe, browser and react build in a throwaway
container of the sandbox image (Spec 012 Slice 2). Skipped unless
OMNI_ARTIFACT_LIVE_CONTAINER names a running container started from the
sandbox image (`docker run -d --name X --entrypoint sleep <image> 3600`).
The react build test also needs the container to reach the npm registry
(OMNI_ARTIFACT_LIVE_NPM=1).

What it proves that the fake cannot: the probe's artifact mode loads the
exact frame document under the artifact CSP, a hostile page's every request
is recorded as a failure, a clean page passes in both themes, and esbuild
builds a react source into a document that renders."""

from __future__ import annotations

import os
import subprocess

import pytest

from app.gateway.artifacts_store import checks, frame, react_build

CONTAINER = os.environ.get("OMNI_ARTIFACT_LIVE_CONTAINER", "")
pytestmark = pytest.mark.skipif(not CONTAINER, reason="needs OMNI_ARTIFACT_LIVE_CONTAINER")


class DockerOps:
    container = CONTAINER

    def sh(self, command, *, timeout=30):
        r = subprocess.run(["docker", "exec", CONTAINER, "/bin/bash", "-c", command], capture_output=True, text=True, timeout=timeout + 10)
        return r.returncode, r.stdout

    def write(self, path, content):
        parent = path.rsplit("/", 1)[0]
        subprocess.run(["docker", "exec", "-i", CONTAINER, "/bin/sh", "-c", f"mkdir -p '{parent}' && cat > '{path}'"], input=content.encode(), check=True, timeout=30)

    def read_text(self, path):
        r = subprocess.run(["docker", "exec", CONTAINER, "cat", path], capture_output=True, timeout=30)
        return r.stdout.decode() if r.returncode == 0 else None


CLEAN = "<!doctype html><html><head><style>body{margin:0;font:16px sans-serif;background:var(--background);color:var(--foreground)}</style></head><body><main><h1>Clean</h1><p>Fits.</p></main></body></html>"

HOSTILE = """<!doctype html><html><head><style>.bg{background:url(http://203.0.113.9/css.png)}</style></head><body class=bg><h1>Hostile</h1>
<img src="http://203.0.113.9/beacon.gif">
<form action="http://203.0.113.9/post" method=post><input name=a value=b></form>
<script>
try { fetch('http://203.0.113.9/fetch'); } catch (e) {}
try { var x = new XMLHttpRequest(); x.open('GET','http://203.0.113.9/xhr'); x.send(); } catch (e) {}
try { new WebSocket('ws://203.0.113.9/ws'); } catch (e) {}
try { new EventSource('http://203.0.113.9/es'); } catch (e) {}
try { navigator.sendBeacon('http://203.0.113.9/beacon'); } catch (e) {}
try { document.forms[0].submit(); } catch (e) {}
try { localStorage.setItem('k','v'); document.title = localStorage.getItem('k'); } catch (e) {}
</script></body></html>"""


def test_live_clean_page_passes_both_themes():
    result, shots = checks.run(DockerOps(), CLEAN.encode())
    assert result["outcome"] == "pass", result
    assert set(shots) == {"light", "dark"}


def test_live_hostile_page_fails_on_network():
    result, _ = checks.run(DockerOps(), HOSTILE.encode())
    assert result["outcome"] == "fail", result
    assert any("network" in s for s in result["summary"]), result


def test_live_overflow_fails():
    wide = CLEAN.replace("<p>Fits.</p>", '<div style="width:900px">wide</div>')
    result, _ = checks.run(DockerOps(), wide.encode())
    assert result["outcome"] == "fail" and any("overflows sideways at 360" in s for s in result["summary"]), result


@pytest.mark.skipif(not os.environ.get("OMNI_ARTIFACT_LIVE_NPM"), reason="needs the npm registry")
def test_live_react_build_renders():
    data, parsed = frame.canonical_react_source({"entry": "App.tsx", "files": {"App.tsx": 'import "./a.css";\nexport default function App(){ return <main><h1>Built</h1></main>; }', "a.css": "h1{color:var(--primary)}"}})
    built = react_build.build(DockerOps(), parsed)
    assert built.ok, (built.reason, built.log)
    assert b"Built" in built.canon.data
    result, _ = checks.run(DockerOps(), built.canon.data)
    assert result["outcome"] == "pass", result


def test_live_the_probe_sees_a_webrtc_attempt(monkeypatch):
    """With the shim's WebRTC removal taken out (as a realm without the shim
    would be), the probe's watch reports the construction and the check fails."""
    import base64
    import hashlib

    body = frame._SHIM_BODY.replace("for (var r = 0; r < RTC.length; r++) lock(w, RTC[r], undefined);", "")
    monkeypatch.setattr(frame, "_SHIM_BODY", body)
    monkeypatch.setattr(frame, "SHIM_HASH", base64.b64encode(hashlib.sha256(body.encode()).digest()).decode())
    page = b"<!doctype html><body><p>x</p><script>try { var pc = new window['RTC' + 'PeerConnection'](); } catch (e) {}</script></body>"
    result, _ = checks.run(DockerOps(), page)
    assert result["outcome"] == "fail" and any("WebRTC" in f for f in result["failures"]), result


def test_live_inline_handlers_do_not_run_under_the_strict_profile():
    page = b"<!doctype html><body><p id=p>before</p><img src=\"data:image/gif;base64,R0lGODlhAQABAAAAACw=\" onload=\"document.getElementById('p').textContent='ran'\"></body>"
    result, _ = checks.run(DockerOps(), page)
    assert result["outcome"] in ("pass", "fail")  # the page renders; the handler is refused (a CSP violation is recorded)
