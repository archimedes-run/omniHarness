# Feature Specification: Artifacts (kinds, store, exports, promote to App)

**Feature Branch**: `012-artifacts` (one PR per slice of [plan.md](plan.md))

**Created**: 2026-11-14

**Status**: Draft. Every open question carries a recommended default so no slice is blocked; the owner may overturn any of them before the slice that uses it starts. Promotion being the owner's button only, code never getting network or same-origin access, and promotion waiting for Spec 008 (AI Lists) so promoted apps keep their data in lists (owner decision, 2026-11-14), are the owner's decisions and are written as requirements.

**Input**: the owner wants "all the artifact types, and usable right from the chat", an Artifact store, and "artifacts like live apps can be promoted to Apps when I say so: when a web app live gets promoted to app it becomes a part of the interface of omniharness".

**Builds on**: the artifacts panel and preview route (`app/gateway/routers/artifacts.py`, `components/workspace/artifacts/*`), preview sessions (`app/gateway/routers/previews.py`), `present_files` (`omniharness/tools/builtins/present_file_tool.py`), coding jobs and their publish step and layout check (`app/gateway/code_jobs/`, spec 009 Slice 1, Slice 1b), the Apps platform (spec [011](../011-apps/spec.md), contract [api.md](../011-apps/api.md): frame rules FR-016 to FR-023, registration FR-028, held versions FR-028a, library and pins FR-029), AI Lists (spec 008 on branch `008-ai-lists`, `specs/008-ai-lists/spec.md`: typed columns FR-005, cell origin FR-064, archive FR-067, change history FR-069, per-list access FR-072 to FR-075, import mapping FR-030, table UI FR-050 and FR-114), the policy layer (`app/policy/default_rules.yaml`, `lineage.py`, `provenance.py`, `grants.py`), the button-only card rule (010 FR-016) and the display sanitiser (005 Amendment 1).

## Terms

- **Artifact**: one record the owner can find again, with an ordered list of immutable **versions**.
- **Static kind**: content that is data. The trusted host page renders it without running any of it.
- **Code kind**: content that is a program. It runs only in the **locked frame**.
- **Locked frame**: the Spec 011 frame (opaque origin, `connect-src 'none'`, no navigation, no nested frames, port-only messaging). Two CSP profiles share it: the **artifact profile** and the **app profile** (FR-031).
- **Lineage**: `user` (the owner's own turn or click) or `content` (made after the turn read outside content, per `lineage.py`; `unknown` counts as content).

## User Scenarios & Testing *(mandatory)*

### User Story 1: Make and change an artifact from chat (Priority: P1)

The owner asks "draft a one-page project brief" or "chart last week's CI pass rate". The assistant calls `artifact_create`; the thread shows an artifact card at that turn (kind icon, title, "v1", a live preview for static kinds) and the side panel opens it. "Make the title shorter" produces v2 through `artifact_update`; the card at the first turn still shows v1 with "Latest: v2". History lists every version with Restore; Undo on the latest version restores the previous one as a new version.

**Independent Test**: from a fresh chat, create a markdown artifact, update it twice, Undo once: four versions exist, the latest equals v2's content hash, no version was rewritten.

**Acceptance Scenarios**:

1. **Given** an update whose `base_version` is not the latest, **When** it is applied, **Then** it is refused with the current version number and nothing is written.
2. **Given** a version made after the turn read an email, **When** its card renders, **Then** it is labelled "made after reading outside content" with the source named.
3. **Given** the owner presses "Ask to change" on v3, **When** they type a request, **Then** the turn carries a reference `{artifact_id, version: 3}` as structured metadata (not text), and the resulting update uses base version 3.

### User Story 2: Edit in place (Priority: P1)

For markdown, code, document and spreadsheet the owner edits directly in the panel or the store. Save makes a new version with lineage `user` and origin `owner_edit`. Leaving with unsaved edits asks first.

### User Story 3: The Artifact store (Priority: P1)

`/workspace/artifacts` lists every artifact across chats: search by title and text, filter by kind, Pinned, Recent, By chat, Archived. Each row opens a preview; actions are Rename, Pin, Duplicate, Export, Open the chat that made it, Use in a new chat, Archive, and (from Archived) Delete permanently.

**Acceptance Scenarios**:

1. **Given** a chat that produced files before this feature, **When** the store is first opened, **Then** those files appear as artifacts with origin `import`, linked to their chat.
2. **Given** "Use in a new chat", **When** the new chat starts, **Then** the artifact is attached as context the assistant reads through `artifact_read` (fenced, as data); its text is never placed in the owner's message.
3. **Given** Delete permanently, **When** confirmed in the dialog that names the artifact and its version count, **Then** the record, versions, unreferenced blobs and share links are removed; without the confirmation nothing is removed.

### User Story 4: Export (Priority: P1)

From any artifact the owner picks Export and a format; a new file artifact appears in the store, linked to its source version, and downloads.

### User Story 5: Promote a web app to an App (Priority: P1, after 008)

A kanban board made in chat works in the panel. The owner presses **Promote to App**, picks a name and an icon, and confirms. A job adapts it in the sandbox (no network; its cards kept in an app-owned list), the system checks it, and the gateway registers it. An **Add to OmniHarness** card appears (or the Spec 011 **App access** card when it reads data sources), listing the list it keeps. After the press the app is in the Apps library, can be pinned in the sidebar, opens at its own route, appears as a tile on Home, and keeps its cards between visits; the same cards are visible as rows under Lists.

**Independent Test**: promote a kanban artifact that uses `localStorage` and one `fetch` to an outside URL. The report lists the dropped call; after Add, cards added in the app survive a reload and a gateway restart and appear as rows of its list; the assistant asking to promote produces only a suggestion chip.

**Acceptance Scenarios**:

1. **Given** the assistant writes "I can promote this for you", **When** the turn ends, **Then** at most a suggestion chip is shown; no job starts until the owner presses the button.
2. **Given** a promoted app, **When** its source artifact gets v5, **Then** the artifact shows "Update the app"; pressing it registers a held version shown as "Use version N" (011 FR-028a); the served version keeps running until then.
3. **Given** Remove from OmniHarness, **When** confirmed, **Then** grants end, cache rows go, pins and the Home tile go, the app is archived, and its lists are archived under 008's 30-day restore rule; the source artifact is untouched.

### User Story 6: Share a read-only view (Priority: P3)

The owner creates a share link for one version. The recipient sees that version only, read-only, with no app data and no way to reach the owner's workspace.

### Edge Cases

- A react build fails: the version is stored with state `build_failed` and the log tail; the card says so; the previous good version stays the one shown.
- Quota reached: create and update are refused with the numbers; nothing partial is written.
- An artifact is archived while open in a chat: the card shows "Archived" with Restore.
- A chat is deleted: its artifacts remain (store copies), with "chat deleted" in place of the link.
- A frame reloads itself or navigates: torn down as in 011 FR-021.
- Two tabs edit the same artifact: the second save is refused as stale (base version).

## Requirements *(mandatory)*

### A. Artifact model and chat tools

- **FR-001**: An artifact record MUST hold `id` (random, URL-safe), `kind`, `title` (≤ 120 chars, display-sanitised), `owner_id`, `origin_thread_id`, `origin_turn_id`, `created_at`, `updated_at`, `latest_version`, `pinned`, `archived_at`, `promoted_app_id`, and `imported_from` (thread path) when imported.
- **FR-002**: A version MUST be immutable and hold `n`, `content_hash` (SHA-256 of the canonical content), `size`, `lineage` (`user` or `content`, with the content source when known), `origin` ∈ {`tool`, `owner_edit`, `restore`, `import`, `export`, `build`}, `base_version`, `created_at`, `note` (≤ 300 chars, labelled as the assistant's words), and for code kinds `build_state` ∈ {`pending`, `ok`, `build_failed`}.
- **FR-003**: Kinds MUST be exactly: `markdown`, `code`, `svg`, `mermaid`, `chart`, `image`, `spreadsheet`, `document`, `dashboard` (static); `html`, `react` (code); `whiteboard` (data, rendered by a platform viewer in the locked frame, FR-033); `file` (anything else: download only). Each kind has a content schema (FR-020 to FR-030).
- **FR-004**: Caps (tracked defaults, overridable upward only by tracked config): text content ≤ 2 MB per version; `image` and `file` ≤ 10 MB; react sources ≤ 2 MB and built bundle ≤ 2 MB; ≤ 200 versions per artifact (beyond that the oldest versions not referenced by an app, share or export are pruned, never the first or latest); per-owner total ≤ 1 GB. A write over any cap MUST be refused before anything is stored.
- **FR-005**: The model's tool surface MUST gain exactly four tools, ruled in `default_rules.yaml`:

  | Tool | Tier | `reversible` | `reads_private` | Why |
  |---|---|---|---|---|
  | `artifact_create(kind, title, content, note?)` | 2 | true | false | a write inside the owner's workspace, undoable; disclosed on the final reply |
  | `artifact_update(id, base_version, content \| edits[], note?)` | 2 | true | false | always a new version; Undo restores |
  | `artifact_read(id, version?)` | 1 | true | (unset: private) | the content may be the owner's data |
  | `artifact_list(query?, kind?, limit?)` | 1 | true | (unset: private) | titles may be private |

  `edits[]` is a list of exact `{old, new}` replacements for text kinds. No tool MAY archive, delete, share, export to outside, or promote: those have no rule, so the policy layer refuses them (rule 1 of `default_rules.yaml`). In scheduled runs the Tier 2 tools need a standing grant as any Tier 2 call does.
- **FR-006**: `artifact_update` MUST refuse a stale `base_version`, a target the owner does not own, an archived target, and a kind change. It never overwrites a version.
- **FR-007**: Lineage MUST be computed server-side from the turn (`lineage.py` origins) at the tool call, never from tool arguments.
- **FR-008**: `artifact_read` results MUST be returned fenced as data (`<artifact id= version= kind= lineage=>…</artifact>` with the existing untrusted-content framing), and `artifact_read` MUST NOT be in `TRUSTED_TOOL_RESULTS`: a turn that read an artifact is content-led for later cards.
- **FR-009**: The tool result MUST carry `{artifact_id, version}`; the thread renders an artifact card at that turn bound to that version, with "Latest: vN" when newer exists. The side panel opens the card's version; History lists versions with lineage, origin and note.
- **FR-010**: Restore and Undo MUST create a new version with origin `restore` (010 rule). Owner edits (markdown, code, document, spreadsheet) MUST save as a new version with origin `owner_edit`, lineage `user`, carrying the base version; a stale base is refused.
- **FR-011**: "Ask to change" MUST attach `{artifact_id, version}` as message metadata of the owner's turn; the assistant receives it as a reference and reads the content through `artifact_read`.
- **FR-012**: `present_files` MUST keep working; each presented file in `/mnt/user-data/outputs` becomes (or updates) an artifact with kind detected by extension and content sniffing (`.md` markdown, `.svg` svg, `.csv` spreadsheet, images, `.html` html, source files code, else `file`). A coding job's published web app becomes an `html` artifact holding its file set.

### B. Rendering by trust

- **FR-013**: Static kinds MUST be rendered by the host with no raw-HTML sink: markdown through the chat's renderer with raw HTML off and links through the existing link handler; code through the existing CodeMirror/shiki viewers; svg and mermaid ONLY as `<img>` from a sanitised SVG (scripts never run in an image); chart, spreadsheet, document and dashboard as React elements built from their data schema. A source gate MUST fail on any new `dangerouslySetInnerHTML` or `innerHTML` under `components/workspace/artifacts/**` and the store page beyond an allowlist of reviewed sites.
- **FR-014**: SVG MUST be sanitised by the gateway on write with an element and attribute allowlist (no `script`, `foreignObject`, event attributes, `style` with `url(`, external `href`/`xlink:href`, `<use>` of external documents), parsed with `defusedxml`; a failing SVG is refused with the reason.
- **FR-015**: Mermaid MUST render client-side with `securityLevel: "strict"` and HTML labels off, and the output SVG MUST pass the same allowlist (FR-014, ported to the frontend) before becoming an `<img>` data URL.
- **FR-016**: Code kinds MUST render only in the locked frame served by the gateway at `/api/artifacts/{id}/versions/{n}/frame.html`, embedded with `sandbox="allow-scripts"` exactly, under the artifact profile (FR-031). The existing preview iframe (`allow-scripts allow-forms`, `connect-src 'self'`) MUST NOT be used for store artifacts.
- **FR-017**: React artifacts MUST be pre-built in the chat's sandbox (decision, see "Compile where"): a gateway-written build script bundles the sources with esbuild and the preferred stack (installed through the sandbox's registries proxy, already approved) into one self-contained HTML document; the gateway (not the worker) inlines, hashes scripts, scans (011 FR-018 list), injects the shim and stores it. Build ≤ 120 s; failure stores `build_failed` with the log tail.
- **FR-018**: Anything interactive (html, react, whiteboard) MUST pass the system layout check (PR #182) at 360 and 1280 px before its card shows a live preview; a failing check shows the result and an Open anyway button.
- **FR-019**: Frame → host messages for artifacts MUST be exactly `ready`, `size {height}` (inline cards, clamped 120 to 1200 px), and `open {url}` (https only; opens after the owner confirms the host's own "Open link?" dialog naming the host). Anything else is dropped and logged `artifact_message_refused`. Nothing a frame sends ever reaches the model, starts a tool call or answers a card; a future "ask the assistant" message would appear only as a suggestion chip the owner must press, with lineage `content`.

#### Content schemas (data, never code)

- **FR-020** `markdown`: UTF-8 text. **FR-021** `code`: `{language, text}`. **FR-022** `svg`: sanitised SVG text. **FR-023** `mermaid`: source text.
- **FR-024** `chart` (`omni-chart/1`): `{type: bar|line|area|scatter|pie|donut, title, x: {field, type: category|time|number}, series: [{field, label}] (≤ 8), data: [rows] (≤ 5,000), units?}`; no expressions or callbacks. Rendered by an in-repo SVG renderer using Graphite tokens, both themes.
- **FR-025** `spreadsheet` (`omni-sheet/1`): `{sheets: [{name, columns, rows}]}` (≤ 20 sheets, ≤ 100,000 cells); cell values string, number, boolean or null; formulas as `{f: "=SUM(A1:A9)"}` limited to an allowlist (arithmetic, references, ranges, `SUM AVERAGE MIN MAX COUNT COUNTA IF ROUND ABS CONCAT`), evaluated by an in-repo parser, never by `eval`. **Spreadsheets and AI Lists are one table system**: a spreadsheet artifact is a versioned snapshot (whole sheet per version, formulas, no agents); a list is live rows with per-cell history and AI columns. They share 008's typed column vocabulary and grid component; "Open as a list" (after 008) creates a list through 008's import mapping (FR-030), and a list's export can be saved as a spreadsheet artifact. No second grid or row store is built.
- **FR-026** `document` (`omni-doc/1`): a block tree (heading 1 to 4, paragraph with bold, italic, code and link marks, bulleted and numbered lists, quote, code block, table, image by blob reference, page break). Links `https:` or `mailto:` only.
- **FR-027** `dashboard` (`omni-dash/1`): `{tiles: [{id, x, y, w, h, type: kpi|chart|table|markdown}]}` on a 12-column grid, each tile's content in its kind's schema; data is fixed at creation (live data belongs to Apps). A custom-code dashboard is a `react` artifact.
- **FR-028** `image`: PNG, JPEG, WebP or GIF, re-encoded by the gateway (Pillow, existing) to strip metadata; served `Content-Type` from the re-encode. **FR-029** `html`: one HTML document or a file set (≤ 50 files, ≤ 2 MB) inlined at registration. **FR-030** `react`: `{entry, files}` (TSX/TS/CSS) plus the built bundle.

#### Frame profiles and the Trusted Types tension

- **FR-031**: Both profiles MUST keep 011 FR-016 to FR-018 except where stated. The **app profile** is 011 FR-016 verbatim (hashed scripts, `require-trusted-types-for 'script'; trusted-types 'none'`). The **artifact profile** differs only in `script-src 'unsafe-inline'` instead of hashes and no Trusted Types directives, because model-written HTML relies on inline handlers and `innerHTML`. This is acceptable only because the artifact frame holds nothing: no bridge, no store, no data from the owner's accounts, no network, no same-origin access, no navigation; an injection there can only misrender its own page. Promotion MUST move code to the app profile (FR-047).
- **FR-032**: How Spec 011 resolved the tension, kept here: app bundles are built ahead of time as single files with no `eval`, `new Function`, dynamic import or HTML-from-string sinks (kit rules), so hashed `script-src` and `trusted-types 'none'` hold; React renders through DOM APIs and `dangerouslySetInnerHTML` is forbidden by the kit.
- **FR-033**: `whiteboard` content is an Excalidraw scene (JSON data). It MUST be shown by a platform-built viewer/editor bundle (shipped by this repo, not written by the model) running in the locked frame under the app profile, receiving the scene and returning edits over the port. Embeddable elements and remote images are disabled; fonts are bundled.

#### Compile where (decided)

Pre-compile in the sandbox. Compiling in the frame needs `eval`/`new Function` or `blob:` scripts (refused by hashed `script-src`, `trusted-types 'none'` and the 011 scan), downloads a multi-megabyte compiler on every open, and needs module resolution that would want network. Pre-building costs seconds per version in a sandbox the chat already has, reuses the 011 registration path, and makes the artifact and the promoted app the same kind of document.

### C. The Artifact store

- **FR-034**: `/workspace/artifacts` MUST list the owner's artifacts with search (title and text content of text kinds), kind filter, Pinned, Recent, By chat and Archived views, and a sidebar entry. Graphite tokens only, both themes, AA, usable at 360 px.
- **FR-035**: Actions MUST be Open (preview, History), Rename, Pin, Duplicate (new artifact from one version, origin noted), Export, Open the chat that made it, Use in a new chat (FR-011 reference, never pasted text), Archive (the default removal; reversible), Restore from archive, and Delete permanently (from Archived only; a dialog naming the artifact and version count; POST carries the version count shown and is refused if it differs).
- **FR-036**: Metadata MUST live in the gateway's shared SQL store (tables `artifacts`, `artifact_versions`, `artifact_exports`, `artifact_shares`). Content MUST be stored content-addressed under `{base_dir}/users/{user_id}/artifacts/blobs/sha256/{h[0:2]}/{h}`, a path built only from the owner id and the hex hash; titles and client input never reach a path. A blob is deleted only when no version references it.
- **FR-037**: Existing chat outputs MUST be indexed lazily: on first store open, and on each thread's next turn, a background pass records each file under the thread's `outputs` (and each artifact manifest) as an artifact with origin `import`, copying files ≤ 10 MB into the blob store (dedup by hash) and recording larger ones as references marked "lives in its chat". Indexing is idempotent by `(thread_id, path, content_hash)`.
- **FR-038**: All store routes MUST require the owner's session; mutating routes require CSRF; no route accepts a filesystem path from the client.

### D. Exports

- **FR-039**: Export MUST produce a new `file` artifact linked to `(source artifact, version, format)`; the same triple is served from the existing export instead of rebuilt.
- **FR-040**: Formats and producers:

  | From | Formats | Producer, where |
  |---|---|---|
  | markdown, document | `.md`, `.html`, `.docx`, `.pdf`, `.pptx` (sections become slides) | gateway: `python-docx`, `python-pptx`; PDF in the sandbox browser |
  | spreadsheet | `.xlsx`, `.csv` (one per sheet), `.pdf` | gateway: `xlsxwriter`; PDF in the sandbox browser |
  | chart | `.svg`, `.png`, `.csv`, `.xlsx` and `.pptx` with a native chart | gateway; PNG in the sandbox browser |
  | svg, mermaid | `.svg`, `.png`, source `.md` | gateway (sanitised SVG); PNG in the sandbox browser |
  | dashboard | `.pdf`, `.png` | sandbox browser |
  | html, react | self-contained `.html` (network-blocking CSP in a meta tag), `.png`, `.pdf`, sources `.zip` | gateway; PNG and PDF in the sandbox browser |
  | whiteboard | `.svg`, `.png`, `.excalidraw` | viewer bundle in the sandbox browser |
  | code | source file, `.md` | gateway |

- **FR-041**: Gateway producers MUST run from the typed content only (no model code runs in the gateway), in a subprocess with a 60 s and 512 MB limit. Browser rendering MUST run in the chat's sandbox (or a fresh one for the store) using the image's existing browser with every non-`file:`/`data:` request aborted; no package is installed for exports.
- **FR-042**: Office files MUST contain no macros, no external relationships, no remote images and no fields that fetch. A post-check MUST unzip each output and refuse it on any `vbaProject.bin`, `TargetMode="External"`, external-link part, OLE object, or `DDE`/`WEBSERVICE`/`HYPERLINK` formula. Links in documents are written as visible text plus URL. Spreadsheet text starting with `= + - @` that is not an allowlisted formula is written as text, and `.csv` cells starting with those characters are prefixed with `'`.
- **FR-043**: PDF output MUST be checked with `pypdf` (existing) and refused on `/JavaScript`, `/JS`, `/OpenAction`, `/Launch`, `/EmbeddedFile` or `/URI` actions (links appear as text).
- **FR-044**: Caps: 120 s per export, output ≤ 25 MB, 3 concurrent exports per owner; exceeding any is a clear failure, never a partial file.

### E. Promote to App (slice "after 008"; depends on spec 008)

Specified now so S1 to S5 do not paint it into a corner; built only after AI Lists exists.

- **FR-045**: Eligible kinds are `html`, `react` and `dashboard`, plus imported coding-job web apps. **Promote to App** MUST be an owner-only button: a POST from the owner's browser session with CSRF carrying `{artifact_id, version, name, icon, pin}`. The route MUST refuse the internal service token, scheduled runs and any tool path. The assistant, a frame or content can at most produce a suggestion chip (lineage `content` when content-led) that opens the same dialog; nothing starts until the owner presses its button.
- **FR-046**: The dialog MUST show the name (default: the artifact title), an icon chosen from a fixed list of icon names (no uploaded images), and an unticked "Pin to sidebar" box.
- **FR-047**: Promotion MUST run a coding job in app mode (011 FR-025) with an **adapt** brief and the artifact version as the starting project. The adapter MUST: rebuild as a single file under the app profile (remove inline handlers and HTML-from-string sinks); replace every network call either with a catalog source read through `omni.data` (catalog entries only; the manifest names them) or by removing it; move persistence to app-owned lists (FR-051); and produce a **report** listing each removed call, each mapped source and each list with its columns. A program that needs a server (its own backend in the sandbox) MUST either be rewritten client-side over lists or fail with that reason.
- **FR-048**: The system checks (011 FR-026, scan FR-018) MUST pass; then the gateway registers the app (011 FR-028) with `source_artifact = (id, version)`, `origin = ("user", None)` for the owner's press, and the artifact's lineage shown on the card.
- **FR-049**: The manifest MUST allow zero sources. A version with no sources and no lists still needs a grant on its manifest hash, raised as an **Add to OmniHarness** card (button only) stating "This app shows no data from your accounts." With sources, the 011 App access card is raised; lists add one line each (FR-051).
- **FR-050**: "Part of the interface" MUST mean, after the grant: listed in the Apps library; pinnable in the sidebar (011 FR-029); its own route `/workspace/apps/{id}` plus a stable owner-chosen slug alias `/workspace/apps/s/{slug}` (unique per owner); an entry in the command menu; and a **Home tile**: a launcher card in a "Your apps" row on Home with name, icon, last opened and a status dot. A live mini-view tile (the app's own `#tile` view in its own locked frame on Home) is Later.

#### App data on AI Lists (no separate store)

- **FR-051**: A promoted app's saved state MUST live in **app-owned lists** (spec 008 lists), declared in the manifest as `lists: {name: {columns: [{name, type, options?}], access: "read" | "read_write"}}` with 008's column types (FR-005: text, number, boolean, datetime, link, single-select). The manifest hash becomes SHA-256 of canonical `{sources, lists}` when `lists` is present and stays 011's sources-only hash when absent, so existing grants are unchanged. On the first grant the gateway creates each list (named "<app name>: <list name>", owned by the app). The card says, per list: "Keeps a table '<name>' (columns …) in Lists. The assistant cannot see it unless you give an agent access."
- **FR-052**: Frame → host messages over the port: `rows.query {id, list, filter?, sort?, page?}` (008 FR-061 operators, pages ≤ 200), `rows.insert {id, list, rows}` (≤ 50 rows), `rows.update {id, list, row_id, base, cells}`, `rows.archive {id, list, row_id}`; host → frame: `rows.result {id, ok, rows?, next?, reason?}`. `list` MUST name a list of the served version's approved manifest; writes need `read_write`; each message is a plain JSON object ≤ 64 KB, schema-validated at both ends (011 FR-022, FR-023), ≤ 10 writes per second. No token reaches the frame.
- **FR-053**: The host MUST serve these through `/api/apps/{id}/lists/{list}/rows` routes with the owner's session (CSRF on writes); the gateway calls the 008 list service in process (never loopback HTTP) as the principal `app:{id}` acting for the owner, refused unless the served version has an active grant for that manifest hash. Row data reached this way MUST NOT enter any thread, run, memory or model context (011 FR-012); 008's per-agent access (default `none` for every agent on an app-owned list) decides whether an agent may ever read it, and only the owner can change that.
- **FR-054**: For code that used `localStorage`, the kit MUST offer a `localStorage`-compatible object over one app-owned list with columns `key` (text, unique) and `value` (text, ≤ 64 KB), preloaded at `init` (≤ 1,000 rows) and written through asynchronously. Adapters SHOULD prefer real typed columns (a kanban's title, status as single-select, order as number) so the rows are useful under Lists.
- **FR-055**: Updates: a new artifact version shows **Update the app** (owner button), which reruns FR-047 with `hold=True`; the result is a held version behind a "Use version N" card (011 FR-028a). A changed `lists` declaration is a new manifest hash and needs a new grant; adding columns is allowed, removing or retyping a column is refused (008 FR-005 forbids type changes), so the adapter must add a new column instead.
- **FR-056**: **Remove from OmniHarness** (confirm) MUST end grants, delete bridge cache rows, remove pins, the slug and the Home tile, and archive the app and its lists (008 FR-067: restorable 30 days, then purged, FR-068). The source artifact is untouched and shows "Was promoted (removed)". Both records link to each other while the app exists.

#### What 008 must expose (requirements back to 008, not edits to it)

Reused as specified: lists and typed columns (008 FR-005, FR-006), cell origin (FR-064), change history (FR-069), archive and purge (FR-067, FR-068), service-side access enforcement (FR-073), the table UI and its 10,000-row behaviour (FR-050, FR-114), import mapping (FR-030). Gaps 008 must close before this slice starts:

| # | Gap in 008 as written | Needed |
|---|---|---|
| G1 | Access levels exist only per agent (FR-072); identity comes from the calling agent (FR-071) | A non-agent principal `app:{id}` with `read` or `read_write` per list, established by the gateway, enforced by the same service check |
| G2 | Agent access is through the `omni-lists` MCP tools (FR-060) | An in-process service API (query, insert, update by row id, archive by row id) the gateway bridge calls with no MCP and no loopback (the internal token is per worker) |
| G3 | Cell origin is user, agent, processing or found (FR-064) | Origin `app` (with the app id) in cells and change history |
| G4 | A list must have an assigned agent (FR-001) | App-owned lists with no assigned agent and no AI columns, and an `owner_app_id` so they are listed under the app and archived with it |
| G5 | Updates are by filter with an expected count (FR-065); delete is two steps with a token (FR-066) | Update and archive by row id with a per-row version for stale-write refusal; the app path only archives (restorable), never purges |
| G6 | Lists created from the UI, templates or import | Creation from a manifest declaration by the gateway at grant time, with column add only |

Until 008 closes G1 to G6, promotion stays unbuilt; no interim key-value store is built.

### F. Sharing and MCP-UI (S5)

- **FR-057**: A share link MUST be created only by the owner's button for one version; a 256-bit random token stored hashed; expiry default 7 days (max 30); revocable; listed per artifact. `/s/{token}` serves a read-only page with no owner session needed, `noindex`, `Referrer-Policy: no-referrer`, rate-limited, rendering static kinds by the same host renderers and code kinds in the locked frame (artifact profile). Promoted apps, bridge data and store data are never shareable.
- **FR-058**: MCP-UI: a UI resource returned by an MCP tool MAY be rendered as an inline artifact card in the locked frame (artifact profile) with the FR-019 messages only; any action it requests is shown as a suggestion with lineage `content`.

### Key Entities

Artifact, ArtifactVersion, Blob (content-addressed), ArtifactExport, ArtifactShare, PromotionJob (artifact version, job id, report); after 008, app-owned lists (008 lists with `owner_app_id`).

## Security

| Threat | Control | Sabotage check (must fail when the control is removed) |
|---|---|---|
| Artifact code reaches the network or the owner's session | FR-016, FR-031 (opaque origin, `connect-src 'none'`, `sandbox="allow-scripts"`) | Run 011's hostile-app suite against `frame.html` (artifact profile); add `allow-same-origin` or `connect-src 'self'` and the listener or cookie test fails. |
| XSS in the host via a static kind | FR-013, FR-014, FR-015 | Markdown with raw `<img onerror>`, SVG with `<script>` and `foreignObject`, mermaid label with HTML, chart label with markup: none executes (a canary global stays unset). Render the SVG inline instead of as `<img>`, or turn raw HTML on: the canary fires. Add an `innerHTML` site: the source gate fails. |
| Model promotes, deletes or shares | FR-005 (no rules, no tools), FR-045 route refuses service token | Call each route with the internal token: 403. Add a rule `artifact_promote`: the tool-surface test fails. |
| Content-led turn treated as the owner's | FR-007, FR-008, FR-011 | A turn that `artifact_read`s then raises a Tier 3 card: card is a suggestion. Add `artifact_read` to `TRUSTED_TOOL_RESULTS`: test fails. Paste artifact text into the owner message on "Use in a new chat": test asserting the message has only the reference fails. |
| Silent overwrite | FR-002, FR-006, FR-010 | Stale `base_version` is refused and the store read back is unchanged; remove the base check: test fails. |
| Path traversal in storage | FR-036, FR-038 | A title of `../../x` and a crafted import path stay inside the owner's blob root; build a path from the title: test fails. |
| Quota exhaustion | FR-004, FR-044 | Over-cap create and export each refused with nothing stored; remove each cap: its test fails. |
| Malicious office or PDF export | FR-042, FR-043 | Fixture output with `vbaProject.bin`, an external relationship, a `WEBSERVICE` formula, a CSV `=cmd` cell, a PDF `/OpenAction`: each refused or neutralised; skip the post-check: test fails. |
| Promoted app keeps network or same-origin | FR-047, FR-048 (app profile, scan) | An adapted bundle still containing `fetch("https://…")` to a non-catalog host fails registration; drop the scan step: test fails. |
| App rows cross apps or reach a model (after 008) | FR-051 to FR-053, 008 FR-073 | App B queries app A's list: refused; drop the manifest check in host and bridge: test fails. Thread state after app writes holds no row value; an agent with default access `none` gets 008's clean denial. |
| Forged row messages (after 008) | FR-052 (schema both ends, port only) | Oversized insert, unknown key, message from another window: refused and logged; remove host validation: the gateway still refuses (assert log); remove both: test fails. |
| Leaky share | FR-057 | Expired, revoked or guessed token: 404 with constant timing; share of a promoted app refused; drop expiry check: test fails. |

Stated limits: the artifact profile allows inline script inside a powerless frame (FR-031); a frame can mislabel its own UI; WebRTC is mitigated by the shim and scan, not CSP (011).

## Success Criteria *(mandatory)*

- **SC-001**: Every kind in FR-003 is created from chat and shown inline and in the store, verified live in Chrome in both themes at 360 and 1280 px.
- **SC-002** (after 008): A kanban artifact is promoted by one button press plus Add, pinned, shown on Home, and keeps its cards as list rows across a gateway restart.
- **SC-003**: Every export format of FR-040 opens in a standard office suite or browser with no warning about macros or external content.
- **SC-004**: Every Security row is observed failing under its sabotage.
- **SC-005**: One independent review per security-marked slice with no HIGH open.

## Out of scope

Real-time collaboration; sharing apps or app data; artifacts writing to connectors; a second hostname; importing office files as editable documents (they stay `file`, readable through existing conversion).

## Open questions

See [plan.md](plan.md#open-questions-recommended-defaults).
