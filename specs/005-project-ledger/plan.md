# Implementation Plan: Project Ledger

**Branch**: `005-project-ledger` | **Date**: 2026-10-19 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/005-project-ledger/spec.md`, and the inherited wiring entries in [plan-inputs.md](plan-inputs.md).

## Summary

The ledger lives in the gateway, in the gateway's own database:
- projects, goals, tasks, notes, links, and append-only evidence;
- a REST API under `/api/ledger`;
- two new pages, **Today** (in Inbox's place) and **Projects**.

Writes come from two places:
- the user, directly in the UI;
- the assistant, through two Tier 3 tools (`ledger_apply` and `automation_propose`). These reuse the existing confirmation card, so initiation (FR-008), confirmation (FR-009) and audit come from the policy layer that already enforces them.

Evidence arrives from four sources:
- **Coding sessions**: the session watcher, extended to read **Codex** as a second adapter and to track each session's **own todo list**, applied only after a confirmed tool result. The gateway reads it through the existing watcher client, with the same tools and new fields in the replies.
- **Git**: read by the gateway from user-chosen, read-only repository mounts.
- **Workflow runs**: read inside the gateway.
- **Calendar**: through the user's existing calendar connection. This wires the dormant `CalendarSource`.

Flags ("done but still changing", "outside declared scope") are computed from evidence against each task's declared files. They are labelled inferences and never change status.

Claude Code hooks are an optional upgrade. A host-side command, shown in Settings, installs them, because the watcher's mount of `~/.claude` is read-only and must stay so. Events arrive at the watcher's existing host-local port.

## Technical Context

**Language/Version**: Python 3.12 (backend, watcher); TypeScript 5 / React 19 / Next.js 16 (frontend)

**Primary Dependencies**:
- existing only: FastAPI, SQLAlchemy (async) + Alembic, LangChain agent middleware (policy), the trigger engine, TanStack Query, the shadcn/ui components already in use;
- `git` CLI, invoked read-only, in the gateway image (already present for the sandbox);
- no new frontend libraries.

**Storage**: The gateway database (the SQLite/Postgres the other repositories use), with new `ledger_*` tables through an Alembic migration. Evidence is append-only, with a uniqueness key per source event (FR-017).

**Testing**:
- pytest, including `tests/gates/*`;
- vitest;
- Playwright rendering specs (`tests/rendering`) and e2e (`tests/e2e`);
- fixtures shaped like this machine's real Claude and Codex files (structure only, synthetic content).

**Target Platform**: The existing Docker Compose stack (`make daily`) on macOS. The watcher stays host-local, with read-only mounts (001 FR-021).

**Project Type**: Web application (backend + frontend), plus the watcher service.

**Performance Goals**: Today and Project view are usable within 500 ms on a direct load (FR-051). A watcher refresh adds no more than 20% to its current cost with Codex enabled (incremental reads, as Gate 3 already measures).

**Constraints**:
- Article VI: no new always-on process. Collectors run inside the gateway's existing trigger loop tick and the watcher's existing refresh.
- Zero writes to sources (FR-018).
- Nothing gitignored carries a default (Article XIV).

**Scale/Scope**: One user. Tens of projects, hundreds of tasks, tens of thousands of evidence items over a year. Two coding agents.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design (below).*

| Article | How this plan complies |
|---|---|
| I. Gateway-only integration | The watcher stays a separate module, reached through `watcher_client`. Triggers read the ledger through `/api/ledger` (FR-065). Hooks talk to the watcher's existing port, never to the agent core. |
| II. Three-tier policy | Assistant writes to the ledger and automations are Tier 3 tools (`ledger_apply`, `automation_propose`), classified in the shipped rules (tracked). Reads are Tier 1. |
| III. Provenance over trust | Session logs, commits and calendar text are evidence data. Chat proposals are refused when initiated by tool-result content (existing `_initiation_permitted`). Hook payloads are data. |
| IV. Human in the loop | Hooks are observe-only: async, silent, exit 0, never answering a prompt. No permission is relayed or approved. Remote approval stays out of scope. |
| V. Non-goals | No email, no browser actions, no persona. |
| VI. Lite by default | No new process. Codex reading reuses the watcher's incremental reader. Git polling runs on the trigger loop's tick, only for linked repositories. |
| VII. Politeness | Overdue and blocked-on-you alerts go through the existing politeness pipeline (quiet hours, coalescing, presence). |
| VIII. Privacy | Todo descriptions are dropped at read. Commit bodies and evidence text pass display redaction. Mounts are read-only and opt-in. |
| IX. Ship in slices | Each user story is independently releasable (see tasks.md phases). US1 alone is a usable ledger. |
| X. Honest limits | Observed / claimed / inferred labels everywhere. Can't-tell is distinct from empty. Unsupported automations are refused with a reason. |
| XI. Production shape | One composition-root integration test per story (FR-071): `create_app()`+`lifespan`, `WatcherService`, `build_loop`. |
| XII. Probes seen finding | Every new gate and check is sabotaged once. Codex parsing is checked against this machine's real files for structure before fixtures are trusted. |
| XIII. Initiation ≠ confirmation | FR-008 and FR-009 are separate requirements with separate tests (T014, T015). |
| XIV. Tracked defaults | Inert-type lists, default mount documentation, hook templates and policy rules for new tools are tracked. Tests use `config.example.yaml` (the hygiene PR). |

**Result: PASS**, with no violations to justify.

## Project Structure

### Documentation (this feature)

```text
specs/005-project-ledger/
├── spec.md
├── plan.md              # this file
├── plan-inputs.md       # inherited unwired entries (from the hygiene PR)
├── research.md          # Phase 0
├── data-model.md        # Phase 1
├── contracts/
│   ├── ledger-api.md    # /api/ledger REST contract
│   ├── watcher.md       # watcher reply additions, hook receiver
│   └── ui.md            # sidebar, Today, Project view, cards (wireframes + states)
├── quickstart.md        # Phase 1 validation guide
├── checklists/requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks)
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── ledger/                      # NEW: the ledger domain (gateway side)
│   │   ├── service.py               # create/update/link/promote; status only by user
│   │   ├── evidence.py              # append-only record, dedupe key, observed/claimed
│   │   ├── flags.py                 # done-but-changing, outside-declared-scope (inferences)
│   │   ├── today.py                 # Today assembly: waiting / due / moved, can't-tell per source
│   │   ├── sources/
│   │   │   ├── sessions.py          # from watcher_client replies (agent, todos, files)
│   │   │   ├── git.py               # read-only `git log` on linked mounts
│   │   │   ├── workflows.py         # from workflow runs (PlatformEvent.from_row)
│   │   │   └── calendar.py          # feeds CalendarSource / project calendar evidence
│   │   └── tools.py                 # ledger_apply, automation_propose (Tier 3 agent tools)
│   ├── gateway/routers/ledger.py    # NEW: /api/ledger/*
│   ├── gateway/routers/inbox.py     # unchanged API; Today reuses it
│   ├── trigger_engine/sources/      # calendar.py, completion.py WIRED (plan-inputs)
│   └── policy/default_rules.yaml    # ledger_apply, automation_propose → Tier 3
├── packages/harness/omniharness/persistence/ledger/   # NEW: model.py, sql.py
├── packages/harness/omniharness/persistence/migrations/versions/<rev>_ledger.py
└── packages/session_watcher/session_watcher/
    ├── adapters/codex.py            # NEW: Codex adapter
    ├── adapters/base.py             # ParsedRecord + optional tool/turn/parent/todo fields
    ├── todos.py                     # NEW: confirmed-only todo state per session
    ├── discovery.py, server.py      # multiple adapters, one RecordSource per root
    └── hooks.py                     # NEW: optional hook receiver (observed waiting)
scripts/claude_hooks.py              # NEW: host-side install/uninstall (diff, atomic, reversible)
THIRD-PARTY-NOTICES.md               # NEW: agenttrail MIT attribution (FR-076)

frontend/src/
├── app/workspace/today/page.tsx     # NEW (inbox/ redirects here)
├── app/workspace/projects/page.tsx  # NEW: list
├── app/workspace/projects/[id]/page.tsx   # NEW: Project view
├── components/workspace/ledger/     # NEW: task row, evidence item, flag, proposal cards
├── core/ledger/                     # NEW: api.ts, hooks.ts, types.ts
└── components/workspace/workspace-nav-chat-list.tsx  # Today + Projects items
frontend/tests/rendering/            # today.spec, projects.spec, sidebar.spec (updated), contrast (routes added)
docker/docker-compose*.yaml          # ~/.codex:ro on the watcher; repo mounts documented
```

**Structure decision**: the existing web-application layout. The ledger is a gateway domain package (`app/ledger`), like `app/policy` and `app/trigger_engine`, with its storage in the harness persistence package next to the other repositories. Watcher changes stay inside `session_watcher`. Nothing crosses the Article I boundary except through `watcher_client` and `/api/*`.

## Phases (detail in tasks.md)

1. **Setup**: migration, mounts, policy rules, notices, and empty wiring whitelist entries forbidden.
2. **Foundational**: ledger storage, service, API, and the composition-root test harness.
3. **US1** capture from chat. 4. **US2** Today. 5. **US3** Claude + Codex sessions, todos, flags. 6. **US4** git, workflows, calendar. 7. **US5** automations from chat. 8. **US6** ledger-aware triggers. 9. **US7** optional hooks.
10. **Polish**: contrast, budgets, screenshots, docs, resolving the 10 inherited entries.

## Post-design Constitution re-check

The design adds no process and no new tool to the watcher. Writes to the user's Claude settings are made only by a host-side command the user runs, never by the containers. All 14 articles still hold. **PASS.**

## Complexity Tracking

None.
