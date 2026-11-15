# Implementation Plan: Artifacts

**Branch**: `012-artifacts` (one PR per slice) | **Date**: 2026-11-14 | **Spec**: [spec.md](spec.md)

## Summary

Five slices now and one after spec 008. Each slice ships backend and frontend together and ends with a live check in Chrome. S1 adds the artifact record, the chat tools, the store page and the static kinds. S2 moves code kinds into the locked frame with sandbox pre-builds. S3 adds exports, S4 the document and spreadsheet editors and dashboards, S5 whiteboard, share links and MCP-UI. Promote to App, with app data on AI Lists and the Home tile, follows spec 008 (owner decision, 2026-11-14).

## What exists today (read from the code)

| Area | Where | What it does now | What 012 changes |
|---|---|---|---|
| Artifact files and preview | `backend/app/gateway/routers/artifacts.py` | Serves thread files from `outputs`; HTML preview with a 10-minute preview token (`PREVIEW_TOKEN_TTL_SECONDS`), root-relative URL rewriting and an in-memory storage shim (`_storage_shim_tag`); preview CSP allows `'unsafe-inline'` scripts and `connect-src 'self'`; active types forced to download on the plain route; artifact manifests (`ArtifactManifest`, `list_artifact_manifests`) and project file listing | Stays for thread files and coding-job work in progress. Store artifacts get their own routes and the locked frame (FR-016). |
| Preview sessions | `backend/app/gateway/routers/previews.py` | Starts, proxies, stops and restarts a live dev server in the sandbox | Unchanged; a published result becomes an `html` artifact (FR-012). |
| Panel UI | `frontend/src/components/workspace/artifacts/` (`artifact-file-list.tsx`, `artifact-file-detail.tsx`, `context.tsx`, `artifact-trigger.tsx`), `frontend/src/core/artifacts/` | File list, code view (CodeMirror), markdown (streamdown), HTML in an iframe with `sandbox="allow-scripts allow-forms"` | Panel shows store artifacts by id and version; code kinds use the locked frame. |
| `present_files` | `backend/packages/harness/omniharness/tools/builtins/present_file_tool.py`, rule in `app/policy/default_rules.yaml` (Tier 1, `reads_private: false`) | Makes `outputs` files visible | Also records artifacts (FR-012). |
| Coding jobs | `backend/app/gateway/code_jobs/` (`runner.py`, `layout.py`, `layout_probe.py`, `app_mode.py`, `app_kit.py`, `app_checks.py`) | Builds in the sandbox, publishes, layout check, app mode with kit and checks | S2 reuses the build and layout check for react artifacts; the after-008 slice adds the adapt brief. |
| Apps | `backend/app/gateway/apps/` (`registry.register_app`, `bundle.py`, `manifest.py`, `bridge.py`, `catalog.py`), `frontend/src/core/apps/` (`host-controller.ts`, `protocol.schema.json`, `shim/`), `frontend/src/app/workspace/apps/` | 011 platform: manifest requires 1 to N sources (`manifest.py`), hash over sources, frame CSP, host port protocol, library, pins via `/api/preferences/app-pins` | S2 reuses the frame and bundle inlining for artifacts; after 008 the manifest allows zero sources and gains `lists`. |
| Policy | `app/policy/default_rules.yaml`, `lineage.py` (`ORIGIN_USER`, `ORIGIN_CONTENT`, `TRUSTED_TOOL_RESULTS`), `provenance.py`, `grants.py` | Tiers, unmatched tool refused, lineage of turns | S1 adds four rules (spec FR-005). |
| Exports | `frontend/src/components/workspace/export-trigger.tsx` (chat as Markdown or JSON); `pypdf==7.0.1` direct in `backend/packages/harness/pyproject.toml`; `markitdown[all,xlsx]` brings `python-pptx`, `openpyxl`, `xlsxwriter`, `mammoth`, `defusedxml`, `lxml` transitively (`backend/uv.lock`) | No artifact export; no PDF or DOCX writer | S3 adds producers (FR-040). |
| Frontend renderers | `frontend/package.json`: streamdown 2.7.1, shiki, CodeMirror 6, katex, `@xyflow/react`, Radix primitives, `cmdk`, `motion`, `lucide-react`, `class-variance-authority`, `tailwind-merge`; `mermaid` 11.14.0 and `dompurify` only transitively in `pnpm-lock.yaml` | Chat markdown and code | S1 adds the chart renderer (in repo) and mermaid as a direct dependency. |
| Sandbox | `docker/sandbox/Dockerfile` (upstream AIO image, browser and Python used by the layout probe; network only through the registries proxy) | Builds and probes | No image change. React builds install their stack through the registries proxy (already approved); exports use the existing browser. |

## Dependencies needing the owner's OK

The rule: no new download without the owner's approval; installs inside the sandbox for building apps are already approved. Promoting a package already in a lockfile to a direct dependency downloads nothing but is listed so the owner sees it.

| Package | Side | Licence | Slice | New download? | Purpose |
|---|---|---|---|---|---|
| `mermaid` | frontend | MIT | S1 | No (in `pnpm-lock.yaml` 11.14.0 via streamdown) | Mermaid kind |
| `defusedxml` | gateway | PSF-2.0 | S1 | No (in `uv.lock`) | Safe SVG parsing for the sanitiser |
| `xlsxwriter` | gateway | BSD-2-Clause | S3 | No (in `uv.lock`) | `.xlsx` (write-only, no macros unless asked, never asked) |
| `python-pptx` | gateway | MIT | S3 | No (in `uv.lock`) | `.pptx`, native charts |
| `python-docx` | gateway | MIT | S3 | **Yes** | `.docx` |
| `lexical`, `@lexical/react` | frontend | MIT | S4 | **Yes** | Document editor (chosen over `@mdxeditor/editor`, which wraps Lexical with more weight) |
| `react-grid-layout` | frontend | MIT | S4 | **Yes** | Dashboard drag-and-resize tile grid |
| `@excalidraw/excalidraw` | platform viewer bundle (built in repo, served to the locked frame) | MIT | S5 | **Yes** | Whiteboard viewer and editor |

Not adopted: Monaco (CodeMirror 6 is already present and needs no workers or CSP change); a data-grid library (the grid is 008's, spec FR-025); `dompurify` as a direct dependency (SVG is shown only as `<img>` after an allowlist pass). The preferred UI stack for generated react artifacts and apps (Radix UI, Tailwind with `tailwind-merge`, CVA and an animate plugin, `lucide-react`, `motion`, `cmdk`, `vaul`, `@xyflow/react`, esbuild) is installed inside the sandbox per build and is not a frontend dependency.

## Slices

Every slice: backend and frontend in one PR; tests through `create_app()`; sabotage observed for every guard it adds; live dogfood in Chrome in its own tab, read-only on real accounts, with test chats moved into the "Tests" folder afterwards.

### S1: Model, chat tools, store page, static kinds

- **Backend**: new `app/gateway/artifacts_store/` (models, repo over the shared SQL store, blob store per FR-036, lineage capture, caps, lazy importer FR-037, SVG sanitiser FR-014); new router `app/gateway/routers/artifact_store.py` (`/api/artifacts...`: list and search, get, versions, content, owner edit, restore, rename, pin, duplicate, archive, delete with count check) registered in `create_app()`; tools `artifact_create`, `artifact_update`, `artifact_read`, `artifact_list` under `omniharness/tools/builtins/`; four rules in `default_rules.yaml`; `present_file_tool.py` records artifacts.
- **Frontend**: `core/artifacts/` gains the store API and hooks; `app/workspace/artifacts/` store page; artifact card message part in `components/workspace/messages/`; panel by id and version with History; renderers for markdown, code, svg, mermaid, chart (in-repo SVG), image; sidebar entry; "Ask to change" and "Use in a new chat" as message metadata.
- **Tests**: version immutability and stale base (state read back); lineage from turn not args; `artifact_read` not trusted (FR-008); tool surface has no promote, delete or share; path built only from hash; caps; importer idempotent; XSS canaries per static kind; source gate for HTML sinks.
- **Gates**: standard gates below; **independent security review** (policy tiers, storage paths, host rendering).
- **Dogfood**: create one of each static kind from chat, update, undo, edit markdown in place, find it in the store, open the chat that made it.

### S2: Code kinds in the locked frame, versions for builds

- **Backend**: artifact frame route `/api/artifacts/{id}/versions/{n}/frame.html` with the artifact profile (FR-031), reusing `apps/bundle.py` inlining and the 011 scan; react build step (gateway-written script run in the chat's sandbox, esbuild through the registries proxy, 120 s cap, `build_state`); layout check hook (FR-018); `html` file sets from coding-job publishes.
- **Frontend**: locked-frame component shared with `core/apps/host-controller.ts` (artifact message set FR-019, size, "Open link?" dialog); inline live cards; panel switches html preview from the old iframe.
- **Tests**: 011 hostile-app suite against the artifact frame; profile diff test (only `script-src` and Trusted Types differ from the app profile); build failure keeps last good version; refused messages logged.
- **Gates**: standard; **independent security review** (frame).
- **Dogfood**: a react todo artifact and a vanilla HTML game from chat, both in panel and store, at 360 and 1280 px.

### S3: Exports

- **Backend**: `app/gateway/artifacts_store/exports/` (producers per FR-040 in a limited subprocess; browser render in the sandbox with non-local requests aborted; office and PDF post-checks FR-042, FR-043; caps FR-044; dedupe by triple); export routes.
- **Frontend**: Export menu in panel and store; progress and failure states.
- **Tests**: one fixture per format opened by its reader (`openpyxl`, `python-pptx`, `python-docx`, `pypdf`); each post-check refusal with sabotage; CSV injection prefix.
- **Gates**: standard; **independent security review** (exported files leave the system).
- **Dogfood**: export a document to DOCX, PDF and PPTX, a chart to XLSX, and open each in an office suite and a browser.

### S4: Document and spreadsheet editors, dashboards

- **Frontend**: Lexical editor for `omni-doc/1` with conversion both ways; spreadsheet editor on 008's grid component (if 008 has not landed, the grid is built at `components/workspace/grid/` as the component 008 will use, so there is one grid); formula parser (FR-025); dashboard tiles with `react-grid-layout`, layout edits as new versions.
- **Backend**: schema validators for doc, sheet and dashboard; formula allowlist shared with exports.
- **Tests**: round trips; formula allowlist refusals; stale edit refused; contrast suite both themes.
- **Gates**: standard. No security review unless the slice touches the frame or storage paths.
- **Dogfood**: edit a document and a sheet in place, rearrange a dashboard, Undo each.

### S5: Whiteboard, share view, MCP-UI

- **Whiteboard**: platform viewer bundle (Excalidraw, fonts bundled, embeddables off) built in repo, served to the locked frame under the app profile; scene in and edits out over the port.
- **Share**: `artifact_shares` table, owner-only create and revoke, `/s/{token}` route outside the workspace with rate limit and `noindex` (FR-057).
- **MCP-UI**: UI resources from MCP tool results as inline cards in the locked frame, actions as suggestions (FR-058).
- **Gates**: standard; **independent security review** (sharing exposes content without a session; frame).
- **Dogfood**: draw and reopen a whiteboard; open a share link in a private window, then revoke it and see 404.

### After 008: Promote to App, app data on lists, Home tile

- **Preconditions**: 008 built and its gaps G1 to G6 (spec section E) closed.
- **Backend**: promote route (owner session and CSRF, refuses the internal token); adapt brief in `code_jobs/app_mode.py`; `apps/manifest.py` allows zero sources and adds `lists` to the hash only when present; list creation at grant; row bridge routes calling 008's service in process as `app:{id}`; Remove archives app and lists; links between artifact and app.
- **Frontend**: Promote dialog; Add to OmniHarness card; row messages in the host controller and shim (`protocol.schema.json`); `localStorage` wrapper over a key/value list; slug route; command menu entry; "Your apps" row on Home (`components/workspace/home/`).
- **Tests**: Security rows for promotion and rows; a content-led suggestion never starts a job; old grants still valid after the hash change (sources-only apps); kanban survives restart.
- **Gates**: standard; **independent security review** (confirmations, frame protocol, policy).
- **Dogfood**: promote a kanban artifact, Add, pin, open from Home, add cards, restart the gateway, see the cards and the rows under Lists; Remove and Restore.

## Gates (each PR)

1. CI green; `scripts/ci/check_docs.py` clean.
2. Sabotage observed for every guard the PR adds.
3. Tests run on the tracked example config plus test overrides, never on a local-only flag; caps and CSP ship in tracked code.
4. Assert on state: versions, archives, exports and grants are read back from the store.
5. UI PRs: screenshots in both themes at 360 and 1280 px, contrast suite AA.
6. Independent review where marked; no HIGH open.
7. Any regression against main blocks the merge.

## Deploy notes

- Additive tables created on first use; rolling back leaves stored artifacts inert and thread files untouched.
- The importer runs in the background and never blocks a request.
- Frontend restarts for S1, S2, S4, S5 and after-008: announce first; open tabs need a refresh.
- No nginx change: artifact routes are under `/api/`, the store under `/workspace/`; `/s/{token}` (S5) is a frontend route that calls a public gateway route under `/api/`.

## Risks

- **Model HTML breaks under the app profile at promotion**: the adapt job rewrites it; the report says what changed; failure is honest.
- **Pre-build latency for react**: first build installs through the registries proxy; the sandbox's package cache makes later builds seconds.
- **Lexical and Excalidraw weight**: both lazy-loaded; Excalidraw lives only in the frame bundle.
- **008 slips**: S1 to S5 are unaffected; promotion waits by design.

## Open questions (recommended defaults)

| # | Question | Recommended default |
|---|---|---|
| Q1 | Build 008 (AI Lists) right after 012 S2, or finish 012 S3 to S5 first? | 008 right after S2: promote to App is the stated goal and it needs 008; S3 to S5 can follow, and S4 then reuses 008's grid. |
| Q2 | Approve the new downloads (`python-docx`, `lexical`, `@lexical/react`, `react-grid-layout`, `@excalidraw/excalidraw`) and the four lockfile promotions? | Approve. If `python-docx` is declined, S3 writes DOCX with an in-repo OOXML writer for the `omni-doc/1` subset; the others have no cheap substitute and their kinds wait. |
| Q3 | Storage caps | 1 GB per owner, 2 MB per text version, 10 MB per image or file, 200 versions per artifact, all in tracked defaults. |
| Q4 | Existing chat outputs: copy into the store or reference? | Copy files up to 10 MB (deduplicated); larger ones stay as references marked "lives in its chat". |
| Q5 | Share links (S5) | Off until S5; per version; expire in 7 days (max 30); static and code kinds only; never apps or their data. |
| Q6 | Home tile for promoted apps | A launcher tile (name, icon, last opened, status) first; the live mini-view tile later. |
