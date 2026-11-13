# Feature Specification: Apps, Slice 1 (a minimal Apps platform and the "Today" command center)

**Feature Branch**: `011-apps` (one PR per slice of [plan.md](plan.md))

**Created**: 2026-11-13

**Status**: Draft. The owner is away; every open question carries a recommended default, recorded as decided. The data design (no network in the app frame, parent-fetched bridge, manifest-only refresh, two-way message validation) is the owner's own decision of 2026-11-13 and is written as requirements, not questions.

**Input**: "A minimal Apps platform, and a flagship 'Today' command center built by OpenCode from a chat request, iterated until genuinely beautiful." An app is a small web page that shows the owner's live data. It never holds a token, never touches the network, and its data never reaches a model.

**Builds on**: the artifact preview route and its sandboxed iframe (`app/gateway/routers/artifacts.py`, `components/workspace/artifacts/artifact-file-detail.tsx`); coding jobs and their publish step (`app/gateway/code_jobs/`, spec 009 Slice 1) with the layout check (PR #182); Home's read-only connector reads (`app/gateway/home_sources.py`, `composio_client.execute_read_tool` and its `READ_ONLY_SLUGS`); the policy layer (`app/policy/`: tiers in `default_rules.yaml`, `runtime_floors.py`, `private_reads.py`, lineage); the versioned config store (`omniharness/config/config_versions.py`, kinds agent, skill, automation); the confirmations store and button-only card parts (010 FR-016); Graphite tokens ([tokens.md](../006-workspace-studio/tokens.md)); the page CSP in `frontend/next.config.js`.

## Data path (decided)

```
App frame (sandbox="allow-scripts", opaque origin, CSP connect-src 'none')
   │  postMessage over a MessageChannel port: {type:"data", source:"calendar"}
   ▼
Trusted host page /workspace/apps/{id} (frontend; owner's cookie; holds no secret beyond it)
   │  checks: port is the one it handed this frame; "calendar" is in the APPROVED manifest
   │  GET /api/apps/{id}/data/calendar   (owner session; same origin)
   ▼
Gateway bridge
   │  scope record: (owner, app id, served version, manifest hash) has an active grant?
   │  source = catalog entry (real read tool + fixed params + field projection)
   │  cache hit → answer at once; stale → answer + refresh in background
   │  miss → run the read tool as the owner (Tier 1 + allowlist + no runtime floor), project, cache
   ▼
Host page posts {type:"result", source, state, data, fetched_at} into the port → app renders
```

The "app-scoped token" of the owner's brief is this server-side scope record. It is never sent anywhere; the frame has nothing to steal. The "bridge" is the gateway endpoint the host page calls. The owner's "connect-src = the bridge only" becomes stricter: the frame has `connect-src 'none'` and reaches the bridge only through the host page.

## User Scenarios & Testing *(mandatory)*

### User Story 1: Ask for an app in chat, approve once, use it (Priority: P1)

In any chat the owner writes "build me a Today page: my calendar, PRs waiting on me, failing CI, my projects, coding sessions, automations, and how many mails need a reply". The lead runs a coding job in app mode. OpenCode builds against mock data, the system checks layout, contrast and every tile state, and the gateway registers the result as a candidate app. The chat shows an **App access** card listing each source in plain words ("Read today's events from Google Calendar", "Read subjects of unread mail in Primary from the last 3 days (not bodies)"), how often it refreshes, and "Data is shown in the app only; the assistant never sees it." The only way to approve is its **Allow** button. The app opens full page with real data.

**Independent Test**: on the live stack, request a two-source app; the card appears; typing "yes" does nothing; pressing Allow makes both tiles show real data; the bridge refuses the same sources before the press.

**Acceptance Scenarios**:

1. **Given** a candidate app, **When** its card renders, **Then** every source is listed in words generated from the catalog entry and its fields, never from text the app or worker wrote.
2. **Given** an approval card, **When** the owner types any text, **Then** nothing is granted; only the button grants (010 FR-016).
3. **Given** a grant, **When** a new version changes only code, **Then** it is served with no new card; **When** a version changes the manifest's sources, **Then** the bridge refuses its sources and a new card is raised.
4. **Given** the request came from content (an email or page read earlier in the turn), **When** the card renders, **Then** it is marked as a suggestion with its source; it still grants only by button.

### User Story 2: The Today command center (Priority: P1)

The owner opens **Today** from the sidebar. Within 2 s every tile shows cached data with "updated 4 min ago": the next meeting and free blocks; PRs waiting on review, failing CI, recent merges; Ledger tasks that moved, are stuck or are overdue; coding sessions running or waiting on the owner; automations' last runs, failures and next runs; an inbox pulse (count and subjects, never bodies). Graphite, both themes, AA, readable at 360 px, a real dashboard grid with small charts where they help (meeting load across the day, CI pass/fail, automation runs).

**Acceptance Scenarios**:

1. **Given** a source with data, **Then** its tile shows it and "updated N min ago" from the bridge's `fetched_at`.
2. **Given** a source whose connector is not connected, **Then** the tile says so with a **Connect** button; pressing it opens the host page's own Connect sheet (the frame never starts OAuth).
3. **Given** a source that failed, **Then** the tile says "Can't tell" with the reason, plus the last good data marked stale if any. Never "nothing today".
4. **Given** a source that answered with nothing, **Then** the tile says "Nothing today".

### User Story 3: The Apps library (Priority: P1)

`/workspace/apps` lists apps: name, current version, status (Approved, Needs approval, Access revoked). Each app has Open, Pin to sidebar, History (versions with Restore), Permissions (each source in words, last fetched, last error, Revoke).

**Acceptance Scenarios**:

1. **Given** version 3, **When** Restore on version 1 is pressed, **Then** version 4 is created with version 1's content (010 rule: undo is a new version); if its manifest hash has no active grant, the app shows "Needs approval".
2. **Given** Revoke, **Then** every grant of that app ends at once, the bridge refuses its sources, the cache rows for it are deleted, and the app shows an Approve again card in place of tiles.
3. **Given** Pin, **Then** the app appears under Apps in the sidebar and opens full page.

### Edge Cases

- The app sends a message for a source not in the approved manifest, an unknown type, or an oversized message: dropped, logged as `app_message_refused` with the app id and reason; the app gets `{type:"error", reason}`.
- The frame reloads or navigates itself: the host page sees a second `load`, closes the port, removes the frame and shows "This app reloaded itself. Reopen it." No second handshake.
- Two tabs open the same app: both read the same server cache; refresh is single-flight.
- A connector is disconnected while the app is open: next refresh turns that tile to not connected.
- The app's direct URL is opened as a top-level page: the response's own CSP `sandbox` directive keeps it opaque and network-less; with no host port it shows "Open this app from OmniHarness".

## Requirements *(mandatory)*

### Manifest and store

- **FR-001**: An app MUST have a manifest `omni-app.json`: `schema` (1), `name`, `description`, and `sources`, a map of source name (`[a-z][a-z0-9_]{0,31}`) to `{use, params?, fields, refresh_s?}`. `use` names an entry of the platform's **source catalog**; each catalog entry fixes the real read tool, its arguments template, its allowed fields and its param schema.
- **FR-002**: `fields` MUST be a subset of the catalog entry's allowed fields; `params` MUST satisfy the entry's typed, bounded schema (enums, integer ranges, IANA time zone). There are no free-form parameters and none from the frame at run time.
- **FR-003**: Apps MUST be a fourth kind, `app`, in `config_versions`: one history per app id; a snapshot holds the manifest, the bundle's content hash and its script hashes. Bundles are stored content-addressed beside the store. Restore is a new version.
- **FR-004**: The **manifest hash** is SHA-256 of the canonical JSON of `sources` only. A version whose hash equals an approved one needs no new approval; any change to `sources` does. Name and description are not in the hash.

### Approval and grants

- **FR-005**: A grant is `(owner, app id, manifest hash, approved_at, revoked_at)`. The bridge MUST refuse every source of a version whose hash has no active grant.
- **FR-006**: The approval card MUST list each source in words generated from the catalog entry, fields and params, the refresh interval, and the sentence "Data is shown in the app only; the assistant never sees it." It MUST grant only by its button (POST with CSRF, carrying the hash shown; refused if the candidate's hash differs).
- **FR-007**: Only a verified coding job in app mode, or a Restore in the library, creates an app version. Agents, scripts, scheduled runs and the frame MUST NOT create versions or grants. A card raised from a content-led turn MUST be labelled a suggestion (010 FR-027).
- **FR-008**: Revoke MUST end all of the app's grants, delete its cache rows and stop its refreshes, effective on the next bridge call.

### Bridge

- **FR-009**: `GET /api/apps/{id}/data/{source}` and `GET /api/apps/{id}/data` (all sources, one round trip) MUST require the owner's session and MUST serve only sources of the app's current version under an active grant.
- **FR-010**: Sources MUST run as the owner (the owner's connected accounts; first-party services in process, never by loopback HTTP). A connector source MUST pass three independent checks: its tool is in the catalog's read allowlist (generalising `READ_ONLY_SLUGS`); `default_rules.yaml` classifies it Tier 1 with no exception raising it; and no runtime floor applies. Failing any one refuses it, fail closed.
- **FR-011**: Results MUST be projected to the declared fields before caching; the raw tool result MUST NOT be cached, logged or returned. Strings are clipped (subjects 200 chars), arrays capped (≤ 50), the projected payload ≤ 64 KB, the upstream response read ≤ 1 MB.
- **FR-012**: Bridge results MUST NOT enter any thread, run, memory or model context, and no bridge path may write. Bridge calls are not tool calls and do not mark any turn as a private read.
- **FR-013**: Every result MUST carry `state` ∈ {`fresh`, `empty`, `not_connected`, `failed`}, `fetched_at`, `stale` (older than twice `refresh_s`), and for `failed` a sanitised reason (≤ 300 chars) with the last good data, if any, marked stale. `not_connected` comes from the connection lookup Home uses, never from an error string.
- **FR-014**: The cache MUST live in the gateway's shared store (not per worker), keyed by (owner, app id, source name, manifest hash). A small in-gateway refresher MUST refresh sources of apps opened in the last 24 h every `refresh_s` (default 300, allowed 60 to 3600), single-flight across workers by a lease. The trigger engine is not used (it starts agent runs).
- **FR-015**: Upstream calls MUST be limited to one per source per 60 s whatever the request rate; bridge requests to 60 per app per minute per owner.

### Hosting and the frame

- **FR-016**: The app MUST be served by the gateway as one self-contained HTML document (scripts and styles inlined at registration, images and fonts as `data:`) at `/api/apps/{id}/versions/{n}/app.html`, `Cache-Control: private, max-age=31536000, immutable`, with exactly this CSP:
  `sandbox allow-scripts; default-src 'none'; script-src 'sha256-…' (one per inlined script, computed at registration); style-src 'unsafe-inline'; img-src data: blob:; font-src data:; media-src 'none'; connect-src 'none'; frame-src 'none'; child-src 'none'; worker-src 'none'; object-src 'none'; manifest-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'`
  plus `Referrer-Policy: no-referrer`, `X-Content-Type-Options: nosniff`, `Cross-Origin-Resource-Policy: same-origin`, `X-DNS-Prefetch-Control: off`, and a `Permissions-Policy` denying camera, microphone, geolocation, payment, USB and clipboard.
- **FR-017**: The host page MUST embed it with `sandbox="allow-scripts"` exactly: no `allow-same-origin`, `allow-forms`, `allow-popups`, `allow-top-navigation*`, `allow-modals` or `allow-downloads`. The host route `/workspace/apps/*` MUST send the page CSP with `frame-src 'self'` (no `blob:`).
- **FR-018**: The frame cannot reach any URL: fetch, XHR, WebSocket, EventSource and beacons (`connect-src 'none'`); images and CSS URLs (`img-src data: blob:`, `font-src data:`); forms (`form-action 'none'` and no `allow-forms`); popups and `target=_blank` links (no `allow-popups`); top navigation (no `allow-top-navigation`); nested frames and workers (`frame-src`, `child-src`, `worker-src 'none'`); self-navigation off origin (the host's `frame-src 'self'`) and on origin (host tears the frame down on a second `load`, FR-021). The platform shim removes `RTCPeerConnection` and `RTCDataChannel` before app code runs, and registration rejects bundles naming them, `WebSocket`, `eval` or `new Function` (WebRTC is not covered by CSP in current browsers: stated limit).
- **FR-019**: Links in an app MUST go through `{type:"open", url}`; the host opens only `https` URLs on hosts the source's catalog entry declares (for example `github.com`, `calendar.google.com`, `mail.google.com`, and this app's own `/workspace/...` paths) with `noopener,noreferrer`.

### Message protocol (both ways validated)

- **FR-020**: Handshake: on the frame's first `load` the host creates a `MessageChannel` and posts `{v:1, type:"init", app, version, theme}` with port 2 by `frame.contentWindow.postMessage(msg, "*", [port2])`. `"*"` is required because the frame's origin is opaque (`"null"`); it is safe because the host posts only to its own frame's `contentWindow`, which `frame-src 'self'` keeps on this origin, and only once. Everything after goes over the port, which only that document holds.
- **FR-021**: The host MUST accept messages only on its port (any `window` message is ignored unless `event.source === frame.contentWindow` and it is the shim's `ready`); a second `load` of the frame closes the port and removes the frame.
- **FR-022**: Frame → host messages are exactly `data {id, source}`, `refresh {id, source}`, `open {url}`, `connect {source}`, each a plain JSON object ≤ 8 KB, schema-validated (unknown keys or types refused). `source` MUST be a name in the **approved** manifest of the served version; refused requests are dropped, logged `app_message_refused`, and answered `{type:"error", reason}`. At most 30 messages per second.
- **FR-023**: Host → frame messages are exactly `init`, `result {id, source, state, data, fetched_at, stale, reason?}`, `update` (a refreshed source) and `theme`. The platform shim MUST validate each against the same schema and accept messages only from its port (and `init` only when `event.source === window.parent`). Nothing is evaluated; data is handed to app code as parsed JSON.
- **FR-024**: The frame never initiates OAuth: `connect` makes the host show its own Connect sheet with its own button, which runs the existing connector flow.

### Building apps with OpenCode

- **FR-025**: `code_job` MUST accept app mode. The runner MUST write the **app kit** into the project: the manifest schema; `omni.d.ts`, a typed client generated from the catalog (`await omni.data("calendar")` returns that source's typed result; naming aligned with code mode's generated API, 009 FR-019); the shim; `graphite.css` (the tokens of `globals.css`, both themes, `.dark` toggled by the `theme` message); mock fixtures for every catalog entry in all four states; and the app rules (single-file build, no dynamic imports, no remote URLs, no eval, every tile handles all four states, responsive from 360 px, charts as inline SVG).
- **FR-026**: The system's checks after verification MUST include, on the mock build: the layout check at 360, 560 and 1280 px (PR #182), in both themes and with every tile in each of the four states; AA contrast measured from the probe's isolated world; and screenshots returned to the lead. The probe stays a gateway-written script using the image's existing browser.
- **FR-027**: The lead MAY run up to 3 design follow-up jobs per app against a fixed design checklist (grid alignment, hierarchy, state wording, chart legibility, touch targets ≥ 24 px, no text under 12 px) using the screenshots. Failing layout or contrast blocks registration.
- **FR-028**: On a passing job the gateway (not the worker) MUST register the app: validate the manifest against the catalog, inline the bundle, compute script hashes, scan it (FR-018), store a version, and raise the approval card when its hash has no active grant. Cap: 2 MB per bundle.

### Library and navigation

- **FR-029**: `/workspace/apps` (library) and `/workspace/apps/{id}` (full-page host) MUST exist; the sidebar shows an Apps entry with pinned apps beneath it, pins stored in per-user preferences.
- **FR-030**: Library UI MUST use Graphite tokens only and pass the contrast suite in both themes.

### Performance

- **FR-031**: Opening a pinned app with a warm server cache MUST render every tile with data in under 2 s (p95 of 10 loads on the live stack): the host fetches `GET /api/apps/{id}/data` in parallel with loading the frame and answers the frame from it.

## Today: tile → source mapping

| Tile | Source name | Catalog entry → real tool or service | Fields |
|---|---|---|---|
| Calendar | `calendar` | `googlecalendar.events_today` → `GOOGLECALENDAR_EVENTS_LIST` (primary, the owner's day in `tz`) | title, start, end, all_day; free blocks computed in the app |
| GitHub: waiting on me | `gh_review` | `github.pr_search` → `GITHUB_SEARCH_ISSUES_AND_PULL_REQUESTS`, fixed query preset `review_requested` (`is:pr is:open review-requested:@me`) | repo, number, title, updated_at, link (built server-side, as Home does) |
| GitHub: failing CI | `gh_failing` | same tool, preset `failing` (`is:pr is:open author:@me status:failure`) | same |
| GitHub: recent merges | `gh_merged` | same tool, preset `merged_7d` | same, merged_at |
| Ledger | `ledger` | `omni.ledger.today` → ledger repository in process: moved (changes since day start), stuck (status blocked, or doing with no change for 3 days), overdue (due_date before today, not done or dropped) | task, project, status, due_date, link |
| Coding sessions | `sessions` | `omni.sessions.active` → `WatcherClient.list_sessions` + `describe_sessions` | tool, title, display_state (working, waiting-on-user), how known, since |
| Automations | `automations` | `omni.automations.recent` → trigger audit (`describe_firings`), run history, `describe_upcoming` | rule name, last run, outcome, next run |
| Inbox pulse | `inbox` | `gmail.unread_subjects` → `GMAIL_FETCH_EMAILS` (metadata only; query `in:inbox is:unread category:primary -from:me newer_than:3d`) | count, subject, received_at, link. Never body, snippet or sender address |

Every connector tool above is Tier 1 in `default_rules.yaml` today; the two not yet in `READ_ONLY_SLUGS` join the catalog allowlist. The tile says "probably needs a reply (unread in Primary, 3 days)" so the estimate is labelled as one.

## Security

| Threat | Control | Sabotage check (must fail when the control is removed) |
|---|---|---|
| Malicious or buggy generated app calls the network | FR-016 CSP, FR-017 sandbox, FR-018 scan | Browser test: a test app tries fetch, XHR, WebSocket, EventSource, beacon, `<img>` to an outside host, CSS `url()`, form submit, `target=_blank` link, `window.open`, `top.location`, self-navigation off origin, nested iframe, worker; a local listener records zero hits. Drop `connect-src 'none'` (or add `allow-popups`, `allow-forms`, `allow-top-navigation`) and the listener gets a hit. |
| App reads the owner's cookie or calls the gateway as the owner | opaque origin (no `allow-same-origin`), `connect-src 'none'` | Add `allow-same-origin`: the test reading `document.cookie` and calling `/api/apps` succeeds and the test fails. |
| Token theft | there is no token in the frame (scope record is server-side) | Test asserts the served HTML and every host→frame message contain no cookie, CSRF or bearer value; inject the CSRF token into `init` and it fails. |
| Unapproved source or params from the frame | FR-022 manifest check in host, FR-009 grant check in bridge (two layers) | Frame requests `inbox_bodies` and a source of another app: refused and logged. Remove the host check: the bridge still refuses (test asserts the log). Remove the bridge check too: test fails. |
| Write-tool call | FR-010 three checks; catalog has no write tool | Catalog test entry naming `GMAIL_DELETE_MESSAGE` is refused at registration and at run; remove the tier check and the allowlist check one at a time, each a failing test. |
| Bodies leak | FR-011 projection before cache | Fixture result with a body: bridge payload and cache row contain no body text; skip projection and the test fails. |
| Data reaches a model | FR-012 | Gate test: no import path from the bridge to thread state, memory or tools; a test thread run after a bridge call has no bridge data in its state. |
| Prompt-injected data rendered in the app (XSS inside the frame) | contained: the frame has no network, no cookie, no same-origin access, no navigation out; worst case it misrenders its own tiles or sends refused messages | The network test above run with a hostile subject line (`<img src=//x onerror=...>` rendered as HTML on purpose). |
| Stale approval after manifest change | FR-004/FR-005 hash binding | Change one field of a source in a new version: bridge refuses; bind grants to app id only and the test fails. |
| Cross-app data | cache key and grant include app id | Two apps with identical sources, one revoked: revoked one refused; drop app id from the key and the test fails. |
| Cache poisoning | cache written only by the bridge from projected tool output; key server-built; no frame input reaches a key | Frame sends `refresh` with extra keys: refused by schema; remove schema validation and the test fails. |
| Spoofed host messages into the frame | FR-023 shim checks | Post a forged `result` from another window: shim ignores it; remove the port check and the test fails. |

Stated limits: WebRTC is not governed by CSP (mitigated by FR-018's shim and scan); a frame can still misuse its own UI (for example, mislabel a tile); the owner's eye, the design checklist and the independent review are the control for that.

## Success Criteria *(mandatory)*

- **SC-001**: Today, built by OpenCode from one chat request, is approved by one button press and pinned.
- **SC-002**: Every tile is verified against real data in Chrome in its own tab, read-only, in all reachable states; not-connected and failed are each forced once.
- **SC-003**: Warm-cache open under 2 s (FR-031).
- **SC-004**: Every row of the Security table is observed failing under its sabotage.
- **SC-005**: One independent review with no HIGH open.

## Out of scope (Slice 1)

Writes of any kind from apps; apps calling arbitrary MCP tools outside the catalog; sharing apps with other people; apps in channels; a second hostname; asking the assistant about a tile.

## Later

- More artifact kinds and exports (PDF, image, a static snapshot).
- MCP-UI inline: app views rendered inside chat messages.
- "Update my app" via OpenCode from the library (an edit job on the existing app, diff and new version).
- Lists as the apps' data layer (owner-writable records an app can read and, with a grant, write).
- Link an app to a Ledger project.
- Generic read sources: any Tier 1 read tool with a declared projection.

## Open questions (decided defaults)

| # | Question | Decided default |
|---|---|---|
| Q1 | Token in the frame vs parent bridge | Owner decided: parent bridge over postMessage; no token, `connect-src 'none'`. |
| Q2 | Own origin: second hostname vs opaque origin | Opaque origin from the gateway (sandbox attribute plus the CSP `sandbox` directive). No DNS, TLS or nginx change; with no network and no same-origin access a second hostname adds nothing for Slice 1. |
| Q3 | Free-form manifest projection vs catalog | Catalog entries with allowed fields; the manifest picks a subset. Approval words come from the catalog. |
| Q4 | Params from the frame | None. Only typed, bounded params fixed in the manifest. |
| Q5 | Refresh engine | Small in-gateway refresher with a lease; not the trigger engine. |
| Q6 | Cache scope | Shared store, keyed by owner, app, source, manifest hash; projected data only. |
| Q7 | Default refresh | 300 s, per source 60 to 3600 s; only apps opened in the last 24 h. |
| Q8 | "Needs reply" | Unread in Primary, not from the owner, last 3 days; labelled an estimate. |
| Q9 | Store | `config_versions` kind `app`; bundles content-addressed. |
| Q10 | Who creates apps | Verified app-mode coding jobs and library Restore only; the owner approves by button. |
| Q11 | "Until beautiful" | Hard gates (layout, contrast, four states, both themes), up to 3 lead design passes from screenshots, then independent review. |
| Q12 | Screenshots in the public repo | Mock data only; live-data evidence stays private. |
