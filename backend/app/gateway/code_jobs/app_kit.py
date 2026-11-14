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
REFERENCE = "2026-01-15T00:00:00+00:00"
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


def starter_app(manifest: dict) -> str:
    """src/App.tsx for this manifest: one kit Tile per source, each with a
    small fresh view. The worker replaces the views and the layout."""
    views, tiles = [], []
    for name, spec in manifest["sources"].items():
        entry = get_entry(spec["use"])
        item_fields = [f for f in entry.item_fields if f in spec["fields"]] if entry else []
        main = _MAIN_FIELD.get(spec["use"]) if _MAIN_FIELD.get(spec["use"]) in item_fields else (item_fields[0] if item_fields else None)
        comp = "".join(p.capitalize() for p in name.split("_")) + "View"
        lines = [f'function {comp}({{ data }}: {{ data: DataOf<"{name}"> }}) {{']
        if "count" in spec["fields"]:
            lines.append('  return <p className="omni-kpi-value">{data.count}</p>;')
        elif main:
            lines += [
                "  return (",
                '    <ul className="omni-list">',
                "      {data.items.map((item, i) => (",
                f'        <li key={{i}}><span className="omni-list-main">{{String(item.{main} ?? "")}}</span></li>',
                "      ))}",
                "    </ul>",
                "  );",
            ]
        else:
            lines.append("  return <p>{data.items.length}</p>;")
        lines.append("}")
        views.append("\n".join(lines))
        tiles.append(f'        <Tile source="{name}" title="{_title(name)}" View={{{comp}}} />')
    head = """import { Tile } from "../omni-kit/omni-react";
import type { DataOf } from "../omni-kit/omni";

// A STARTER written by the system: replace the views and the layout. Keep
// the pattern: every hook at the top of a component, one Tile per source,
// each tile's fresh view a component of its own.
"""
    title = json.dumps(manifest["name"])[1:-1].replace("{", "&#123;").replace("<", "&lt;")
    app = (
        '\nexport default function App() {\n  return (\n    <main className="omni-page">\n      <header className="omni-header">\n'
        f'        <h1>{title}</h1>\n      </header>\n      <div className="omni-grid">\n' + "\n".join(tiles) + "\n      </div>\n    </main>\n  );\n}\n"
    )
    return head + "\n" + "\n\n".join(views) + "\n" + app


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
        f"{KIT_DIR}/starter/main.tsx": STARTER_MAIN,
        f"{KIT_DIR}/starter/vite.config.ts": STARTER_VITE,
    }


# -- sample data ------------------------------------------------------------------


def _t(hm: str, day: str = "2026-01-15") -> str:
    return f"{day}T{hm}:00+00:00"


def _pr(repo: str, number: int, title: str, updated: str, merged: str | None = None) -> dict:
    return {"repo": repo, "number": number, "title": title, "updated_at": updated, "merged_at": merged, "link": f"https://github.com/{repo}/pull/{number}"}


_GITHUB_SAMPLES = {
    "review_requested": [
        _pr("acme/web", 482, "Add keyboard shortcuts to the command palette", _t("08:12")),
        _pr("acme/api", 1290, "Paginate the audit log endpoint", _t("07:40")),
        _pr("acme/mobile", 77, "Fix a crash when the clipboard is empty", _t("09:05", "2026-01-14")),
    ],
    "failing": [
        _pr("acme/web", 479, "Upgrade the build to Node 22", _t("08:55")),
        _pr("acme/infra", 35, "Rotate the staging certificates", _t("06:30")),
    ],
    "merged_7d": [
        _pr("acme/web", 470, "Dark mode for the settings page", _t("16:20", "2026-01-14"), _t("16:20", "2026-01-14")),
        _pr("acme/api", 1281, "Cache the feature flags", _t("11:02", "2026-01-13"), _t("11:02", "2026-01-13")),
        _pr("acme/docs", 58, "Document the export API", _t("15:45", "2026-01-12"), _t("15:45", "2026-01-12")),
        _pr("acme/web", 466, "Remove the legacy onboarding banner", _t("10:10", "2026-01-10"), _t("10:10", "2026-01-10")),
    ],
}


def _sample(entry_id: str, params: dict) -> dict:
    """Fresh projected data for one catalog entry, before field selection."""
    if entry_id == "googlecalendar.events_today":
        return {
            "items": [
                {"title": "Release week", "start": "2026-01-15", "end": "2026-01-16", "all_day": True},
                {"title": "Team standup", "start": _t("09:30"), "end": _t("09:45"), "all_day": False},
                {"title": "Design review: onboarding flow", "start": _t("11:00"), "end": _t("12:00"), "all_day": False},
                {"title": "Lunch with Sam", "start": _t("12:30"), "end": _t("13:15"), "all_day": False},
                {"title": "Roadmap planning", "start": _t("14:00"), "end": _t("15:30"), "all_day": False},
                {"title": "1:1 with Priya", "start": _t("16:00"), "end": _t("16:30"), "all_day": False},
            ]
        }
    if entry_id == "github.pr_search":
        items = copy.deepcopy(_GITHUB_SAMPLES.get(params.get("preset"), _GITHUB_SAMPLES["review_requested"]))
        # `more`: the search had more than the cap (show "20+"); `dropped`:
        # results without a placeable repository, left out.
        return {"items": items, "more": str(params.get("preset", "")).startswith("merged"), "dropped": 0}
    if entry_id == "gmail.unread_subjects":
        subjects = [
            ("Contract renewal: two questions before Friday", "08:41"),
            ("Your expense report needs a receipt", "07:58"),
            ("Interview loop for the design role", "18:20", "2026-01-14"),
            ("Re: venue options for the offsite", "16:05", "2026-01-14"),
            ("Quarterly numbers, first draft", "11:30", "2026-01-13"),
        ]
        items = [{"subject": s[0], "received_at": _t(s[1], s[2] if len(s) > 2 else "2026-01-15"), "link": f"https://mail.google.com/mail/u/0/#inbox/18c{i}a2b4f00d1e{i}"} for i, s in enumerate(subjects)]
        return {"count": 12, "count_capped": False, "items": items}
    if entry_id == "omni.ledger.today":
        return {
            "items": [
                {"bucket": "overdue", "task": "Write the hiring plan", "project": "Team", "status": "todo", "due_date": "2026-01-13", "link": "/workspace/projects/p-team"},
                {"bucket": "stuck", "task": "Move billing to the new provider", "project": "Payments", "status": "blocked", "due_date": None, "link": "/workspace/projects/p-payments"},
                {"bucket": "moved", "task": "Draft the launch post", "project": "Launch", "status": "doing", "due_date": "2026-01-20", "link": "/workspace/projects/p-launch"},
                {"bucket": "moved", "task": "Review the security checklist", "project": "Launch", "status": "done", "due_date": None, "link": "/workspace/projects/p-launch"},
            ]
        }
    if entry_id == "omni.sessions.active":
        return {
            "items": [
                {"tool": "OpenCode", "title": "web", "display_state": "working", "known": "observed", "since": _t("08:50")},
                {"tool": "Coding agent", "title": "api", "display_state": "waiting-on-user", "known": "inferred", "since": _t("08:20")},
            ]
        }
    if entry_id == "omni.automations.recent":
        return {
            "items": [
                {"rule": "Inbox triage", "last_run": _t("08:00"), "outcome": "delivered", "next_run": _t("12:00"), "trigger": "schedule"},
                {"rule": "Morning brief", "last_run": _t("07:00"), "outcome": "delivered", "next_run": _t("07:00", "2026-01-16"), "trigger": "schedule"},
                {"rule": "Weekly report", "last_run": _t("09:00", "2026-01-12"), "outcome": "failed", "next_run": _t("09:00", "2026-01-19"), "trigger": "schedule"},
                {"rule": "Blocked session", "last_run": _t("10:15", "2026-01-14"), "outcome": "suppressed", "next_run": None, "trigger": "event"},
            ]
        }
    return {"items": []}


def fixtures(manifest: dict) -> dict:
    """The mock shim's data: for each source, its fresh and empty `data`
    (only the fields the manifest selected, as the bridge would send)."""
    sources = {}
    for name, spec in manifest["sources"].items():
        entry = get_entry(spec["use"])
        if entry is None:
            continue
        fresh = _sample(entry.id, spec["params"])
        limit = spec["params"].get("limit")
        if isinstance(limit, int):
            fresh["items"] = fresh["items"][:limit]
        empty = {"items": [], **({"count": 0, "count_capped": False} if "count" in entry.top_fields else {}), **({"more": False, "dropped": 0} if entry.meta_fields else {})}
        sources[name] = {"use": entry.id, "fresh": select(fresh, entry, spec["fields"]), "empty": select(empty, entry, spec["fields"])}
    return {"reference": REFERENCE, "reason": MOCK_REASON, "sources": sources}


def mock_data_file(manifest: dict) -> dict:
    """mock-data.json for the worker: the four states of every source, as the
    app receives them (times are moved to today by the mock shim)."""
    data = fixtures(manifest)
    out: dict[str, Any] = {
        "about": "Sample data the system builds and checks your app with. `fetched_at` is set when the page loads; sample times move to today. Open the built page with ?state=fresh|empty|not_connected|failed and ?theme=light|dark.",
        "sources": {},
    }
    for name, f in data["sources"].items():
        out["sources"][name] = {
            "use": f["use"],
            "fresh": {"source": name, "state": "fresh", "data": f["fresh"], "fetched_at": "(4 minutes before the page loads)", "stale": False, "reason": None},
            "empty": {"source": name, "state": "empty", "data": f["empty"], "fetched_at": "(4 minutes before the page loads)", "stale": False, "reason": None},
            "not_connected": {"source": name, "state": "not_connected", "data": None, "fetched_at": None, "stale": False, "reason": None},
            "failed": {"source": name, "state": "failed", "data": None, "fetched_at": None, "stale": False, "reason": MOCK_REASON},
        }
    return out


def sentinels(data: dict) -> dict[str, list[str]]:
    """Per source, sample strings of which at least one must show in the
    fresh state (a tile that shows none of its data is missing). Counts are
    sentinels too, since an inbox tile may show only its number."""
    out: dict[str, list[str]] = {}
    for name, f in data["sources"].items():
        fresh = f["fresh"]
        needles: list[str] = []
        for item in (fresh.get("items") or [])[:ITEMS_MAX]:
            for key in ("title", "subject", "task", "rule", "project", "repo"):
                value = item.get(key)
                if isinstance(value, str) and len(value) >= 3:
                    needles.append(value[:60])
            if isinstance(item.get("number"), int):
                needles.append(f"#{item['number']}")
        if isinstance(fresh.get("count"), int) and fresh["count"] >= 10:
            needles.append(str(fresh["count"]))
        out[name] = list(dict.fromkeys(needles))[:24]
    return out


def mock_script(data: dict) -> str:
    """The mock shim with its data, as one script."""
    blob = json.dumps(data, ensure_ascii=True, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e")
    return f"window.__OMNI_MOCK__ = {blob};\n" + MOCK_SHIM_PATH.read_text(encoding="utf-8")
