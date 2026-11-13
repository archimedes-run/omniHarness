# Implementation Plan: Apps, Slice 1

**Branch**: `011-apps` (one PR per slice) | **Date**: 2026-11-13 | **Spec**: [spec.md](spec.md)

## Summary

Four PRs. The gateway gains a source catalog, an app kind in the versioned store, grants, and a read-only bridge with a shared cache and refresher. The frontend gains a host page that embeds a network-less sandboxed frame and talks to it over a MessageChannel, plus the library and sidebar pins. The coding job gains an app mode that hands OpenCode a kit and checks the result. Then OpenCode builds Today, and every tile is verified live.

## Technical context

- **Backend**: new `app/gateway/apps/` (catalog, manifest, registration, bridge, cache, refresher, grants), new router `app/gateway/routers/apps.py`, registered in `create_app()`; `omniharness/config/config_versions.py` gains kind `app`; `composio_client` read allowlist generalised into the catalog; `home_sources.py` helpers reused (connection lookup, Ledger, watcher, triggers views); `app/gateway/code_jobs/runner.py` app mode and registration hook; the layout probe (PR #182) extended for themes, states, contrast and screenshots.
- **Frontend**: `app/workspace/apps/` (library, `[appId]` host), `core/apps/` (API, protocol schema, host controller), sidebar pins (`workspace-sidebar.tsx`, `workspace-nav-menu.tsx`, preferences), approval card in `components/workspace/confirmations/`, `next.config.js` header entry for `/workspace/apps/*` (`frame-src 'self'`).
- **Shared contract**: `specs/011-apps/` is the contract; the protocol JSON Schema lives in one file (`frontend/src/core/apps/protocol.schema.json`) and is copied into the kit's shim at build time, so host and shim validate against the same schema.
- **Depends on**: PR #182 (layout check) merged before PR 3's checks; nothing else unmerged.
- **No sandbox image change.** Kit files are written by the runner; the probe is a gateway-written script using the image's browser and Python; app dependencies come through the existing registries proxy. No package download for the platform itself.

## Constitution check

Article I (the frame and host use only the gateway API), II (policy decides: Tier 1 plus allowlist plus floors), III and XIII (app data is data; it never enters a model), X (honest tile states), XI (`create_app()` wiring). No new external dependency.

## Slices (PR-sized)

### PR 1: Bridge, store, grants, approval card backend (can start now)

- Source catalog with the eight Today entries (spec table), each: tool or in-process service, arguments template, presets, allowed fields, param schema, plain-words template, link hosts.
- Manifest validation (FR-001, FR-002), manifest hash (FR-004), `config_versions` kind `app` with content-addressed bundles (FR-003), registration API used by PR 3 (inline, script hashes, scan, 2 MB cap: FR-018, FR-028).
- Grants and the approval pending card (button-only part), POST carrying the hash, suggestion label from lineage (FR-005 to FR-008).
- Bridge endpoints (FR-009 to FR-013), shared cache table in the gateway's existing SQL store, lease-based refresher started in the app lifespan (FR-014), rate limits (FR-015).
- App HTML route with the exact CSP and headers (FR-016).
- Tests through `create_app()`: grant lifecycle, hash change refuses, revoke deletes cache, projection drops bodies, write tool refused by each of the three checks, not_connected from the connection lookup, multi-worker single-flight (two app instances sharing the store), no bridge data in thread state (gate test). Each Security-table row owned by the backend has its sabotage.

### PR 2: Host page, protocol, library, pins (parallel with PR 1)

- `/workspace/apps/[appId]` host: iframe `sandbox="allow-scripts"`, handshake and port (FR-020, FR-021), validation and rate limit (FR-022), results, updates and theme (FR-023), Connect sheet (FR-024), open links (FR-019), batch prefetch (FR-031).
- Platform shim (`omni` client) with its own validation and RTC removal (FR-018, FR-023), built as one file the kit copies.
- Library page, History with Restore, Permissions with Revoke, pins in preferences, sidebar Apps entry (FR-029, FR-030); approval card UI.
- Develops against a fake bridge (fixtures from the catalog) until PR 1 merges; the real API swaps in with no code change beyond the base URL.
- Tests: unit (protocol schema both ways, refused-message log, second-load teardown); rendering (library, card, host states, both themes, contrast suite); Playwright attack suite: a hostile test app tries every channel in FR-018 against a local listener that must record zero hits; forged messages; cookie read. Each with its sabotage (flag added, check removed).

### PR 3a: App kit and checks (parallel with PRs 1 and 2; needs #182 merged)

- `code_job` app mode; runner writes the kit (FR-025): schema, `omni.d.ts` generated from the catalog, shim from PR 2 (stubbed until it lands), `graphite.css` generated from `globals.css`, mock fixtures in four states, app rules in AGENTS.md.
- Probe extension: both themes, four states per tile via mock build flags, AA contrast, screenshots returned to the lead (FR-026); design checklist and the 3-pass cap (FR-027); registration hook calling PR 1's API (FR-028).
- Tests: scripted-lead e2e (`scripts/code-job-e2e.sh`) with a fixture app that overflows, one that fails contrast, one that passes and is registered; the cap of 3 design passes enforced by the gateway; sabotage for each.

### PR 3b: Today built by OpenCode (after 1, 2 and 3a)

- From a chat on the live stack, the owner-style request of spec US1. OpenCode builds; checks and design passes run; the owner presses Allow and pins it. An agent never presses an approval button for the owner; if the owner is away, the run stops at the card, reports, and PR 4's tile checks wait for the grant.
- The PR carries no app code from the owner's library: it records the request text, the design checklist results, and screenshots from the mock build only (both themes, 360/560/1280). Kit fixes found while building go in this PR.

### PR 4: Live verification, performance, review (after 3b)

- Chrome, own tab, read-only: every tile against the real source (calendar against Google Calendar, PRs against GitHub search, Ledger against the projects page, sessions against `/workspace/sessions`, automations against the Automations page, inbox count against Gmail's own count for the same query). Force not-connected (disconnect a test connector or point at an unconnected toolkit) and failed (refresher with an unreachable upstream in a test override) once each. Evidence private (live data), summary in the PR.
- Performance: 10 warm-cache loads, p95 under 2 s, measured from navigation start to the last tile's `result` render mark.
- Security table re-run end to end on the live stack.
- One independent review (fresh reviewer, no prior context) of PRs 1 to 3a; exit when no HIGH is open.

## Parallelism

| Phase | Runs together | With 2 agents instead of 4 |
|---|---|---|
| 1 | PR 1, PR 2, PR 3a (three agents); a fourth runs the full suites and the attack suite as each pushes | PR 1 and PR 2 together; PR 3a after the first of them merges |
| 2 | PR 3b (one agent), review of PRs 1 and 2 starting in parallel | 3b, then review |
| 3 | PR 4 | PR 4 |

Coding agents edit disjoint trees (backend `apps/`, frontend `apps/`, `code_jobs/`); shared files (`config_versions.py`, `create_app()`, sidebar) each have one owning PR.

## Gates (each PR)

1. CI "CI passed" green; `scripts/ci/check_docs.py` clean.
2. Sabotage observed for every guard the PR adds (gates must be observed failing).
3. Tests run on the tracked example config plus test overrides, never on a local-only flag.
4. Assert on state: grant, revoke, cache and version tests read the store back.
5. UI PRs: screenshots in both themes, contrast suite AA.
6. Independent review for PRs 1, 2 and 3a (policy, frame isolation, worker contract). No HIGH open.
7. Any regression against main blocks the merge.

## Deploy notes

- Additive: new router, new store kind (lazy, no migration of existing kinds), new cache table created on first use. Rolling back the code leaves stored apps inert.
- Multi-worker: cache and refresher lease in the shared store; bridge first-party sources run in process, so the per-worker internal token is never used.
- Frontend restart for PRs 2 and 4: announce first; open tabs need a refresh.
- No nginx change: app HTML is under `/api/` (gateway), the host under `/workspace/` (frontend), both on the existing origin.
- Gitignored config must not carry any guarantee: catalog, CSP and limits ship in tracked code and defaults.

## Risks

- **Single-file bundling breaks some libraries** (dynamic imports, eval-based charts): the kit's rules forbid them and the mock build fails early; charts are inline SVG.
- **Gmail metadata shape varies**: projection reads only the subject header and drops everything else; an unrecognised shape is `failed` with a reason, never `empty`.
- **"Beautiful" is subjective**: hard gates catch broken; the checklist, three passes and an independent review raise the floor; the owner can ask for more in chat.
- **Refresher load on connectors**: only recently opened apps, one call per source per 60 s minimum.
- **PR #182 slips**: PR 3a's probe extension waits; PRs 1 and 2 are unaffected.
