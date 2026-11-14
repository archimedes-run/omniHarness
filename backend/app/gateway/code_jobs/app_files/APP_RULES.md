<!-- omni-harness:app-rules v1 (tracked: backend/app/gateway/code_jobs/app_files/APP_RULES.md; written into omni-kit/ by the gateway for every app-mode job) -->
# Rules for building an OmniHarness app

This job builds an **app**: one small, self-contained web page that shows the
person's own data in OmniHarness. The page never touches the network; the
platform hands it read-only data through `window.omni`. These rules come on
top of the workspace rules (AGENTS.md). The system checks every one it can
measure and refuses to register an app that breaks them.

## What is in `omni-kit/` (written by the system; do not edit)

| File | What it is |
| --- | --- |
| `APP_RULES.md` | This file. |
| `omni.d.ts` | Types for `window.omni`, with `OmniSources` generated from your sources: `await omni.data("calendar")` is typed. Data shapes come from here; do not guess them. |
| `graphite.css` | The Graphite design tokens for light and dark as CSS variables, plus dashboard primitives (`omni-grid`, `omni-tile`, `omni-kpi`, `omni-list`, `omni-badge`, `omni-state`, `omni-chart`, ...). Import it first. |
| `mock-data.json` | Sample data for every source in the four states. The system builds your app against it; read it to see real shapes. |
| `omni-app.schema.json` | The JSON Schema of `omni-app.json`. |
| `omni-shim.js` | A copy of the platform shim, for reading only. The system inlines its own copy as the first script when it registers the app; never include, copy or edit it. |

`omni-app.json` (in the project folder) is the app's manifest: its name and
the data sources it reads. The system wrote a starter. You may change `name`
and `description`; change `sources` only if the job asks for it, and only to
entries in the schema. The system validates it.

## Build output

- The build must produce **`dist/index.html`**; the system inlines every
  local script, stylesheet, image and font it references into ONE HTML file of
  at most **2 MB**. So: no code splitting, no dynamic `import()`, no lazy
  routes, no web workers, images and fonts small (or inline SVG).
- Vite: set `base: './'`, `build.modulePreload: false`, `build.cssCodeSplit: false`,
  `build.assetsInlineLimit: 100000000`, and
  `build.rollupOptions.output.inlineDynamicImports: true`.
- Use `window.omni` as a global. Do not add any script that defines it.
- TypeScript: add `"omni-kit/omni.d.ts"` to `tsconfig` `include` (or
  `/// <reference path="../omni-kit/omni.d.ts" />` in your entry file).

## Never (registration refuses these, or the page breaks under the app's CSP)

- **No network of any kind**: no `fetch`, `XMLHttpRequest`, `EventSource`,
  `WebSocket`, `navigator.sendBeacon`, WebRTC, remote `<script>`, `<link>`,
  `<img>`, fonts or CSS `url()`/`@import`. Google Fonts, CDNs and icon fonts
  included. All data comes from `omni.data(...)`.
- **No HTML from strings**: no `innerHTML`, `outerHTML`, `insertAdjacentHTML`,
  `document.write`, `dangerouslySetInnerHTML`, `DOMParser` with HTML, `eval`,
  `new Function`, `setTimeout("string")`. The app runs under Trusted Types
  with no policy, so these throw. Build DOM with `createElement` /
  `textContent`, or JSX.
- **No frames or popups**: no `<iframe>`, `srcdoc`, `<object>`, `<embed>`,
  `window.open`, `target="_blank"`, forms that submit.
- **No navigation**: every link goes through `omni.open(url)` (plain
  `<a href>` clicks are routed there for you). Only `https` links on the
  hosts of your sources' catalog entries, or `/workspace/...`, open.
- No `localStorage`, `sessionStorage`, cookies or IndexedDB (the frame has an
  opaque origin; they throw). Keep state in memory.
- No chart, UI or icon library that fetches, uses `eval`, or draws on canvas
  only. Draw charts as **inline SVG** yourself.

## Every tile shows the four honest states

Each source is one of `fresh`, `empty`, `not_connected`, `failed`
(`omni.describe(result)` returns these words; use them):

| `state` | The tile shows |
| --- | --- |
| `fresh` | The data, and **"updated 4 min ago"** from `fetched_at` (`"updated " + omni.ago(r.fetched_at)`). If `stale` is true, add "May be out of date". |
| `not_connected` | **"Not connected"** and a **Connect** button calling `omni.connect(name)`. Never start sign-in yourself. |
| `failed` | **"Can't tell"** and the `reason`. If `data` is not null, show it marked stale. Never "Nothing today": a failure is not an empty day. |
| `empty` | **"Nothing today"** (or the tile's own wording of nothing, such as "No PRs waiting on you"). Only for `empty`. |

While the first answer is on its way, show a quiet placeholder of the tile's
size (`omni-skeleton`), not a spinner over the page. Never print `undefined`,
`null`, `NaN`, `Invalid Date` or `[object Object]`. Handle a missing field.
Listen for `omni.onUpdate` and re-render that tile.

## Design (the system's checks and the design checklist)

- **Graphite only**: colours from `graphite.css` variables (`var(--card)`,
  `var(--muted-foreground)`, `var(--chart-series)`, ...), never a hex,
  `rgb()` or named colour of your own. Both themes come free: the shim
  toggles `.dark` on `<html>`; subscribe with `omni.onTheme` if you draw
  anything that needs to know.
- **Contrast AA**: body text at least 4.5:1, large text (24 px, or 18.66 px
  bold) 3:1, in BOTH themes. Muted text only on `--card` or `--background`.
- **Responsive from 360 px**: no sideways page scroll at 360, 560 or 1280 px;
  `omni-grid` stacks tiles; long titles truncate or wrap inside their tile;
  wide tables scroll inside their own box.
- **Type**: a clear hierarchy (page title 20 px, tile title 14 px semibold,
  KPI 28 px, meta 12 px). No text under 12 px.
- **Touch targets** at least 24 px (buttons 32 px).
- **Spacing rhythm** on a 4 px grid (4, 8, 12, 16, 24); tiles aligned to the
  grid; equal gaps.
- **Charts where they help** (a load across the day, pass/fail, runs over
  time), drawn in SVG with a `viewBox` that contains every shape, stroke and
  label, `width: 100%; height: auto`; a title or label, axis or value labels,
  and a legend when there is more than one series. A chart never replaces the
  numbers it shows: give it a text alternative.

## What the system checks after your build

1. `npm run build` exits 0 and `dist/index.html` exists.
2. The build inlines into one file of at most 2 MB, with no remote reference.
3. Your source files contain none of the "Never" APIs above.
4. The page is loaded with the sample data in a headless browser at 360, 560
   and 1280 px, in light and dark, with every source in each of the four
   states, under the app's real CSP: no sideways overflow, no clipped chart,
   no uncaught error, no blocked request, no frame, contrast AA, and the tile
   words above in each state. Screenshots go to the assistant, who may ask
   for up to three design passes against the checklist.
