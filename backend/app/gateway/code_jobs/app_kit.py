"""The app kit of a coding job in app mode (Spec 011 FR-025).

Before the worker starts, the gateway writes into the project:

  omni-app.json                 the manifest (a starter built from the lead's
                                `app` argument, validated against the catalog)
  omni-kit/APP_RULES.md         the app rules (tracked: app_files/APP_RULES.md)
  omni-kit/omni.d.ts            the shim's types with `OmniSources` generated
                                from the manifest's sources
  omni-kit/graphite.css         the Graphite tokens of frontend globals.css,
                                both themes, plus dashboard primitives
  omni-kit/mock-data.json       sample data for every source in four states
  omni-kit/omni-app.schema.json the manifest's JSON Schema, from the catalog
  omni-kit/omni-mock.js         the mock shim with the sample data (never in index.html)

The kit is the worker's material, not the system's evidence: the system's
checks regenerate the sample data and the mock shim from the FINAL manifest
and its own tracked copies, whatever the worker did to these files. The
platform shim that ships is inlined by registration from the gateway's own
copy (app.gateway.apps.bundle.SHIM_FILE), never from the project; the kit
carries only the MOCK shim (omni-kit/omni-mock.js) for trying the page locally.
"""

from __future__ import annotations

import copy
import json
import re
import zoneinfo
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from app.gateway.apps import bundle as bundle_mod
from app.gateway.apps.catalog import CATALOG, ITEMS_MAX, REFRESH_MAX_S, REFRESH_MIN_S, get_entry, select
from app.gateway.apps.manifest import DESCRIPTION_MAX, NAME_MAX, SOURCES_MAX, ManifestError, validate_manifest

HERE = Path(__file__).with_name("app_files")
KIT_DIR = "omni-kit"
MANIFEST = "omni-app.json"
#: The manifest is read back only if it is this small.
MANIFEST_MAX_BYTES = 64 * 1024
TOKENS_PATH = HERE / "graphite-tokens.css"
PRIMITIVES_PATH = HERE / "primitives.css"
MOCK_SHIM_PATH = HERE / "omni-mock.js"
RULES_PATH = HERE / "APP_RULES.md"
DTS_PATH = bundle_mod.SHIM_FILE.with_name("omni.d.ts")
#: The day the sample data is written for; the mock shim moves it to today.
#: The failure every source reports in the `failed` state (a check reads it back).
MOCK_REASON = "Sample failure: the source did not answer in time"

#: Short names the lead may use for a source; each is a manifest entry.
STARTER_SOURCES: dict[str, dict[str, Any]] = {
    "calendar": {"use": "googlecalendar.events_today"},
    "gh_review": {"use": "github.pr_search", "params": {"preset": "review_requested"}},
    "gh_failing": {"use": "github.pr_search", "params": {"preset": "failing"}},
    "gh_merged": {"use": "github.pr_search", "params": {"preset": "merged_7d"}},
    "ledger": {"use": "omni.ledger.today"},
    "sessions": {"use": "omni.sessions.active"},
    "automations": {"use": "omni.automations.recent"},
    "inbox": {"use": "gmail.unread_subjects"},
}
_BY_ENTRY = {"googlecalendar.events_today": "calendar", "omni.ledger.today": "ledger", "omni.sessions.active": "sessions", "omni.automations.recent": "automations", "gmail.unread_subjects": "inbox"}


class AppSpecError(ValueError):
    """The lead's `app` argument cannot become a valid manifest."""


# -- the manifest --------------------------------------------------------------


def manifest_from_spec(spec: dict) -> dict:
    """The normalised starter manifest for the lead's `app` argument:
    `{name, description?, timezone?, sources}` where `sources` is a list of
    short names (STARTER_SOURCES), catalog ids, or `{name, use, params?,
    fields?, refresh_s?}` objects, or a map of name to such an object."""
    if not isinstance(spec, dict):
        raise AppSpecError("app must be an object with a name and sources")
    name = spec.get("name")
    if not isinstance(name, str) or not name.strip():
        raise AppSpecError('app.name is required (the app\'s title, for example "Today")')
    raw = spec.get("sources")
    items: list[tuple[str | None, Any]]
    if isinstance(raw, dict):
        items = list(raw.items())
    elif isinstance(raw, list):
        items = [(None, s) for s in raw]
    else:
        raise AppSpecError('app.sources must list the data sources (for example ["calendar", "inbox"])')
    if not items:
        raise AppSpecError("app.sources must name at least one source")
    if len(items) > SOURCES_MAX:
        raise AppSpecError(f"app.sources may name at most {SOURCES_MAX} sources")
    tz = spec.get("timezone")
    sources: dict[str, dict] = {}
    for key, item in items:
        if isinstance(item, str):
            if item in STARTER_SOURCES:
                source_name, body = key or item, copy.deepcopy(STARTER_SOURCES[item])
            elif get_entry(item) is not None:
                if item == "github.pr_search":
                    raise AppSpecError("github.pr_search needs a preset: use gh_review, gh_failing or gh_merged")
                source_name, body = key or _BY_ENTRY.get(item, item.split(".")[-1]), {"use": item}
            else:
                known = ", ".join(STARTER_SOURCES)
                raise AppSpecError(f"unknown source {item[:60]!r}; use one of: {known}")
        elif isinstance(item, dict):
            body = {k: copy.deepcopy(v) for k, v in item.items() if k != "name"}
            source_name = key or item.get("name")
            if not isinstance(source_name, str):
                raise AppSpecError("each source object needs a name")
        else:
            raise AppSpecError("each source is a short name or an object")
        entry = get_entry(body.get("use")) if isinstance(body.get("use"), str) else None
        if entry is None:
            raise AppSpecError(f"source {str(source_name)[:40]!r}: use must name a catalog entry")
        body.setdefault("fields", list(entry.fields))
        if tz and "tz" in entry.params:
            body.setdefault("params", {}).setdefault("tz", tz)
        if source_name in sources:
            raise AppSpecError(f"source name {source_name!r} is used twice")
        sources[source_name] = body
    description = spec.get("description") or ""
    manifest = {"schema": 1, "name": name.strip()[:NAME_MAX], "description": str(description)[:DESCRIPTION_MAX], "sources": sources}
    try:
        return validate_manifest(manifest)
    except ManifestError as exc:
        raise AppSpecError(str(exc)) from exc


def read_manifest(text: str | None) -> dict | None:
    """The project's omni-app.json, normalised, or None when it is missing,
    too large or invalid."""
    if not text or len(text.encode("utf-8", "replace")) > MANIFEST_MAX_BYTES:
        return None
    try:
        return validate_manifest(json.loads(text))
    except (ValueError, ManifestError, RecursionError):
        return None


def manifest_error(text: str | None) -> str:
    """Why the project's omni-app.json is not valid (the system's words plus
    the validator's, which name keys the worker wrote: shown fenced)."""
    if text is None:
        return "omni-app.json is missing"
    if len(text.encode("utf-8", "replace")) > MANIFEST_MAX_BYTES:
        return "omni-app.json is larger than 64 KB"
    try:
        validate_manifest(json.loads(text))
    except ManifestError as exc:  # a ValueError too: first
        return f"omni-app.json is not valid: {exc}"
    except (ValueError, RecursionError):
        return "omni-app.json is not valid JSON"
    return ""


def manifest_text(manifest: dict) -> str:
    return json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"


# -- the kit files ---------------------------------------------------------------


def tokens_from_globals(globals_css: str) -> str:
    """The Graphite tokens of frontend/src/styles/globals.css (the `:root,
    .light` and `.dark` blocks): custom properties and color-scheme only."""

    def block(selector: str) -> list[str]:
        m = re.search(r"(?m)^" + selector + r"\s*\{\n(.*?)\n\}", globals_css, re.S)
        if not m:
            raise ValueError(f"globals.css has no {selector!r} block")
        body = re.sub(r"/\*.*?\*/", "", m.group(1), flags=re.S)
        return [f"  {line.strip()}" for line in body.splitlines() if re.match(r"\s*(--[a-z0-9-]+|color-scheme)\s*:", line)]

    light = block(r":root,\n\.light")
    dark = block(r"\.dark")
    head = "/* Graphite tokens, light and dark. GENERATED from frontend/src/styles/globals.css by\n * app.gateway.code_jobs.app_kit.tokens_from_globals; a test keeps them in step. Do not edit. */\n"
    return head + ":root,\n.light {\n" + "\n".join(light) + "\n}\n\n.dark {\n" + "\n".join(dark) + "\n}\n"


def graphite_css() -> str:
    return TOKENS_PATH.read_text(encoding="utf-8") + "\n" + PRIMITIVES_PATH.read_text(encoding="utf-8")


def _ts_name(name: str) -> str:
    return name if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", name) else json.dumps(name)


def omni_dts(manifest: dict) -> str:
    """The shim's omni.d.ts with OmniSources generated from the manifest."""
    base = DTS_PATH.read_text(encoding="utf-8")
    lines = ["export interface OmniSources {"]
    for name, spec in manifest["sources"].items():
        lines.append(f"  /** {spec['use']}: {', '.join(spec['fields'])} */")
        lines.append(f'  {_ts_name(name)}: CatalogData["{spec["use"]}"];')
    lines.append("}")
    generated = "\n".join(lines)
    pattern = re.compile(r"// eslint-disable-next-line @typescript-eslint/no-empty-interface\nexport interface OmniSources \{\}")
    if not pattern.search(base):
        raise ValueError("omni.d.ts has no empty OmniSources to fill")
    return pattern.sub(lambda _m: generated, base, count=1)


def manifest_schema() -> dict:
    """The JSON Schema of omni-app.json, from the catalog."""
    entries = []
    for entry in CATALOG.values():
        params: dict[str, Any] = {}
        for pname, p in entry.params.items():
            if p.type == "integer":
                params[pname] = {"type": "integer", "minimum": p.minimum, "maximum": p.maximum}
            elif p.type == "enum":
                params[pname] = {"enum": list(p.values)}
            else:
                params[pname] = {"type": "string", "description": "an IANA time zone, for example Europe/London"}
        required = [n for n, p in entry.params.items() if p.required]
        entries.append(
            {
                "properties": {
                    "use": {"const": entry.id},
                    "params": {"type": "object", "additionalProperties": False, "properties": params, **({"required": required} if required else {})},
                    "fields": {"type": "array", "minItems": 1, "uniqueItems": True, "items": {"enum": list(entry.fields)}},
                    "refresh_s": {"type": "integer", "minimum": REFRESH_MIN_S, "maximum": REFRESH_MAX_S},
                },
                "required": ["use", "fields", *(["params"] if required else [])],
            }
        )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "omni-app.json",
        "type": "object",
        "additionalProperties": False,
        "required": ["schema", "name", "sources"],
        "properties": {
            "schema": {"const": 1},
            "name": {"type": "string", "minLength": 1, "maxLength": NAME_MAX},
            "description": {"type": "string", "maxLength": DESCRIPTION_MAX},
            "sources": {
                "type": "object",
                "minProperties": 1,
                "maxProperties": SOURCES_MAX,
                "propertyNames": {"pattern": "^[a-z][a-z0-9_]{0,31}$"},
                "additionalProperties": {"type": "object", "additionalProperties": False, "oneOf": entries},
            },
        },
    }


#: The kit's React helpers, render check and starter (paths under omni-kit/).
KIT_STATIC = ("omni-react.tsx", "check-render.mjs", "check-render-core.mjs", "render-entry.tsx")
#: Per catalog entry, the item field a starter list shows first.
_MAIN_FIELD = {
    "googlecalendar.events_today": "title",
    "github.pr_search": "title",
    "gmail.unread_subjects": "subject",
    "omni.ledger.today": "task",
    "omni.sessions.active": "title",
    "omni.automations.recent": "rule",
}

STARTER_MAIN = """import { createRoot } from "react-dom/client";

import "../omni-kit/graphite.css";
import App from "./App";

createRoot(document.getElementById("root")!).render(<App />);
"""

STARTER_VITE = """import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// One self-contained file: the system inlines dist/ into the app.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    modulePreload: false,
    cssCodeSplit: false,
    assetsInlineLimit: 100000000,
    rollupOptions: { output: { inlineDynamicImports: true } },
  },
});
"""


def _title(name: str) -> str:
    return name.replace("_", " ").capitalize()


#: Per catalog entry, a meta field for its rows (a time is formatted in the app's zone).
_META_FIELD = {
    "googlecalendar.events_today": ("start", True),
    "github.pr_search": ("repo", False),
    "gmail.unread_subjects": ("received_at", True),
    "omni.ledger.today": ("project", False),
    "omni.sessions.active": ("since", True),
    "omni.automations.recent": ("last_run", True),
}


def starter_app(manifest: dict) -> str:
    """src/App.tsx for this manifest: one kit Tile per source, each fresh view
    built from the kit's Row, Stat and Timeline, every time through zoned().
    The worker replaces the views and the layout."""
    views, tiles = [], []
    for name, spec in manifest["sources"].items():
        entry = get_entry(spec["use"])
        item_fields = [f for f in entry.item_fields if f in spec["fields"]] if entry else []
        main = _MAIN_FIELD.get(spec["use"]) if _MAIN_FIELD.get(spec["use"]) in item_fields else (item_fields[0] if item_fields else None)
        meta, is_time = _META_FIELD.get(spec["use"], (None, False))
        meta = meta if meta in item_fields else None
        comp = "".join(p.capitalize() for p in name.split("_")) + "View"
        lines = [f'function {comp}({{ data }}: {{ data: DataOf<"{name}"> }}) {{']
        body = []
        if spec["use"] == "googlecalendar.events_today" and {"start", "end"} <= set(item_fields):
            body.append("      <Timeline events={data.items} tz={TIME_ZONE} now={omni.now()} />")
        if "count" in spec["fields"]:
            body.append('      <Stat value={data.count} label="unread" />')
        if main:
            meta_expr = (f"item.{meta} ? z.formatTime(item.{meta}) : undefined" if is_time else f"item.{meta} ?? undefined") if meta else "undefined"
            link = "item.link ?? null" if "link" in item_fields else "null"
            body += [
                '      <ul className="omni-list">',
                "        {data.items.slice(0, 5).map((item, i) => (",
                f'          <Row key={{i}} title={{String(item.{main} ?? "")}} meta={{{meta_expr}}} href={{{link}}} />',
                "        ))}",
                "      </ul>",
                '      {data.items.length > 5 ? <p className="omni-muted omni-text-xs">{data.items.length - 5} more</p> : null}',
            ]
        if not body:
            body.append("      <p>{data.items.length}</p>")
        lines += ["  return (", "    <>", *body, "    </>", "  );", "}"]
        views.append("\n".join(lines))
        tiles.append(f'        <Tile source="{name}" title="{_title(name)}" View={{{comp}}} />')
    head = """import { Row, Stat, Tile, Timeline, zoned } from "../omni-kit/omni-react";
import { TIME_ZONE } from "../omni-kit/app-config";
import type { DataOf } from "../omni-kit/omni";

// A STARTER written by the system: replace the views and the layout. Keep
// the pattern: every hook at the top of a component, one Tile per source,
// each tile's fresh view a component of its own, the kit's Row / Stat /
// Timeline, every time through zoned(TIME_ZONE), "now" from omni.now().
const z = zoned(TIME_ZONE);
"""
    title = json.dumps(manifest["name"])[1:-1].replace("{", "&#123;").replace("<", "&lt;")
    app = (
        '\nexport default function App() {\n  return (\n    <main className="omni-page">\n      <header className="omni-header">\n'
        f'        <h1>{title}</h1>\n        <span className="omni-muted omni-text-xs">{{z.formatDay(omni.now())}}</span>\n      </header>\n      <div className="omni-grid">\n' + "\n".join(tiles) + "\n      </div>\n    </main>\n  );\n}\n"
    )
    return head + "\n" + "\n\n".join(views) + "\n" + app


def app_config(manifest: dict) -> str:
    """omni-kit/app-config.ts: the app's time zone (from its manifest)."""
    return f"// Written by the system from omni-app.json; do not edit.\nexport const TIME_ZONE = {json.dumps(app_time_zone(manifest))};\n"


MOCK_BANNER = "/* The kit's MOCK shim with sample data, for trying the page by hand (?state=, ?theme=). Never reference it from index.html:\n * the system adds it to its own mock build, and registration adds the real platform shim. */\n"


def kit_files(manifest: dict) -> dict[str, str]:
    """omni-kit/* for this manifest (paths relative to the project)."""
    return {
        f"{KIT_DIR}/APP_RULES.md": RULES_PATH.read_text(encoding="utf-8"),
        f"{KIT_DIR}/omni.d.ts": omni_dts(manifest),
        f"{KIT_DIR}/graphite.css": graphite_css(),
        f"{KIT_DIR}/mock-data.json": json.dumps(mock_data_file(manifest), indent=2, ensure_ascii=False) + "\n",
        f"{KIT_DIR}/omni-app.schema.json": json.dumps(manifest_schema(), indent=2) + "\n",
        f"{KIT_DIR}/omni-mock.js": MOCK_BANNER + mock_script(fixtures(manifest)),
        **{f"{KIT_DIR}/{name}": (HERE / name).read_text(encoding="utf-8") for name in KIT_STATIC},
        f"{KIT_DIR}/starter/App.tsx": starter_app(manifest),
        f"{KIT_DIR}/app-config.ts": app_config(manifest),
        f"{KIT_DIR}/starter/main.tsx": STARTER_MAIN,
        f"{KIT_DIR}/starter/vite.config.ts": STARTER_VITE,
    }


# -- sample data ------------------------------------------------------------------


#: The sample "now": a Wednesday at 10:20 in the app's own time zone. Every
#: sample time is written relative to it, with its real UTC offset, and the
#: mock shim's omni.now() returns it, so a timeline and "in 40 min" read the
#: same in every check and screenshot.
SAMPLE_DAY = date(2026, 1, 14)
SAMPLE_TIME = time(10, 20)


def app_time_zone(manifest: dict) -> str:
    """The app's time zone: the first `tz` param of its sources, else UTC."""
    for spec in manifest["sources"].values():
        tz = (spec.get("params") or {}).get("tz")
        if isinstance(tz, str) and tz:
            return tz
    return "UTC"


def sample_now(tz: str) -> datetime:
    return datetime.combine(SAMPLE_DAY, SAMPLE_TIME, tzinfo=zoneinfo.ZoneInfo(tz))


class _Clock:
    def __init__(self, tz: str) -> None:
        self.zone = zoneinfo.ZoneInfo(tz)

    def at(self, hm: str, days: int = 0) -> str:
        h, m = (int(x) for x in hm.split(":"))
        return datetime.combine(SAMPLE_DAY + timedelta(days=days), time(h, m), tzinfo=self.zone).isoformat()

    def day(self, days: int = 0) -> str:
        return (SAMPLE_DAY + timedelta(days=days)).isoformat()


def _pr(repo: str, number: int, title: str, updated: str, merged: str | None = None) -> dict:
    return {"repo": repo, "number": number, "title": title, "updated_at": updated, "merged_at": merged, "link": f"https://github.com/{repo}/pull/{number}"}


#: (title, start, end) of the timed sample events, local time on the sample day.
CALENDAR_EVENTS = (
    ("Team standup", "09:30", "09:45"),
    ("Design review: onboarding flow", "11:00", "12:00"),
    ("Lunch with Sam", "12:30", "13:15"),
    ("Roadmap planning", "14:00", "15:30"),
    ("1:1 with Priya", "16:00", "16:30"),
)


def _sample(entry_id: str, params: dict, tz: str = "UTC") -> dict:
    """Fresh projected data for one catalog entry, before field selection:
    some times today, some earlier this week, one overdue."""
    c = _Clock(tz)
    if entry_id == "googlecalendar.events_today":
        items = [{"title": "Release week", "start": c.day(), "end": c.day(1), "all_day": True}]
        items += [{"title": t, "start": c.at(a), "end": c.at(b), "all_day": False} for t, a, b in CALENDAR_EVENTS]
        return {"items": items}
    if entry_id == "github.pr_search":
        preset = params.get("preset")
        if preset == "failing":
            items = [_pr("acme/web", 479, "Upgrade the build to Node 22", c.at("08:55")), _pr("acme/infra", 35, "Rotate the staging certificates", c.at("06:30"))]
        elif preset == "merged_7d":
            items = [
                _pr("acme/web", 470, "Dark mode for the settings page", c.at("16:20", -1), c.at("16:20", -1)),
                _pr("acme/api", 1281, "Cache the feature flags", c.at("11:02", -1), c.at("11:02", -1)),
                _pr("acme/docs", 58, "Document the export API", c.at("15:45", -2), c.at("15:45", -2)),
                _pr("acme/web", 466, "Remove the legacy onboarding banner", c.at("10:10", -4), c.at("10:10", -4)),
            ]
        else:
            items = [
                _pr("acme/web", 482, "Add keyboard shortcuts to the command palette", c.at("08:12")),
                _pr("acme/api", 1290, "Paginate the audit log endpoint", c.at("07:40")),
                _pr("acme/mobile", 77, "Fix a crash when the clipboard is empty", c.at("17:05", -1)),
            ]
        # `more`: the search had more than the cap (show "20+"); `dropped`:
        # results left out because they had no usable number.
        return {"items": items, "more": str(preset or "").startswith("merged"), "dropped": 0}
    if entry_id == "gmail.unread_subjects":
        subjects = [
            ("Contract renewal: two questions before Friday", c.at("08:41")),
            ("Your expense report needs a receipt", c.at("07:58")),
            ("Interview loop for the design role", c.at("18:20", -1)),
            ("Re: venue options for the offsite", c.at("16:05", -1)),
            ("Quarterly numbers, first draft", c.at("11:30", -2)),
        ]
        items = [{"subject": s, "received_at": t, "link": f"https://mail.google.com/mail/u/0/#inbox/18c{i}a2b4f00d1e{i}"} for i, (s, t) in enumerate(subjects)]
        return {"count": 12, "count_capped": False, "items": items}
    if entry_id == "omni.ledger.today":
        return {
            "items": [
                {"bucket": "overdue", "task": "Write the hiring plan", "project": "Team", "status": "todo", "due_date": c.day(-1), "link": "/workspace/projects/p-team"},
                {"bucket": "stuck", "task": "Move billing to the new provider", "project": "Payments", "status": "blocked", "due_date": None, "link": "/workspace/projects/p-payments"},
                {"bucket": "moved", "task": "Draft the launch post", "project": "Launch", "status": "doing", "due_date": c.day(6), "link": "/workspace/projects/p-launch"},
                {"bucket": "moved", "task": "Review the security checklist", "project": "Launch", "status": "done", "due_date": None, "link": "/workspace/projects/p-launch"},
            ]
        }
    if entry_id == "omni.sessions.active":
        return {
            "items": [
                {"tool": "OpenCode", "title": "web", "display_state": "working", "known": "observed", "since": c.at("08:50")},
                {"tool": "Coding agent", "title": "api", "display_state": "waiting-on-user", "known": "inferred", "since": c.at("08:20")},
            ]
        }
    if entry_id == "omni.automations.recent":
        return {
            "items": [
                {"rule": "Inbox triage", "last_run": c.at("08:00"), "outcome": "delivered", "next_run": c.at("12:00"), "trigger": "schedule"},
                {"rule": "Morning brief", "last_run": c.at("07:00"), "outcome": "delivered", "next_run": c.at("07:00", 1), "trigger": "schedule"},
                {"rule": "Weekly report", "last_run": c.at("09:00", -2), "outcome": "failed", "next_run": c.at("09:00", 5), "trigger": "schedule"},
                {"rule": "Blocked session", "last_run": c.at("10:15"), "outcome": "suppressed", "next_run": None, "trigger": "event"},
            ]
        }
    return {"items": []}


def fixtures(manifest: dict) -> dict:
    """The mock shim's data: for each source, its fresh and empty `data`
    (only the fields the manifest selected, as the bridge would send)."""
    tz = app_time_zone(manifest)
    sources = {}
    for name, spec in manifest["sources"].items():
        entry = get_entry(spec["use"])
        if entry is None:
            continue
        fresh = _sample(entry.id, spec["params"], tz)
        limit = spec["params"].get("limit")
        if isinstance(limit, int):
            fresh["items"] = fresh["items"][:limit]
        empty = {"items": [], **({"count": 0, "count_capped": False} if "count" in entry.top_fields else {}), **({"more": False, "dropped": 0} if entry.meta_fields else {})}
        sources[name] = {"use": entry.id, "fresh": select(fresh, entry, spec["fields"]), "empty": select(empty, entry, spec["fields"])}
    return {"now": sample_now(tz).isoformat(), "time_zone": tz, "reason": MOCK_REASON, "sources": sources}


def mock_data_file(manifest: dict) -> dict:
    """mock-data.json for the worker: the four states of every source, as the
    app receives them (times are moved to today by the mock shim)."""
    data = fixtures(manifest)
    out: dict[str, Any] = {
        "about": (
            "Sample data the system builds and checks your app with, in the app's time zone. omni.now() returns the sample now "
            "(a Wednesday, 10:20 local) in the mock build; fetched_at is 4 minutes before it. "
            "Open the built page with ?state=fresh|empty|not_connected|failed and ?theme=light|dark."
        ),
        "now": data["now"],
        "time_zone": data["time_zone"],
        "sources": {},
    }
    for name, f in data["sources"].items():
        out["sources"][name] = {
            "use": f["use"],
            "fresh": {"source": name, "state": "fresh", "data": f["fresh"], "fetched_at": "(4 minutes before omni.now())", "stale": False, "reason": None},
            "empty": {"source": name, "state": "empty", "data": f["empty"], "fetched_at": "(4 minutes before omni.now())", "stale": False, "reason": None},
            "not_connected": {"source": name, "state": "not_connected", "data": None, "fetched_at": None, "stale": False, "reason": None},
            "failed": {"source": name, "state": "failed", "data": None, "fetched_at": None, "stale": False, "reason": MOCK_REASON},
        }
    return out


def sentinels(data: dict) -> dict[str, list[str]]:
    """Per source, one sample string per item (its longest name-like field),
    and the count when it is the tile's number: the check counts how many of
    a tile's sample items show in the fresh state."""
    out: dict[str, list[str]] = {}
    for name, f in data["sources"].items():
        fresh = f["fresh"]
        needles: list[str] = []
        for item in (fresh.get("items") or [])[:ITEMS_MAX]:
            names = [item.get(k) for k in ("title", "subject", "task", "rule", "tool") if isinstance(item.get(k), str) and len(item.get(k)) >= 3]
            if names:
                needles.append(max(names, key=len)[:60])
        out[name] = list(dict.fromkeys(needles))[:24]
    return out


def expected_times(data: dict) -> dict:
    """The calendar's timed sample events: each start in the app's time zone
    (accepted as H:MM or HH:MM, 12 or 24 hour) and, for a zone other than UTC,
    the same instants in UTC (a page showing those is in the wrong zone)."""
    tz = data.get("time_zone") or "UTC"
    zone = zoneinfo.ZoneInfo(tz)
    local, shifted = [], []
    for f in data["sources"].values():
        if f["use"] != "googlecalendar.events_today":
            continue
        for item in f["fresh"].get("items") or []:
            start = item.get("start")
            if item.get("all_day") or not isinstance(start, str) or "T" not in start:
                continue
            at = datetime.fromisoformat(start)
            here, utc = at.astimezone(zone), at.astimezone(zoneinfo.ZoneInfo("UTC"))
            local.append(_time_words(here))
            if tz != "UTC" and utc.utcoffset() != here.utcoffset():
                shifted.append(_time_words(utc))
        break
    return {"local": local, "shifted": shifted}


def _time_words(at: datetime) -> dict:
    """Regex sources for H:MM in 24 or 12 hour form, and a label."""
    h12 = at.hour % 12 or 12
    words = {f"{at.hour}:{at.minute:02d}", f"{h12}:{at.minute:02d}"}
    pattern = "(?<![0-9])(?:" + "|".join(f"0?{w}" for w in sorted(words)) + ")(?![0-9])"
    return {"re": pattern, "label": f"{h12}:{at.minute:02d} {'AM' if at.hour < 12 else 'PM'}"}


def mock_script(data: dict) -> str:
    """The mock shim with its data, as one script."""
    blob = json.dumps(data, ensure_ascii=True, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e")
    return f"window.__OMNI_MOCK__ = {blob};\n" + MOCK_SHIM_PATH.read_text(encoding="utf-8")
