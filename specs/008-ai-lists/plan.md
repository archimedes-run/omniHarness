# Implementation Plan: AI Lists

**Branch**: `008-ai-lists` | **Date**: 2026-10-20 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/008-ai-lists/spec.md`, and the design decisions in [research.md](research.md).

## Summary

Lists live in the gateway, in the gateway's own database, as typed tables (`lists_*`): typed cells with state, origin, label and sources; append-only change history; durable runs, queue items and run events. Agents reach them through **`omni-lists`**: ten tools defined once in the gateway, served in-process to our agents with the caller's identity taken from the runtime context, and optionally over MCP HTTP to external clients (research.md R6). Access (none / read / read+write per agent per list) is enforced in the list service on every call. Tiers are in the tracked policy rules; user-written cells need approval with a diff on the existing confirmation card.

Processing is a durable queue of (row × AI column) items in dependency order, claimed with leases by one elected worker, budget-checked at claim time, and streamed to the UI from stored events over SSE (R4, R5). Untrusted cell text cannot initiate actions: processing gets Tier 1 research tools only, and in chat, list-initiated Tier 2/3 actions become button-only proposals (R7). Finish notices go through the trigger engine's politeness pipeline (R11). A deterministic 002 rule action processes new rows on a schedule (R9). The UI adds Lists to the sidebar with full-page boards (R12).

Four slices, each releasable, each with sabotage-checked gates and at least one integration test through the production composition root.

## Technical Context

**Language/Version**: Python 3.12 (backend); TypeScript 5 / React 19 / Next.js 16 (frontend)

**Primary Dependencies**:
- existing: FastAPI, SQLAlchemy 2 (async engine for routes, sync engine where tools run inside the loop, as the ledger does), the 003 policy middleware and `PendingStore`, the 002 trigger engine and politeness pipeline, the 005 `LedgerService`, TanStack Query, the shadcn/ui components in use;
- new direct dependency: `openpyxl` (already in the lock transitively), stdlib `csv`;
- `mcp` (already a dependency of the watcher package) for the optional external MCP mount.

**Storage**: The gateway database (SQLite WAL by default, Postgres optional). New `lists_*` tables (research.md R3) created at startup and by an Alembic revision on its own branch.

**Testing**: pytest (`backend/tests/lists/`, `backend/tests/gates/`), vitest, Playwright rendering and e2e on the production build. A deterministic stand-in model for processing tests (fixed structured answers, including can't tell, wrong type, and an "injection-following" mode that tries to call an email tool).

**Target Platform**: The existing Docker Compose stack on macOS; the daemon profile must still meet Article VI.

**Project Type**: Web application (backend + frontend).

**Performance Goals**: first page of 200 rows from a 10,000-row list in under 1 s server + render on the production build; `aggregate` over 10k rows under 1 s; pivot over 10k rows under 2 s.

**Constraints**: no new always-on process; the queue worker idles at zero CPU when nothing is queued (Article VI). Everything a requirement reads is tracked (Article XIV). No DarcyIQ text or assets.

**Scale/Scope**: one user; tens of lists; up to 10,000 rows per import, ~50k rows per list total as the design limit; up to ~20 columns, 3–5 AI.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after design (below).*

| Article | How this plan complies |
|---|---|
| I. Gateway-only integration | Lists are a gateway domain (`app/lists`). The trigger engine reaches them only through `gateway_post` to `/api/lists/*`. External MCP clients reach them through the gateway's MCP mount. No module imports gateway internals. |
| II. Three-tier policy | Every `omni-lists` tool is classified in `default_rules.yaml` (tracked). The user-written-cell distinction is made by a policy-side resolver from stored cell origin, not by the tool or model. Unknown tools stay Tier 3. Departures from the article's wording are in Complexity Tracking. |
| III. Provenance over trust | Cell and Find rows text is data. Confirmations of list-initiated proposals are button-only (`confirmable_by_typing` false for content origin). |
| IV. Human in the loop | Not engaged (no coding-agent approvals). |
| V. Non-goals | No email is sent from list content; processing has no outbound tools (FR-093). No browser actions initiated from cells. |
| VI. Lite by default | The queue worker is a task inside the gateway's elected worker, sleeping when idle. No Docker requirement. |
| VII. Politeness | Finish notices enter the existing pipeline: quiet hours, coalescing, no interruption, presence (R11). |
| VIII. Privacy | Memory is used per column only when toggled on, and recorded per cell. Purge is Tier 3 and audit-logged. |
| IX. Ship in slices | Four slices, each useful alone (below). Slice 1 is a usable store with no AI or UI. |
| X. Honest limits | Cell states (empty / filled / can't tell / failed), withheld, unknown spend, estimate basis stated, "stopped at your budget cap". |
| XI. Production shape | Each slice has a `create_app()` + lifespan test; the restart test uses the real lifespan twice on one database with claim contention; the automation test uses `build_production_loop`; the SSE test reads events from a different app instance than the one processing. |
| XII. Probes seen finding | Every gate below lists its sabotage; each is recorded in `gate-verification.md` with the literal failure output and confirmation that the sabotage reached its subject (summary line read, not grepped). |
| XIII. Initiation ≠ confirmation | FR-090 and FR-091 are separate, with separate tests (G1-5 / G2-6 vs G1-6). |
| XIV. Tracked defaults | Templates, system library, policy rules, rate-limit and concurrency defaults, and the `omni-lists` registration are tracked; a gate runs on a fresh clone. Tests build config from `config.example.yaml`. No test reads `.env` or `config.yaml`. |

**Result: PASS**, with the departures listed in Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/008-ai-lists/
├── spec.md
├── research.md
├── plan.md              # this file
├── data-model.md        # next: /speckit-plan Phase 1
├── contracts/           # next: lists-api.md, omni-lists-tools.md, ui.md
├── quickstart.md        # next
├── gate-verification.md # filled per slice
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── lists/                         # NEW: the lists domain (gateway side)
│   │   ├── service.py                 # lists, columns, rows, cells; access checks; change history
│   │   ├── types.py                   # typed values, validation, datetime+tz, link, single-select
│   │   ├── query.py                   # filter/sort/search/paging, aggregate, pivot (SQL)
│   │   ├── graph.py                   # {column} references, cycle detection, topological order
│   │   ├── access.py                  # none/read/read+write, defaults, denial shape
│   │   ├── delete.py                  # preview tokens, count check, archive, restore, purge
│   │   ├── importer.py                # CSV/XLSX parse with limits, mapping, preview, atomic import
│   │   ├── export.py                  # CSV with state columns
│   │   ├── templates/                 # tracked built-in templates + system column library (YAML)
│   │   ├── processing/
│   │   │   ├── queue.py               # runs, items, leases, claims, budget check at claim
│   │   │   ├── worker.py              # elected worker; per-row ordering; concurrency; rate limits
│   │   │   ├── cell.py                # one structured call per item; type validation; labels
│   │   │   ├── estimate.py            # estimate and basis; measured usage
│   │   │   └── events.py              # lists_run_events append + SSE tail
│   │   ├── find_rows.py               # proposals and batch approval (Slice 4)
│   │   └── mcp/
│   │       ├── tools.py               # the ten tool schemas + handlers
│   │       ├── inprocess.py           # adapter into get_available_tools as local:omni-lists
│   │       └── http.py                # optional MCP streamable HTTP mount, per-client tokens
│   ├── gateway/routers/lists.py       # NEW: /api/lists/*
│   ├── gateway/app.py                 # include router; start/stop worker in lifespan
│   ├── policy/default_rules.yaml      # omni-lists_* tiers
│   ├── policy/targets.py              # resolver: update_rows touches user-written cells
│   └── trigger_engine/                # Rule.action lists.process_new_rows; fixed-text firings
├── packages/harness/omniharness/
│   ├── persistence/lists/             # NEW: model.py, sql.py
│   ├── persistence/migrations/versions/<rev>_lists.py
│   └── tools/tools.py                 # add local:omni-lists source when the controller is registered
└── tests/lists/                       # NEW: incl. *_through_the_app.py

frontend/src/
├── app/workspace/lists/page.tsx              # index
├── app/workspace/lists/[id]/page.tsx         # table, toolbar, panels
├── components/workspace/lists/               # table, cells, row detail, column editor, import, pivot, run summary, cards
├── components/workspace/chat-bar/context-picker.tsx   # Lists tab
├── components/workspace/confirmations/pending-action-card.tsx  # diff for update_rows
├── components/workspace/workspace-nav-chat-list.tsx   # Lists sidebar item
└── core/lists/                               # api.ts, hooks.ts, types.ts, sse.ts
frontend/tests/rendering/                     # lists.spec, contrast routes added
```

**Structure decision**: the existing web-application layout. Lists are a gateway domain package next to `app/ledger` and `app/policy`, with storage in the harness persistence package next to the ledger, mirroring 005.

## Slices

Each slice ends with: its gates green, each gate's sabotage recorded in `gate-verification.md`, its composition-root test green, the wiring gate with zero new "unwired" entries, and a fresh-clone check of tracked defaults.

### Slice 1: data model + `omni-lists` + access control + delete safety (no UI)

Delivers: lists, typed columns (all six types), rows, cells with state and origin, change history, column library (system + user, API only), and all ten `omni-lists` tools, with `process_rows` returning "processing arrives in Slice 2" honestly (Article X). REST `/api/lists/*` for the same operations. Policy rules and the update diff payload on the pending action (the card renders it as plain change lines until Slice 3 styles it).

Requirements: FR-001–FR-011, FR-013 (cycle refusal at save), FR-016, FR-020–FR-021, FR-030(1,3), FR-033 (statuses stored), FR-051 (server side, API), FR-060–FR-076, FR-090–FR-091 (chat side), FR-094, FR-130–FR-135.

Gates (each with its sabotage):

| Gate | Asserts | Sabotage that must make it fail |
|---|---|---|
| G1-1 typed storage | 9 sorts before 10; datetimes sort by instant across timezones; bad link / bad option / bad boolean refused per cell | store numbers as text in the number column path |
| G1-2 cycle refusal | a→b→a and a→b→c→a refused, naming the columns | skip the graph check on save |
| G1-3 ambiguous update | expecting one, 2 matches → refused with "2 rows match", no change; 0 matches refused | replace the count check with "take the first" |
| G1-4 delete token | changed count → refused with the new count; reused, expired and other-caller tokens refused; same count different rows refused (Q10) | drop the count comparison in `delete_rows` |
| G1-5 tiers | each tool's tier from the shipped rules; `update_rows` on a user cell creates a pending action and changes nothing; on an AI cell executes and discloses | mark the resolver's "touches user cells" always false |
| G1-6 button-only | a list-initiated proposal cannot be confirmed by typing "yes"; the button confirms it | set `confirmable_by_typing` true for content origin |
| G1-7 access sabotage (FR-075) | an agent with `none` gets the fixed denial; no cell value of the list appears anywhere in the thread state, tool results or errors; `list_lists` omits the list | remove the access check in `service.query_rows` |
| G1-8 identity | a call with no gateway-established agent identity is denied; an `agent` argument supplied by the model is ignored | read identity from tool arguments |
| G1-9 archive/restore | delete archives; restore within 30 days returns cells, sources, history; purge by an agent is Tier 3 | hard-delete in `delete_rows` |
| G1-10 never "unable to determine" | no cell value matches the can't-tell phrase list; can't tell has no value | let the writer store the reason as the value |
| G1-11 tracked registration | on a fresh clone with an empty `extensions_config.json`, `omni-lists_*` tools are in the catalog | move registration into the example extensions file |

Composition-root test: `tests/lists/test_omni_lists_through_the_app.py`, using the ledger-style `gateway` fixture (`create_app()` + real lifespan, config from `config.example.yaml`, tmp SQLite). It runs the US1 journey: create list, insert, query with every operator, aggregate, ambiguous update, two-step delete with a changed count, restore, and a no-access agent. **Structural difference named**: tool calls made through `get_available_tools` and the policy middleware as the lead agent builds them, not service calls, because hand-calling the service would bypass identity and tier classification.

### Slice 2: processing queue + AI columns + cost estimate

Delivers: AI columns with references, dependency order and memory toggle; the durable queue (runs, items, leases, events); per-cell structured fills with type validation, labels and sources; disqualification; estimate and "Try on 5"; budget cap; pause, resume, rerun failed; SSE progress; finish notice through the politeness pipeline; processing tool surface restriction; the injection test.

Requirements: FR-012, FR-014–FR-019, FR-033–FR-044, FR-047, FR-055 (API), FR-062, FR-092–FR-093, FR-136.

Gates:

| Gate | Asserts | Sabotage |
|---|---|---|
| G2-1 restart durability (FR-034) | stop the lifespan mid-run, start a new app on the same DB: every queued cell done exactly once, none lost, paused runs stay paused | commit the cell and the item in separate transactions with a crash injected between |
| G2-2 claim contention | two workers' claim loops on one DB never lease the same item | remove the lease condition from the claim `UPDATE` |
| G2-3 dependency order | a dependent column never sees its dependency unfilled; empty/can't-tell reference short-circuits with a reason | process items in insertion order |
| G2-4 budget cap | the run stops before the next cell at the cap and says so; two concurrent claims cannot both pass the check at the cap | move the budget check outside the claim transaction |
| G2-5 injection (FR-092) | the injection row completes; zero Tier 2+ tools execute; the cell's source is the URL | give processing the agent's full tool surface |
| G2-6 Tier 2 initiation extension | in chat, an `update_rows` initiated by AI-cell text becomes a card-only proposal | disable the list-content Tier 2 extension |
| G2-7 estimate before run | every run request without a shown estimate id is refused; first run defaults to 5 rows | allow run creation without `estimate_id` |
| G2-8 unknown spend | a model with no usage reported records "unknown", never 0 | default missing usage to 0 |
| G2-9 quiet hours | a run ending inside quiet hours delivers its notice at the window's end, coalesced | route the notice straight to `deliver` |
| G2-10 SSE across workers | events written by app A are streamed by app B from `Last-Event-ID` | publish events in memory only |
| G2-11 idle cost | with nothing queued, the worker makes no DB query for 60 s (beyond one slow poll) | replace the wake signal with a 100 ms poll |

Composition-root tests: `tests/lists/test_processing_through_the_app.py` (US2 end to end with the stand-in model) and `tests/lists/test_restart_through_the_app.py` (G2-1). **Structural differences named**: the restart test exists because in-process tests never lose memory; the SSE test exists because one-process tests hide per-worker state (Article XI's first row).

### Slice 3: UI

Delivers: Lists in the sidebar; the index; the list page with toolbar (Filter, Sort, Pivot shell, Process, Pause, Export, Agent); inline edit; row detail; column editor; import mapping and preview (CSV/XLSX at 10,000 rows / 25 MB); process dialog with the estimate; run summary with cost; Agent menu with access; card view on mobile; "+" picker Lists tab and list chip; chat opened from a list uses its assigned agent; the diff on the approval card. CSV export of all / complete / failed.

Requirements: FR-030(2), FR-050–FR-055, FR-077–FR-078, FR-110–FR-117, FR-122.

Gates:

| Gate | Asserts | Sabotage |
|---|---|---|
| G3-1 contrast | every new page and state passes AA in both themes | swap a state label to `text-muted-foreground` on `bg-muted` at reduced opacity |
| G3-2 tokens only | no hex, rgb or palette class in new components | add one `text-gray-500` |
| G3-3 states without colour | empty / can't tell / failed / withheld each have distinct text and accessible names | render can't tell and empty both as "—" |
| G3-4 paging | 10k-row fixture loads pages of 200 from the server; sort is typed | sort the loaded page client-side |
| G3-5 import limits | 10,001 rows and 25 MB + 1 refused before insert; failed import leaves zero rows | commit per batch |
| G3-6 export states | can't-tell and failed cells are distinguishable in the CSV via state columns; withheld exports as `[withheld]` | export redacted text |
| G3-7 list chat agent | chat opened from a list is answered by its assigned agent | open with the default agent |
| G3-8 performance | first page usable < 1 s on the production build (median of 5) | render all 10k rows |

Composition-root test: Playwright e2e against the production build and the real gateway (`tests/e2e/lists.spec.ts`), plus a backend test that the picker's attach call and the list-chat thread creation go through `create_app()`.

### Slice 4: Find rows, templates, pivot, automations

Delivers: Find rows (proposals, batch approval, untrusted labelling, counted against the budget); the six built-in templates and user templates with favourites; the pivot (server-side, copy, CSV); the 002 `lists.process_new_rows` rule action; row → ledger task with a back link; lists on the project view.

Requirements: FR-031–FR-032, FR-048–FR-049, FR-052, FR-095, FR-100–FR-102, FR-120–FR-121.

Gates:

| Gate | Asserts | Sabotage |
|---|---|---|
| G4-1 batch approval | nothing from a proposal is inserted before approval; exactly the approved subset is inserted, origin "found" | insert on proposal |
| G4-2 Find rows untrusted | an action initiated by proposal text is card-only | mark proposals as user origin |
| G4-3 pivot correctness | every aggregate equals a direct computation on 10k rows; 2 / 1 / 1 limits enforced | compute over the first page only |
| G4-4 templates tracked | on a fresh clone each built-in template creates its columns, AI columns and (Leads) disqualification criteria | load templates from a gitignored path |
| G4-5 automation is deterministic | a cron firing creates a run for only never-processed pending rows, within the cap, and no agent turn is injected | route the action through the prompt injector |
| G4-6 row → task | the task exists with a `list_row` link, the row shows it, and neither status changes the other | update row status from task status |

Composition-root tests: `tests/lists/test_automation_through_the_loop.py` with `build_production_loop` (the trigger engine's real loop builder) posting to a gateway built by `create_app()`; `tests/lists/test_find_rows_through_the_app.py`. **Structural difference named**: the automation test exists because hand-built loops skip `_parse_rule` and the write path, where a new rule field is most likely to be dropped.

## Post-design Constitution re-check

No new process; the worker lives in the elected gateway worker. One new tool source, registered in code. Two departures from Article II's wording (below), both tied to open questions. All 14 articles still hold. **PASS.**

## Complexity Tracking

| Departure | Why needed | Simpler alternative rejected because |
|---|---|---|
| `insert_rows` is Tier 1 although it writes (spec Q2) | The brief's constraint; inserts are additive, visible and recorded, and blocking them would make "add from Telegram" a confirmation dance | Tier 2 is the constitutional fit and is one rules-file line away if the user prefers it |
| AI-cell fills are Tier 1 writes | The assigned agent writing the cells it was asked to fill is the run itself; each fill is recorded with sources | Classifying each fill as Tier 2 would append a disclosure per cell to nothing (background runs have no reply) |
| "Tier 2, needs approval" for user-written cells (spec Q1) | The brief's constraint; the constitution's Tier 2 does not wait | Implemented as Tier 3 (the existing confirmation path) with a diff; a constitutional "Tier 2 with approval" would be an amendment |
| Tier 2 actions initiated by list content become proposals | Article XIII's initiation rule for the largest untrusted channel | Leaving Tier 2 to execute would let a cell rewrite other cells |
