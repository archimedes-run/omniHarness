"""Code kinds in the locked frame (Spec 012 Slice 2: FR-016 to FR-019, FR-029 to FR-031).

Builds and checks run through the real gateway code against a fake sandbox
(fake_sandbox.py); every assertion reads state back from the store. The
browser side (the frame's isolation, the hostile suite, the UDP listener)
is in frontend/tests/rendering/artifacts-frame*.spec.ts."""

from __future__ import annotations

import json
import re

import pytest
from fake_sandbox import PNG, FakeSandbox, failing, page, passing
from langchain_core.messages import AIMessage, ToolMessage

from app.gateway.apps import bundle
from app.gateway.artifacts_store import blobs, caps, checks, code_service, frame, react_build
from app.gateway.artifacts_store.kinds import InvalidContent, TooLarge
from app.gateway.artifacts_store.service import FENCE_LABEL, GatewayArtifactController
from app.gateway.artifacts_store.store import FixRefused
from app.policy.lineage import user_turn
from omniharness.runtime.artifacts.controller import MESSAGES_KEY, TOOL_CALL_KEY

OWNER = "owner-1"
PAGE = "<!doctype html><html><head><style>body{margin:0}</style></head><body><main><h1>Hello</h1></main><script>document.querySelector('h1').onclick=()=>{}</script></body></html>"
REACT = {"entry": "App.tsx", "files": {"App.tsx": "export default function App(){ return <h1>Hi</h1>; }", "styles.css": "h1{color:var(--foreground)}"}}

APP_TEMPLATE_EXACT = (
    "sandbox allow-scripts; default-src 'none'; script-src {scripts}; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; "
    "media-src 'none'; connect-src 'none'; frame-src 'none'; child-src 'none'; worker-src 'none'; object-src 'none'; manifest-src 'none'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'self'; require-trusted-types-for 'script'; trusted-types 'none'"
)


def ctx(messages=None, **extra):
    msgs = messages if messages is not None else [user_turn("make a page"), AIMessage(content="", tool_calls=[{"name": "artifact_create", "args": {}, "id": "c1"}])]
    return {"user_id": OWNER, "thread_id": "thread-a", "run_id": "run-1", MESSAGES_KEY: msgs, TOOL_CALL_KEY: "c1", **extra}


@pytest.fixture
def sandbox(monkeypatch):
    box = {"ops": FakeSandbox()}
    monkeypatch.setattr(code_service, "sandbox_factory", lambda thread_id, owner_id: box["ops"])
    return box


@pytest.fixture
def tools(store):
    return GatewayArtifactController(lambda: store)


def create(tools, kind="html", content=PAGE, **kw):
    return tools.create(ctx(kw.pop("messages", None)), kind=kind, title=kw.pop("title", "Page"), content=content, language=None, source_path=None, note=None)


def update(tools, aid, base, content=None, edits=None, fix_of=None, messages=None):
    return tools.update(ctx(messages), artifact_id=aid, base_version=base, content=content, edits=edits, language=None, note=None, fix_of=fix_of)


# -- the frame profile (FR-016, FR-031) ------------------------------------------------


def test_the_frame_has_the_apps_profile_exactly():
    doc, hashes = frame.frame_document(PAGE.encode())
    assert frame.csp(hashes) == bundle.csp(hashes) == APP_TEMPLATE_EXACT.format(scripts=" ".join(f"'sha256-{h}'" for h in hashes))
    assert frame.PROFILE["csp_template"] == bundle.CSP_TEMPLATE == APP_TEMPLATE_EXACT
    policy = frame.csp(hashes)
    assert "'unsafe-inline'" not in policy.split("script-src", 1)[1].split(";", 1)[0]
    assert "require-trusted-types-for 'script'; trusted-types 'none'" in policy
    assert frame.PROFILE["sandbox"] == "allow-scripts"
    assert frame.HEADERS == {
        "Cache-Control": "private, no-store",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "Cross-Origin-Resource-Policy": "same-origin",
        "Cross-Origin-Opener-Policy": "same-origin",
        "X-DNS-Prefetch-Control": "off",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=(), clipboard-read=(), clipboard-write=()",
        "Content-Disposition": 'inline; filename="artifact.html"',
    }


def test_the_shim_is_prepended_as_the_first_bytes_after_the_doctype():
    doc, hashes = frame.frame_document(PAGE.encode())
    assert doc.decode().startswith("<!doctype html><script>" + frame.SHIM.replace("</script", "<\\/script")[:120])
    assert hashes[0] == frame.SHIM_HASH
    bare, _ = frame.frame_document(b"<p>no doctype</p><script>1</script>")
    assert bare.decode().startswith("<script>")
    assert frame.frame_sha256(PAGE.encode()) == frame.frame_sha256(PAGE.encode())


@pytest.mark.parametrize(
    "html, hidden",
    [
        # A comment the gateway's tokenizer reads as open and the browser as closed.
        ("<!doctype html><!--><script>window.__P=window['RTC'+'PeerConnection']</script><!-- --><p>x</p>", "window.__P=window['RTC'+'PeerConnection']"),
        ("<!doctype html><!---><script>window.__P=1</script><!-- --><p>x</p>", "window.__P=1"),
        ("<!doctype html><!--!><script>window.__P=2</script>--><p>x</p>", None),
        # A visible script later: a parser-placed shim would land after the hidden one.
        ("<!doctype html><!--><script>window.__P=3</script><!-- --><p>x</p><script>var ok = 1</script>", "window.__P=3"),
    ],
)
def test_a_script_hidden_from_the_tokenizer_gets_no_hash_and_the_shim_still_comes_first(html, hidden):
    """Whatever a parser makes of a comment, the shim is the first script: it
    is prepended, not placed by parsing. A script the gateway's parser does
    not see has no hash (it does not run); one it sees runs after the shim."""
    doc, hashes = frame.frame_document(html.encode())
    assert doc.decode().index("<script>") == len("<!doctype html>")
    assert hashes[0] == frame.SHIM_HASH


def test_the_shim_is_first_even_without_a_doctype_and_with_a_head():
    doc, _ = frame.frame_document(b"<html><head><title>t</title></head><body><script>var a = 1</script></body></html>")
    assert doc.decode().startswith("<script>")


def test_what_the_strict_profile_will_not_run_is_a_blocking_finding():
    html = '<!doctype html><button onclick="go()">x</button><a href="javascript:go()">y</a><script src="a.js"></script><script>el.innerHTML = s; eval("1")</script>'
    _, findings = frame.canonical_html(html)
    block = frame.blocking(findings)
    assert frame.HANDLER_WORDS in block and frame.JS_URL_WORDS in block and frame.SINK_WORDS in block and frame.STRING_CODE_WORDS in block and frame.SCRIPT_SRC_WORDS in block
    _, clean = frame.canonical_html(PAGE)
    assert frame.blocking(clean) == []


def test_a_blocking_finding_fails_the_check_with_its_reason(tools, store, sandbox):
    text, card = create(tools, content='<!doctype html><button onclick="go()">x</button>')
    info = store.get(OWNER, card["artifact_id"])["code"]
    assert info["check_state"] == "failed" and "System checks FAILED: will not run in the frame" in text and "fix_of=1" in text


# -- the scan (refusals and findings) ---------------------------------------------------


@pytest.mark.parametrize(
    "html",
    [
        "<html><body><iframe src='x'></iframe></body></html>",
        "<html><body><template><object data='x'></object></template></body></html>",
        "<html><body><script>d.srcdoc = '<b>x</b>'</script></body></html>",
        "<html><body><script>new RTCPeerConnection()</script></body></html>",
        "<html><body><script>new XSLTProcessor()</script></body></html>",
        "<html><body><script>x.innerHTML='<embed src=a>'</script></body></html>",
    ],
)
def test_ways_to_another_realm_are_refused(html):
    with pytest.raises(InvalidContent):
        frame.canonical_html(html)


def test_network_references_are_findings_not_refusals():
    html = (
        '<html><head><link rel="stylesheet" href="https://cdn.example/x.css"><style>@import url(https://x/y.css); b{background:url(https://x/i.png)}</style>'
        '<meta http-equiv="refresh" content="0;url=https://x"></head><body><img src="https://x/p.gif"><a href="https://ok.example">link</a>'
        "<script>fetch('https://x');new WebSocket('wss://x');navigator.sendBeacon('https://x')</script></body></html>"
    )
    canon, findings = frame.canonical_html(html)
    text = "\n".join(findings)
    assert canon.data == html.encode()
    for part in ("<link href>", "@import", "url()", "<meta http-equiv>", "<img src>", "WebSocket", "sendBeacon", "network requests"):
        assert part in text, part
    assert "<a href>" not in text  # links go through the host's dialog
    assert "cdn.example" not in text  # fixed words, never an echo


def test_html_caps_and_text_rules():
    with pytest.raises(TooLarge):
        frame.canonical_html("<p>" + "x" * caps.TEXT_VERSION_BYTES)
    for bad in ("a\x00b", "   ", 42):
        with pytest.raises(InvalidContent):
            frame.canonical_html(bad)


@pytest.mark.parametrize(
    "content",
    [
        {"entry": "App.tsx", "files": {"../App.tsx": "x"}},
        {"entry": "App.tsx", "files": {"/abs.tsx": "x"}},
        {"entry": "App.tsx", "files": {"App.tsx": "x", "__omni_entry.jsx": "y"}},
        {"entry": "App.tsx", "files": {"App.exe": "x"}},
        {"entry": "Missing.tsx", "files": {"App.tsx": "x"}},
        {"entry": "App.tsx", "files": {"App.tsx": "new RTCPeerConnection()"}},
        {"entry": "App.tsx", "files": {"App.tsx": "x", "b/c.tsx": 'import y from "../../../z"'}},
        {"entry": "App.tsx", "files": {f"f{i}.ts": "x" for i in range(51)}},
        {"entry": "App.tsx", "files": {}, "extra": 1},
    ],
)
def test_react_source_rules(content):
    with pytest.raises(InvalidContent):
        frame.canonical_react_source(content)


def test_react_source_is_canonical_json_and_capped():
    data, parsed = frame.canonical_react_source(REACT)
    assert json.loads(data) == parsed == REACT
    with pytest.raises(TooLarge):
        frame.canonical_react_source({"entry": "App.tsx", "files": {"App.tsx": "x" * (caps.REACT_SOURCE_BYTES + 1)}})


def test_react_output_is_inlined_locally_and_capped():
    canon, findings = frame.react_files_to_html(b'console.log("</script><b>")', b"body{color:red}")
    html = canon.data.decode()
    assert "<style>body{color:red}</style>" in html and "<\\/script>" in html and 'src="app.js"' not in html
    assert findings == []
    with pytest.raises(InvalidContent):
        frame.react_files_to_html(b"1", b"body{background:url(https://x/y.png)}")
    with pytest.raises(TooLarge):
        frame.react_files_to_html(b"x" * (caps.REACT_BUNDLE_BYTES + 1), None)


# -- the build output is read safely ----------------------------------------------------


def test_build_output_read_refuses_links_and_oversize(sandbox):
    ops = sandbox["ops"]
    ops.files["/b/app.js"] = "ok"
    assert react_build.read_bytes(ops, "/b/app.js", 10) == b"ok"
    ops.links.add("/b/app.js")
    assert react_build.read_bytes(ops, "/b/app.js", 10) is None
    ops.links.clear()
    ops.files["/b/app.js"] = "x" * 11
    assert react_build.read_bytes(ops, "/b/app.js", 10) is None


def test_build_output_that_grows_after_stat_is_refused(sandbox):
    ops = sandbox["ops"]
    ops.files["/b/app.js"] = "x" * 11
    ops.stat_size["/b/app.js"] = 5
    assert react_build.read_bytes(ops, "/b/app.js", 10) is None


def test_a_build_whose_output_is_a_link_fails_and_keeps_the_last_good_version(tools, store, sandbox):
    text, card = create(tools, "react", REACT)
    aid = card["artifact_id"]
    box = sandbox["ops"]
    real_sh = box.sh

    def sh(command, *, timeout=30):
        out = real_sh(command, timeout=timeout)
        if "npm ci " in command:
            box.links.update(k for k in box.files if k.endswith("/dist/app.js"))
        return out

    box.sh = sh
    text, card2 = update(tools, aid, 1, content=REACT)
    assert card2["version"] == 2 and "build FAILED" in text and "version 1 stays the one shown" in text
    summary = store.get(OWNER, aid)
    assert summary["code"]["build_state"] == "build_failed" and summary["code"]["shown_version"] == 1


def test_build_failure_stores_source_and_log(tools, store, sandbox):
    sandbox["ops"].build = lambda files: (1, {}, "src/App.tsx:1:10: ERROR: Expected ';'")
    text, card = create(tools, "react", REACT)
    summary, version, code, check = store.code_version(OWNER, card["artifact_id"], 1)
    assert code.build_state == "build_failed" and check is None
    assert json.loads(store.source(OWNER, code)) == REACT
    assert "Expected" in code.build_log and "Expected" not in text  # the compiler's words only through artifact_read
    assert "Run ONE automatic fix now" in text


# -- create, checks, fail closed --------------------------------------------------------


def test_html_create_runs_the_checks_on_the_exact_bytes(tools, store, sandbox):
    seen = {}

    def probe(check, doc):
        seen.update(check=check, doc=doc)
        return 0, passing(check, doc)

    sandbox["ops"].probe = probe
    text, card = create(tools)
    assert "System checks passed" in text
    _, version, code, check = store.code_version(OWNER, card["artifact_id"], 1)
    doc, hashes = frame.frame_document(PAGE.encode())
    assert seen["doc"].encode() == doc
    assert seen["check"]["csp"] == frame.csp(hashes) and re.fullmatch(r"[0-9a-f]{32}", seen["check"]["nonce"])
    # The checks never stop the sandbox's other processes (a preview server,
    # a coding job, the model's own background work).
    assert not any(re.search(r"\bkill\b|pkill|killall", c) for c in sandbox["ops"].commands)
    assert check.state == "passed" and check.frame_sha256 == code.frame_sha256 == frame.frame_sha256(PAGE.encode())
    assert store.shot(OWNER, card["artifact_id"], 1, "light") == PNG
    assert sandbox["ops"].closed
    # A fresh probe folder each run, removed afterwards.
    assert not any(k.startswith("/tmp/omni-art-") for k in sandbox["ops"].files)


@pytest.mark.parametrize(
    "probe, word",
    [
        (failing(violations=["connect-src"]), "network"),
        (failing(blocked=2), "network"),
        (failing(errors=1, first_error="TypeError: boom"), "uncaught error"),
        (failing(pages=[page(w, overflow_px=40 if w == 360 else 0, offenders=["div#wide"]) for w in (360, 560, 1280)]), "overflows sideways at 360"),
        (failing(pages=[page(w, rendered=False) for w in (360, 560, 1280)]), "rendered nothing"),
        (failing(loaded=False, load_error="slow"), "did not load"),
    ],
)
def test_failing_checks_store_the_version_with_a_label(tools, store, sandbox, probe, word):
    sandbox["ops"].probe = probe
    text, card = create(tools)
    assert card is not None and "System checks FAILED" in text and word in text
    assert "boom" not in text and "div#wide" not in text  # page text is not in the trusted result
    info = store.get(OWNER, card["artifact_id"])["code"]
    assert info["check_state"] == "failed" and info["shown_version"] == 1


@pytest.mark.parametrize(
    "probe",
    [
        lambda check, doc: (0, passing({**check, "nonce": "0" * 32}, doc)),  # another run's answer
        lambda check, doc: (0, passing(check, doc + " ")),  # other bytes
        lambda check, doc: (97, None),  # the script did not match its checksum
        lambda check, doc: (0, "not json"),
        lambda check, doc: (0, {**passing(check, doc), "runs": passing(check, doc)["runs"][:1]}),
        lambda check, doc: (98, passing(check, doc)),  # the probe saw its folder tampered with
    ],
)
def test_checks_fail_closed(tools, store, sandbox, probe):
    sandbox["ops"].probe = probe
    text, card = create(tools)
    info = store.get(OWNER, card["artifact_id"])["code"]
    assert info["check_state"] == "not_checked" and "gave no answer" in text
    assert store.shot(OWNER, card["artifact_id"], 1, "light") is None


def test_no_sandbox_is_not_checked(tools, store, monkeypatch):
    monkeypatch.setattr(code_service, "sandbox_factory", lambda t, o: None)
    text, card = create(tools)
    assert store.get(OWNER, card["artifact_id"])["code"]["check_state"] == "not_checked"
    text, card = create(tools, "react", REACT)
    assert card is None and "sandbox" in text


def test_a_result_for_other_bytes_is_recorded_as_not_checked(tools, store, sandbox):
    _, card = create(tools)
    store.set_check(OWNER, card["artifact_id"], 1, state="passed", result={"summary": []}, frame_sha256="0" * 64)
    assert store.get(OWNER, card["artifact_id"])["code"]["check_state"] == "not_checked"


def test_a_stale_pending_check_reads_not_checked(tools, store, monkeypatch):
    monkeypatch.setattr(code_service, "sandbox_factory", lambda t, o: (_ for _ in ()).throw(RuntimeError("down")))
    from app.gateway.artifacts_store import store as store_mod

    canon, findings = frame.canonical_html(PAGE)
    summary, version = store.create(OWNER, kind="html", title="P", canon=canon, lineage="user", lineage_source=None, origin="tool", code={"findings": findings})
    assert version["code"]["check"]["state"] == "pending"
    monkeypatch.setattr(store_mod, "LIVENESS_SECONDS", -1)
    assert store.get(OWNER, summary["id"])["code"]["check_state"] == "not_checked"


# -- one automatic fix only ----------------------------------------------------------------


def test_exactly_one_automatic_fix(tools, store, sandbox):
    sandbox["ops"].probe = failing(violations=["img-src"])
    text, card = create(tools)
    aid = card["artifact_id"]
    assert "fix_of=1" in text
    text, card = update(tools, aid, 1, content=PAGE + " ", fix_of=1)
    assert card["version"] == 2 and "do not run another automatic fix" in text and "Run ONE" not in text
    # A fix of the fix, and a second fix of v1, are refused; nothing is written.
    text, card = update(tools, aid, 2, content=PAGE + "  ", fix_of=2)
    assert card is None and "already the automatic fix" in text
    text, card = update(tools, aid, 2, content=PAGE + "  ", fix_of=1)
    assert card is None and "already had its one automatic fix" in text
    assert store.get(OWNER, aid)["latest_version"] == 2


def test_fix_of_a_passing_version_is_refused(tools, store, sandbox):
    _, card = create(tools)
    text, card2 = update(tools, card["artifact_id"], 1, content=PAGE + " ", fix_of=1)
    assert card2 is None and "only for a version whose checks failed" in text
    with pytest.raises(FixRefused):
        store.check_fix(OWNER, card["artifact_id"], 1)


def test_react_fix_is_refused_before_a_build_is_spent(tools, store, sandbox):
    _, card = create(tools, "react", REACT)
    builds = [c for c in sandbox["ops"].commands if "npm ci " in c]
    text, card2 = update(tools, card["artifact_id"], 1, content=REACT, fix_of=1)
    assert card2 is None and len([c for c in sandbox["ops"].commands if "npm ci " in c]) == len(builds)


# -- react: build, versions, source --------------------------------------------------------


def test_react_build_stores_bundle_source_and_recipe(tools, store, sandbox):
    text, card = create(tools, "react", REACT)
    assert card["kind"] == "react" and "System checks passed" in text
    summary, version, code, check = store.code_version(OWNER, card["artifact_id"], 1)
    html = store.content(OWNER, version).decode()
    assert 'getElementById("root")' in html and "<style>body{margin:0}</style>" in html and frame.SHIM[:40] not in html
    assert json.loads(store.source(OWNER, code)) == REACT
    assert json.loads(code.recipe)["versions"] == react_build.VERSIONS
    build = next(c for c in sandbox["ops"].commands if "npm ci " in c)
    assert "--ignore-scripts" in build and "env -i PATH=/opt/nodejs/22/bin:/usr/bin:/bin" in build and f"timeout -k 5 {caps.REACT_BUILD_SECONDS}" in build
    assert store.usage(OWNER) == version.size + code.source_size


def test_react_build_runs_in_a_fresh_folder_and_cleans_up(tools, store, sandbox):
    create(tools, "react", REACT)
    made = [c for c in sandbox["ops"].commands if "mkdir -m 700 /tmp/omni-artb-" in c]
    assert len(made) == 1 and re.search(r"/tmp/omni-artb-[0-9a-f]{32}", made[0])
    assert not any(k.startswith("/tmp/omni-artb-") for k in sandbox["ops"].files)


def test_read_returns_code_source_fenced(tools, store, sandbox):
    sandbox["ops"].probe = failing(errors=1, first_error="ReferenceError: nope")
    _, card = create(tools, "react", REACT)
    text = tools.read(ctx(), artifact_id=card["artifact_id"], version=None)
    assert text.startswith(FENCE_LABEL)
    tag = re.search(r"<(artifact-[0-9a-f]{8}) ", text).group(1)
    body = text.split(f"<{tag}", 1)[1]
    assert 'kind="react"' in body and 'build_state="ok"' in body and 'checks="failed"' in body
    assert "----- file: App.tsx -----" in body and "export default function App" in body
    assert "ReferenceError: nope" in body and body.rstrip().endswith(f"</{tag}>")


def test_restore_and_duplicate_keep_code_and_checks(tools, store, sandbox):
    _, card = create(tools)
    aid = card["artifact_id"]
    update(tools, aid, 1, edits=[{"old": "Hello", "new": "Hi"}])
    _, v3 = store.restore(OWNER, aid, version=1, base_version=2)
    assert v3["code"]["check"]["state"] == "passed" and v3["code"]["build_state"] == "ok"
    copy = store.duplicate(OWNER, aid, version=1)
    assert copy["code"]["check_state"] == "passed"


def test_delete_removes_sources_and_screenshots(tools, store, sandbox):
    _, card = create(tools, "react", REACT)
    aid = card["artifact_id"]
    _, _, code, check = store.code_version(OWNER, aid, 1)
    paths = [blobs.path_for(OWNER, h) for h in (code.source_hash, check.shot_light, check.shot_dark)]
    assert all(p.exists() for p in paths)
    store.set_archived(OWNER, aid, True)
    store.delete(OWNER, aid, confirm_id=aid, version_count=1)
    assert not any(p.exists() for p in paths) and store.usage(OWNER) == 0


def test_html_update_after_reading_it_stays_user_led(tools, store, sandbox):
    """#211's exception holds for code kinds: reading the artifact to fix it."""
    _, card = create(tools)
    aid = card["artifact_id"]
    text, read = tools.read_bound(ctx(), artifact_id=aid, version=None)
    msgs = [
        user_turn("fix my page"),
        AIMessage(content="", tool_calls=[{"name": "artifact_read", "args": {"id": aid}, "id": "r1"}]),
        ToolMessage(content=text, tool_call_id="r1", name="artifact_read", artifact=read),
        AIMessage(content="", tool_calls=[{"name": "artifact_update", "args": {}, "id": "u1"}]),
    ]
    _, card2 = update(tools, aid, 1, content=PAGE.replace("Hello", "Hey"), messages=msgs)
    assert store.versions(OWNER, aid)[0]["lineage"] == "user"


def test_parse_rejects_malformed_values():
    for raw in ("[]", json.dumps({"v": 1, "mode": "artifact", "nonce": "n", "prod_sha256": "s", "runs": [{"theme": "dark"}]})):
        assert checks.parse(raw, exit_code=0, nonce="n", prod_sha256="s")["outcome"] == "error"


# -- review round: WebRTC watch, exit status, capped reads, one fix per turn --------------


def test_a_webrtc_attempt_seen_by_the_probe_fails_the_check(tools, store, sandbox):
    sandbox["ops"].probe = failing(rtc=3)
    text, card = create(tools)
    assert store.get(OWNER, card["artifact_id"])["code"]["check_state"] == "failed" and "network" in text


def test_a_run_without_the_webrtc_watch_is_not_checked(tools, store, sandbox):
    sandbox["ops"].probe = failing(rtc_watched=False)
    _, card = create(tools)
    assert store.get(OWNER, card["artifact_id"])["code"]["check_state"] == "not_checked"


@pytest.mark.parametrize("code", [137, 143, 1])
def test_a_result_from_a_probe_that_did_not_exit_cleanly_is_not_counted(tools, store, sandbox, code):
    sandbox["ops"].probe = lambda check, doc: (code, passing(check, doc))
    _, card = create(tools)
    assert store.get(OWNER, card["artifact_id"])["code"]["check_state"] == "not_checked"


def test_capped_read_refuses_a_file_that_grows_or_is_a_link(sandbox):
    ops = sandbox["ops"]
    ops.files["/r/result.json"] = "{}"
    assert checks.capped_read(ops, "/r/result.json", 10) == b"{}"
    ops.grow["/r/result.json"] = 50
    assert checks.capped_read(ops, "/r/result.json", 10) is None
    ops.grow.clear()
    ops.links.add("/r/result.json")
    assert checks.capped_read(ops, "/r/result.json", 10) is None


def test_one_automatic_fix_per_turn_even_without_fix_of(tools, store, sandbox):
    sandbox["ops"].probe = failing(violations=["img-src"])
    _, card = create(tools)
    aid = card["artifact_id"]
    _, card2 = update(tools, aid, 1, content=PAGE + " ")  # no fix_of: still the automatic fix
    assert card2["version"] == 2
    assert store.code_version(OWNER, aid, 2)[2].fix_of == 1
    text, card3 = update(tools, aid, 2, content=PAGE + "  ")
    assert card3 is None and "already made the one automatic fix" in text
    assert "try again once they ask for a change" in text
    # A later turn (the owner asked again) may change it.
    _, card4 = tools.update(ctx(run_id="run-2"), artifact_id=aid, base_version=2, content=PAGE + "   ", edits=None, language=None, note=None)
    assert card4["version"] == 3


@pytest.mark.parametrize(
    "files",
    [
        {"App.tsx": 'import x from "../../etc/passwd";\nexport default () => null;'},
        {"App.tsx": 'import x from "/abs/file";\nexport default () => null;'},
        {"App.tsx": 'import x from "lodash";\nexport default () => null;'},
        {"App.tsx": 'const x = require("https://cdn/x.js");\nexport default () => null;'},
        {"App.tsx": "export default () => <div dangerouslySetInnerHTML={{__html: s}} />;"},
        {"App.tsx": 'import "./a.css";\nexport default () => null;', "a.css": '@import "../../x.css";'},
    ],
)
def test_react_sources_stay_inside_the_project(files):
    with pytest.raises(InvalidContent):
        frame.canonical_react_source({"entry": "App.tsx", "files": files})


def test_the_build_installs_exactly_the_tracked_lockfile():
    import json as _json

    lock = _json.loads(react_build.PACKAGE_LOCK)
    pkg = _json.loads(react_build.package_json())
    assert lock["packages"][""]["dependencies"] == pkg["dependencies"] and lock["packages"][""]["devDependencies"] == pkg["devDependencies"]
    assert all(v.get("integrity", "").startswith("sha512-") for k, v in lock["packages"].items() if k)
    assert "npm ci " in react_build.command("/tmp/x") and "npm install" not in react_build.command("/tmp/x")


def test_one_automatic_fix_even_without_a_turn_id(tools, store, sandbox):
    sandbox["ops"].probe = failing(violations=["img-src"])
    _, card = tools.create(ctx(run_id=None), kind="html", title="P", content=PAGE, language=None, source_path=None, note=None)
    aid = card["artifact_id"]
    _, card2 = tools.update(ctx(run_id=None), artifact_id=aid, base_version=1, content=PAGE + " ", edits=None, language=None, note=None)
    assert card2["version"] == 2
    text, card3 = tools.update(ctx(run_id=None), artifact_id=aid, base_version=2, content=PAGE + "  ", edits=None, language=None, note=None)
    assert card3 is None and "already made the one automatic fix" in text
    # The owner acting on it opens a new round.
    store.add_version(OWNER, aid, base_version=2, canon=frame.canonical_html(PAGE + "   ")[0], lineage="user", lineage_source=None, origin="owner_edit", code={})
    _, card4 = tools.update(ctx(run_id=None), artifact_id=aid, base_version=3, content=PAGE + "    ", edits=None, language=None, note=None)
    assert card4["version"] == 4
