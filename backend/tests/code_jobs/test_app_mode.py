"""App mode of a coding job (Spec 011 FR-025 to FR-028): the kit, the manifest
from the lead's `app` argument, the sample data, the source scan, the app
probe's result parser, the bundle with the platform shim, who led to the
job, and the lead's report.

The composition (the lead, the tool, the job manager, registration through
`create_app()`) is in test_app_mode_http.py; the probe itself, in the real
sandbox image with its browser, in test_app_probe_docker.py.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.gateway.apps import bundle as bundle_mod
from app.gateway.code_jobs import app_checks, app_kit, app_mode
from app.gateway.code_jobs import layout as layout_mod

REPO = Path(__file__).resolve().parents[3]
FRONTEND_SHIM = REPO / "frontend/src/core/apps/shim"
FIXTURE = Path(__file__).with_name("app_fixtures") / "pass"
TODAY = ["calendar", "gh_review", "gh_failing", "gh_merged", "ledger", "sessions", "automations", "inbox"]


def today_manifest(**extra) -> dict:
    return app_kit.manifest_from_spec({"name": "Today", "sources": TODAY, **extra})


# -- byte copies and generated files stay in step ---------------------------------


def test_the_gateway_shim_and_types_are_byte_copies_of_the_frontends():
    assert bundle_mod.SHIM_FILE.read_bytes() == (FRONTEND_SHIM / "omni-shim.js").read_bytes()
    assert app_kit.DTS_PATH.read_bytes() == (FRONTEND_SHIM / "omni.d.ts").read_bytes()


def test_graphite_tokens_are_generated_from_globals_css_both_themes():
    globals_css = (REPO / "frontend/src/styles/globals.css").read_text()
    assert app_kit.TOKENS_PATH.read_text() == app_kit.tokens_from_globals(globals_css)
    css = app_kit.graphite_css()
    light, dark = css.split(".dark {", 1)
    for token in ("--background", "--card", "--foreground", "--muted-foreground", "--chart-series", "--destructive"):
        assert f"{token}:" in light and f"{token}:" in dark
    assert "color-scheme: dark" in dark and ".omni-tile" in css and ".omni-state" in css


def test_the_mock_shim_has_the_real_shims_tile_words():
    real = bundle_mod.shim()
    mock = app_kit.MOCK_SHIM_PATH.read_text()

    def body(text: str, name: str) -> str:
        m = re.search(r"\n  function " + name + r"\(.*?\n  }\n", text, re.S)
        assert m, name
        return m.group(0)

    for name in ("ago", "describe"):
        assert body(mock, name) == body(real, name)
    words = (FRONTEND_SHIM / "README.md").read_text()
    rules = app_kit.RULES_PATH.read_text()
    for phrase in ('"updated 4 min ago"', '"Not connected"', '"Can\'t tell"', '"Nothing today"', "May be out of date"):
        assert phrase.strip('"') in words and phrase.strip('"') in rules


# -- the manifest from the lead's argument ------------------------------------------


def test_short_names_become_the_today_manifest_with_every_field():
    m = today_manifest(timezone="Europe/London")
    assert list(m["sources"]) == TODAY
    assert m["sources"]["gh_failing"]["params"] == {"preset": "failing", "limit": 20, "tz": "Europe/London"}, "GitHub weeks follow the app's zone"
    assert m["sources"]["calendar"]["params"]["tz"] == "Europe/London" and m["sources"]["ledger"]["params"]["tz"] == "Europe/London"
    assert m["sources"]["inbox"]["fields"] == ["count", "subject", "received_at", "link"]


def test_catalog_ids_and_objects_are_accepted_and_validated():
    m = app_kit.manifest_from_spec({"name": "Mail", "sources": ["gmail.unread_subjects", {"name": "prs", "use": "github.pr_search", "params": {"preset": "merged_7d", "limit": 5}, "fields": ["title", "link"]}]})
    assert list(m["sources"]) == ["inbox", "prs"] and m["sources"]["prs"]["fields"] == ["title", "link"]


@pytest.mark.parametrize(
    ("spec", "why"),
    [
        ({"sources": ["calendar"]}, "app.name is required"),
        ({"name": "x", "sources": []}, "at least one source"),
        ({"name": "x", "sources": ["mail_bodies"]}, "unknown source"),
        ({"name": "x", "sources": ["github.pr_search"]}, "needs a preset"),
        ({"name": "x", "sources": {"a": {"use": "gmail.unread_subjects", "fields": ["body"]}}}, "not allowed"),
        ({"name": "x", "sources": ["calendar"], "timezone": "Mars/Base"}, "IANA"),
        ({"name": "x", "sources": [{"name": "Bad Name", "use": "omni.sessions.active"}]}, "must match"),
        ({"name": "x", "sources": [{"name": "w", "use": "gmail.delete_message"}]}, "catalog entry"),
    ],
)
def test_an_invalid_app_argument_is_refused_with_the_reason(spec, why):
    with pytest.raises(app_kit.AppSpecError, match=re.escape(why) if why != "must match" else "must match"):
        app_kit.manifest_from_spec(spec)


def test_the_projects_manifest_is_read_back_strictly():
    good = app_kit.manifest_text(today_manifest())
    assert app_kit.read_manifest(good)["name"] == "Today"
    assert app_kit.read_manifest(None) is None and app_kit.read_manifest("{") is None
    assert app_kit.read_manifest(json.dumps({**json.loads(good), "extra": 1})) is None
    assert "not valid JSON" in app_kit.manifest_error("{") and "unknown key" in app_kit.manifest_error(json.dumps({**json.loads(good), "extra": 1}))
    assert app_kit.read_manifest("x" * (app_kit.MANIFEST_MAX_BYTES + 1)) is None


# -- the kit ----------------------------------------------------------------------------


def test_the_kit_has_every_file_and_types_generated_from_the_sources():
    files = app_kit.kit_files(today_manifest())
    assert set(files) >= set(f"omni-kit/{n}" for n in ("APP_RULES.md", "omni.d.ts", "graphite.css", "mock-data.json", "omni-app.schema.json", "omni-mock.js"))
    dts = files["omni-kit/omni.d.ts"]
    assert 'calendar: CatalogData["googlecalendar.events_today"];' in dts and 'inbox: CatalogData["gmail.unread_subjects"];' in dts
    assert "export interface OmniSources {}" not in dts
    schema = json.loads(files["omni-kit/omni-app.schema.json"])
    uses = [e["properties"]["use"]["const"] for e in schema["properties"]["sources"]["additionalProperties"]["oneOf"]]
    assert "gmail.unread_subjects" in uses and len(uses) == 6
    assert "__OMNI_MOCK__" in files["omni-kit/omni-mock.js"] and "OmniHarness platform shim" not in files["omni-kit/omni-mock.js"]
    rules = files["omni-kit/APP_RULES.md"]
    for rule in ("No network of any kind", "innerHTML", "dangerouslySetInnerHTML", "<iframe>", "omni.open", "Graphite only", "360 px", "AA", "inline SVG", "omni.d.ts", "2 MB"):
        assert rule in rules, rule


def test_sample_data_has_four_states_and_only_the_selected_fields():
    m = app_kit.manifest_from_spec({"name": "x", "sources": {"prs": {"use": "github.pr_search", "params": {"preset": "failing"}, "fields": ["title", "number"]}, "inbox": {"use": "gmail.unread_subjects", "fields": ["subject"]}}})
    data = app_kit.fixtures(m)
    assert data["sources"]["prs"]["fresh"]["items"][0] == {"number": 479, "title": "Upgrade the build to Node 22"}
    assert data["sources"]["inbox"]["fresh"] == {"items": data["sources"]["inbox"]["fresh"]["items"]} and set(data["sources"]["inbox"]["fresh"]["items"][0]) == {"subject"}
    assert data["sources"]["prs"]["empty"] == {"items": [], "more": False, "dropped": 0}, "the bridge always sends more and dropped"
    file = app_kit.mock_data_file(m)
    assert set(file["sources"]["prs"]) == {"use", "fresh", "empty", "not_connected", "failed"}
    assert file["sources"]["prs"]["failed"]["reason"] == app_kit.MOCK_REASON
    s = app_kit.sentinels(data)
    assert s["prs"] == ["Upgrade the build to Node 22", "Rotate the staging certificates"]


def test_the_mock_script_cannot_be_closed_by_its_data():
    data = {"now": "2026-01-14T10:20:00+00:00", "reason": "</script><script>alert(1)</script>", "sources": {}}
    script = app_kit.mock_script(data)
    assert "</script" not in script.split("\n", 1)[0] and "<" not in script.split("\n", 1)[0]


# -- the bundle with the platform shim --------------------------------------------------


def test_the_mock_build_replaces_the_platform_shim_with_the_mock():
    files = {"index.html": b'<!doctype html><html><head><title>x</title></head><body><script src="./a.js"></script></body></html>', "a.js": b"document.title = 'ok';"}
    app, _ = bundle_mod.inline(files)
    assert app.decode().index("OmniHarness platform shim") < app.decode().index("document.title")
    mock, hashes = bundle_mod.inline({"index.html": app}, platform_shim=app_kit.mock_script({"now": "2026-01-14T10:20:00+00:00", "reason": "r", "sources": {}}))
    text = mock.decode()
    assert "OmniHarness platform shim" not in text and text.index("__OMNI_MOCK__") < text.index("document.title") and len(hashes) == 2


# -- the source scan ----------------------------------------------------------------------


def test_the_source_scan_runs_with_absolute_paths_and_skips_dependencies():
    cmd = app_checks.scan_command("/mnt/user-data/workspace/today", "/tmp/out")
    assert "/usr/bin/env -i PATH=/usr/bin:/bin" in cmd and "/usr/bin/grep -rnoIEZ" in cmd
    for skipped in ("node_modules", "dist", "omni-kit"):
        assert f"--exclude-dir={skipped}" in cmd


@pytest.mark.parametrize(
    ("line", "code"),
    [
        ("const r = await fetch('https://x.test')", "network"),
        ("new XMLHttpRequest()", "network"),
        ("el.innerHTML = s", "html_string"),
        ("<div dangerouslySetInnerHTML={{__html: s}} />", "html_string"),
        ("document.createElement('iframe')", "frame"),
        ("<iframe srcdoc='x'>", "frame"),
        ("eval(code)", "eval"),
        ("const f = new Function('a', 'return a')", "eval"),
        ("const ws = new WebSocket(u)", "socket"),
        ("const m = await import('./x.js')", "dynamic_import"),
        ("new Worker(url)", "worker"),
    ],
)
def test_the_source_scan_names_each_forbidden_api(line, code):
    pattern = next(p for c, _, p in app_checks.SOURCE_RULES if c == code)
    assert re.search(app_checks._ere_to_python(pattern), line)
    findings = app_checks.parse_scan(f"./src/App.tsx\x0012:{line}\n")
    assert findings and findings[0]["code"] == code and findings[0]["file"] == "src/App.tsx" and findings[0]["line"] == 12


def test_the_source_scan_does_not_flag_ordinary_code():
    for line in ("const prefetch = 1", "refetch()", "import { x } from './y'", "evaluate(x)", "omni.open(link)"):
        assert app_checks.parse_scan(f"./src/a.ts\x001:{line}\n") == [], line


# -- the app probe's result ------------------------------------------------------------------


def page(width: int, **app) -> dict:
    words = {"updated": 3, "ago": 3, "nothing": 0, "not_connected": 0, "cant_tell": 0, "connect": 0, "junk": 0, "reason": False, **app.pop("words", {})}
    base = {"contrast_measured": 20, "contrast_low": 0, "contrast": [], "small_text": 0, "small_text_where": [], "small_targets": 0, "small_targets_where": [], "frames": 0, "doc_height": 900, "words": words}
    base["sentinels"] = {"calendar": True, "inbox": True, "gh_review": True}
    base["times"] = {"local_found": 99, "first_missing": "", "shifted_found": ""}
    top = {k: app.pop(k) for k in ("overflow_px", "offenders", "svgs", "rendered") if k in app}
    return {"width": width, "overflow_px": 0, "client_width": width, "offenders": [], "rendered": True, "svgs": [], **top, "app": {**base, **app}}


STATE_WORDS = {
    "fresh": {},
    "empty": {"words": {"updated": 2, "ago": 2, "nothing": 2}, "sentinels": {"calendar": False, "inbox": False, "gh_review": False}},
    "not_connected": {"words": {"updated": 0, "ago": 0, "not_connected": 2, "connect": 2}, "sentinels": {"calendar": False, "inbox": False, "gh_review": False}},
    "failed": {"words": {"updated": 0, "ago": 0, "cant_tell": 2, "reason": True}, "sentinels": {"calendar": False, "inbox": False, "gh_review": False}},
}


def _runs(change: dict, widths) -> list[dict]:
    runs = []
    for theme in app_checks.THEMES:
        for state in app_checks.STATES:
            c = change.get((theme, state), {})
            pages = []
            for w in widths:
                fields = json.loads(json.dumps(STATE_WORDS[state]))
                for key in ("all", w):
                    for k, v in c.get(key, {}).items():
                        fields[k] = {**fields.get(k, {}), **v} if isinstance(v, dict) and k in ("words", "sentinels") else v
                pages.append(page(w, **fields))
            runs.append({"theme": theme, "state": state, "loaded": True, "crashed": False, "errors": 0, "first_error": "", "pages": pages, "violations": [], "watched": True, **c.get("run", {})})
    return runs


def app_result(change: dict | None = None, prod_change: dict | None = None, **top) -> str:
    """A passing app probe result. `change[(theme, state)] = {width or 'all':
    page fields, 'run': run fields}` changes the development runs;
    `prod_change` the production runs (every theme and state, at 1280 px)."""
    runs = _runs(change or {}, layout_mod.WIDTHS)
    prod = _runs(prod_change or {}, (layout_mod.WIDTHS[-1],))
    shots = [{"theme": t, "width": w, "file": f"shot-{t}-{w}.png", "bytes": 1000, "height": 900} for t in app_checks.THEMES for w in layout_mod.WIDTHS]
    return json.dumps({"v": 1, "mode": "app", "runs": runs, "prod": prod, "shots": shots, **top})


def parse(raw, exit_code=0):
    return app_checks.parse(raw, exit_code=exit_code, data_sources=["calendar", "inbox"])


def test_a_good_app_passes_every_theme_state_and_width_and_keeps_its_screenshots():
    r = parse(app_result())
    assert r["outcome"] == "pass" and r["failures"] == [] and r["design"] == [] and r["publishable"]
    assert len(r["shots"]) == 6 and r["shots"][0] == {"theme": "light", "width": 360, "file": "shot-light-360.png", "bytes": 1000}


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({("light", "fresh"): {360: {"overflow_px": 412, "offenders": ["div.board in main.omni-page"]}}}, "overflows sideways at 360 px by 412 px (sticking out: div.board in main.omni-page)"),
        ({("dark", "fresh"): {360: {"svgs": [{"where": "svg.load in div.omni-tile", "side": "right", "px": 40, "kind": "shape"}]}}}, "chart clipped: svg.load in div.omni-tile (cut off 40 px on the right) at 360 px"),
        ({("dark", "empty"): {"all": {"contrast_low": 3, "contrast": [{"where": "span.meta in li", "ratio": 2.1, "need": 4.5}]}}}, "text below AA contrast in dark (3 elements; worst 2.10:1 where 4.5:1 is needed: span.meta in li)"),
        ({("light", "failed"): {"all": {"words": {"nothing": 2}}}}, 'failed state: says "Nothing today"'),
        ({("light", "failed"): {"all": {"words": {"cant_tell": 0}}}}, 'failed state: no "Can\'t tell"'),
        ({("light", "failed"): {"all": {"words": {"reason": False}}}}, "failed state: the failure reason is not shown"),
        ({("dark", "not_connected"): {"all": {"words": {"connect": 0}}}}, "not connected state: no Connect button"),
        ({("light", "empty"): {"all": {"sentinels": {"calendar": True}}}}, "empty state: still shows sample data"),
        ({("light", "fresh"): {"all": {"sentinels": {"inbox": False}}}}, "the fresh state shows none of the sample data of source inbox (light)"),
        ({("light", "fresh"): {"all": {"words": {"ago": 0}}}}, 'fresh state: no "updated N min ago"'),
        ({("light", "fresh"): {"run": {"violations": ["connect-src"]}}}, "the page tried a network request, which the app's CSP blocks (connect-src; light/fresh)"),
        ({("dark", "fresh"): {"run": {"violations": ["require-trusted-types-for"]}}}, "the page tried HTML or script from a string (Trusted Types), which the app's CSP blocks"),
        ({("light", "empty"): {"all": {"frames": 1}}}, "the page has a nested frame or embedded object (light/empty)"),
        ({("dark", "failed"): {"all": {"words": {"junk": 1}}}}, '"[object Object]" (dark/failed)'),
        ({("light", "fresh"): {"run": {"errors": 1, "first_error": "TypeError: x is undefined"}}}, "uncaught error on load (light/fresh): TypeError: x is undefined"),
    ],
)
def test_each_failure_blocks_with_the_systems_words(change, expected):
    r = parse(app_result(change))
    assert r["outcome"] == "fail" and layout_mod.counts_against(r)
    assert any(expected in f for f in r["failures"]), r["failures"]


def test_measured_design_findings_do_not_block():
    change = {("light", "fresh"): {360: {"small_text_where": [{"where": "span.tiny", "px": 10}], "small_text": 2, "small_targets_where": [{"where": "a.row", "w": 180, "h": 20}], "small_targets": 1}}}
    for state in ("empty",):
        for theme in app_checks.THEMES:
            change[(theme, state)] = {"all": {"words": {"nothing": 0}}}
    r = parse(app_result(change))
    assert r["outcome"] == "pass"
    assert r["design"] == ["text under 12 px: span.tiny (10 px)", "touch targets under 24 px: a.row (180x20 px)", 'the empty state does not say "Nothing today": check that every tile has its own wording of nothing']


def test_a_broken_page_is_not_published_and_no_answer_is_an_error():
    r = parse(app_result({("light", "fresh"): {"run": {"loaded": False, "load_error": "slow"}}}))
    assert r["outcome"] == "fail" and not r["publishable"] and "did not load (light/fresh: it did not finish loading within 10 s)" in r["failures"]
    assert parse(None, exit_code=None)["outcome"] == "error" and app_checks.blocks(parse(None, exit_code=None))
    assert parse("{}")["error_code"] == "unreadable" and layout_mod.counts_against(parse("{}"))
    assert parse("", exit_code=97)["error_code"] == "checksum"
    assert parse(app_result()[:-30])["error_code"] == "unreadable"


def test_runs_out_of_order_or_a_layout_result_are_unreadable():
    data = json.loads(app_result())
    data["runs"][0], data["runs"][1] = data["runs"][1], data["runs"][0]
    assert parse(json.dumps(data))["error_code"] == "unreadable"
    assert parse(json.dumps({"v": 1, "pages": []}))["error_code"] == "unreadable"


def test_screenshots_are_only_the_names_the_system_expects():
    data = json.loads(app_result())
    data["shots"] = [
        {"theme": "light", "width": 360, "file": "../../etc/passwd", "bytes": 10},
        {"theme": "dark", "width": 560, "file": "shot-dark-560.png", "bytes": 99_000_000},
        {"theme": "dark", "width": 1280, "file": "shot-dark-1280.png", "bytes": 500},
    ]
    assert parse(json.dumps(data))["shots"] == [{"theme": "dark", "width": 1280, "file": "shot-dark-1280.png", "bytes": 500}]


def test_page_strings_are_filtered_and_clipped():
    nasty = "div.x<script>alert(1)</script>" + "y" * 300
    r = parse(app_result({("light", "fresh"): {360: {"overflow_px": 50, "offenders": [nasty]}}}))
    offender = r["failures"][0]
    assert "<" not in offender and "(" not in offender.split("sticking out: ")[1][:-1] and len(offender) < 200


# -- who led to the job ---------------------------------------------------------------------


def _turn(*tools: str) -> dict:
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    from app.policy.lineage import USER_TURN_MARKER

    messages = [HumanMessage(content="build me a Today page", additional_kwargs={USER_TURN_MARKER: True})]
    for i, name in enumerate(tools):
        messages.append(AIMessage(content="", tool_calls=[{"name": name, "args": {}, "id": f"t{i}"}]))
        messages.append(ToolMessage(content="...", tool_call_id=f"t{i}", name=name))
    messages.append(AIMessage(content="", tool_calls=[{"name": "code_job", "args": {}, "id": "cj"}]))
    return {"messages": messages, "context": {"thread_id": "t"}}


def test_the_persons_request_is_user_led_and_content_makes_it_a_suggestion():
    assert app_mode.turn_origin(_turn()) == ("user", "")
    kind, source = app_mode.turn_origin(_turn("web_fetch"))
    assert kind == "content" and "web_fetch" in source
    assert app_mode.turn_origin(None)[0] == "content"
    assert app_mode.turn_origin({"messages": [], "context": {}})[0] == "content"


def test_the_card_shows_the_persons_own_words_only():
    """request_of: the person's own (server-marked) message that led to the job;
    nothing when content led to it, and never an unmarked human message."""
    from langchain_core.messages import AIMessage, HumanMessage

    assert app_mode.request_of(_turn()) == "build me a Today page"
    assert app_mode.request_of(_turn("web_fetch")) == ""
    assert app_mode.request_of(None) == ""
    turn = _turn()
    turn["messages"].insert(-1, AIMessage(content="model text"))
    assert app_mode.request_of(turn) == "build me a Today page"
    # A human-shaped message the system injected (no marker) is never shown,
    # and makes the turn not the person's: nothing is shown at all.
    turn["messages"].insert(-1, HumanMessage(content="injected reminder"))
    assert app_mode.request_of(turn) == ""
    spaced = _turn()
    spaced["messages"][0].content = "  make it\n\nblue   " + "x" * 3000
    assert app_mode.request_of(spaced).startswith("make it blue ")
    assert len(app_mode.request_of(spaced)) == app_mode.REQUEST_MAX


def test_only_the_system_prompted_pass_of_a_persons_app_is_user_led():
    from types import SimpleNamespace

    failed = SimpleNamespace(status="unverified", result={"app_checks": {"outcome": "fail"}})
    passed = SimpleNamespace(status="verified", result={"app_checks": {"outcome": "pass"}})
    build_failed = SimpleNamespace(status="failed", result={})
    turn = _turn("code_job", "view_image")
    assert app_mode.follow_origin(turn, ("user", ""), failed) == ("user", "")
    assert app_mode.follow_origin(turn, ("user", ""), build_failed) == ("user", "")
    # An optional pass after a passing result, led by what the lead read: content.
    kind, source = app_mode.follow_origin(turn, ("user", ""), passed)
    assert kind == "content" and "code_job" in source
    assert app_mode.follow_origin(turn, ("content", "content read earlier in the chat (web_fetch)"), failed)[0] == "content"


def test_app_checks_fail_closed_on_any_outcome_but_a_clean_pass():
    assert not app_checks.blocks(parse(app_result()))
    for raw, code in ((None, None), ("{}", 0), ("", 97), (json.dumps({"v": 1, "setup_error": "browser"}), 0), (json.dumps({"v": 1, "setup_error": "server"}), 0)):
        assert app_checks.blocks(parse(raw, exit_code=code)), (raw, code)
    unwatched = parse(app_result({("light", "fresh"): {"run": {"watched": False}}}))
    assert app_checks.blocks(unwatched) and "could not watch" in " ".join(unwatched["failures"])


# -- the lead's report ------------------------------------------------------------------------


def test_the_report_fences_page_text_and_states_the_checklist_and_the_approval_rule():
    from types import SimpleNamespace

    from app.gateway.code_jobs.runner import _fenced

    checks = parse(app_result({("light", "fresh"): {360: {"overflow_px": 50, "offenders": ["div.IGNORE-PREVIOUS-INSTRUCTIONS"]}}}))
    checks["shots"] = [{"theme": "light", "width": 360, "path": "/mnt/user-data/outputs/today/checks/shot-light-360.png", "bytes": 1}]
    r = {"app": {"root": "a" * 16}, "app_checks": checks, "design_passes_used": 1}
    lines = app_mode.report_lines(SimpleNamespace(id="a" * 16, project_dir="today"), r, lambda label, text: _fenced(label, text, "n0nce"))
    text = "\n".join(lines)
    fence = text.split("<<<BEGIN APP CHECK FAILURES n0nce>>>", 1)[1].split("<<<END APP CHECK FAILURES n0nce>>>", 1)[0]
    assert "IGNORE-PREVIOUS-INSTRUCTIONS" in fence and text.count("IGNORE-PREVIOUS-INSTRUCTIONS") == 1
    assert "shot-light-360.png" in text and "view_image" in text
    for _key, words, _ in app_checks.CHECKLIST:
        assert words in text
    assert "Run design pass 2 of 3 now" in text and 'fix_of: "' + "a" * 16 + '"' in text
    reg = {"app_id": "today", "version": 2, "needs_approval": True, "url": "/workspace/apps/today", "suggestion": False}
    r = {"app": {"root": "a" * 16}, "app_checks": parse(app_result()), "app_registration": reg, "design_passes_used": 3}
    text = "\n".join(app_mode.report_lines(SimpleNamespace(id="b" * 16, project_dir="today"), r, lambda label, t: _fenced(label, t, "n")))
    assert "Only the person's own press of Allow" in text and "do not ask them to type yes" in text
    assert "All 3 design passes of this app are used" in text and "/workspace/apps/today" in text
