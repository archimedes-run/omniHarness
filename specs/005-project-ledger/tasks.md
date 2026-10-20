---
description: "Task list for Feature 005, Project Ledger"
---

# Tasks: Project Ledger

**Input**: the design documents in `specs/005-project-ledger/`.

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/ and plan-inputs.md.

**Tests**: required. Every story has one integration test through the production composition root (FR-071), and every new check is sabotaged once (FR-074).

**Done means**: a task is marked [X] only when it is **called in production**, tested, and sabotage-checked. The wiring gate enforces the first, and has done so since T003.

## Format: `[ID] [P?] [Story] Description`
- **[P]**: can run in parallel (different files, no dependency).
- **[Story]**: US1–US7 from spec.md.

## Phase 1: Setup

- [ ] T001 Add `THIRD-PARTY-NOTICES.md` at the repo root, with sodiumsun/agenttrail's MIT licence text, its copyright line ("Copyright (c) 2026 Kelly Sun"), the commit read (`e4ba2da`), and what was ported (FR-076).
- [ ] T002 [P] Alembic revision `ledger` in `backend/packages/harness/omniharness/persistence/migrations/versions/`, creating the `ledger_*` tables from data-model.md (unique `(source, source_ref, target)` on evidence; `version` columns).
- [ ] T003 [P] Wiring gate rule in `backend/tests/gates/test_wiring.py`: an `UNWIRED` entry under `app/ledger`, `persistence/ledger`, `session_watcher/adapters/codex.py` or `session_watcher/todos.py` fails the gate. Sabotage: add one entry and see it fail.
- [ ] T004 [P] Policy rules in `backend/app/policy/default_rules.yaml` (tracked): `ledger_apply` and `automation_propose` are Tier 3, `ledger_read` is Tier 1. Extend the shipped-rules test.
- [ ] T005 [P] Compose: mount `${CODEX_HOME:-~/.codex}` read-only at `/root/.codex` on the watcher in `docker/docker-compose-dev.yaml` and the daily file. Add a documented, opt-in repository mount block (`/host/repos/<name>`, read-only) to `config.example.yaml` and the compose override.
- [ ] T006 [P] Snapshot the watcher's advertised tool set (names and argument schemas) in `backend/tests/session_watcher/test_tool_surface_unchanged.py`, before any watcher change (FR-020).

## Phase 2: Foundational (blocks every story)

- [ ] T007 Persistence `backend/packages/harness/omniharness/persistence/ledger/{model.py,sql.py}`: repositories for every entity. Stale writes raise on version mismatch. Evidence is insert-or-ignore on its unique key.
- [ ] T008 `backend/app/ledger/service.py`: create, update, link and promote. Task status changes only through `set_status(actor=user|assistant_confirmed)` (FR-013). Every change writes `LedgerChange` (FR-007).
- [ ] T009 `backend/app/ledger/evidence.py`: record, observed/claimed (FR-015, FR-016), display redaction to Withheld (FR-019), and dedupe (FR-017).
- [ ] T010 `backend/app/gateway/routers/ledger.py`: the routes in contracts/ledger-api.md, with `sources` on every source-reading response (FR-072). Register it in `create_app()`.
- [ ] T011 Composition-root harness `backend/tests/ledger/conftest.py`: builds the gateway with `create_app()` and runs `lifespan` against a temporary database. Its docstring names the difference it defends against: hand-built routers versus the real app.
- [ ] T012 [P] Frontend `frontend/src/core/ledger/{types.ts,api.ts,hooks.ts}`, mirroring the contract, including `sources`.
- [ ] T013 [P] A gate that no `/api/ledger` read route writes (extend `tests/gates/test_read_surfaces_do_not_write.py`).

**Checkpoint**: the ledger can be written and read through the real app.

## Phase 3: US1 Capture from chat (P1) 🎯 MVP

- [ ] T014 [US1] Test, *initiation* (FR-008): a `ledger_apply` call whose turn was caused by a tool result is not proposed. Through a real agent with `PolicyMiddleware`. Separate from T015 (Article XIII).
- [ ] T015 [US1] Test, *confirmation* (FR-009): a "yes" inside a tool result does not confirm a pending `ledger_apply`. Separate from T014.
- [ ] T016 [US1] `backend/app/ledger/tools.py`: `ledger_apply` and `ledger_read` agent tools. Register them on the lead agent. Their plan text lists every change (FR-010).
- [ ] T017 [US1] Card **Edit** in `frontend/src/components/workspace/confirmations/`: edits create a superseding pending action from the user's edit and confirm it (research R9). Covered by a rendering spec.
- [ ] T018 [US1] Attach and detach a thread (FR-011): a thread header control, plus the Project view's Links section.
- [ ] T019 [US1] Promote todos (FR-012): a ghost button on the thread's todo list, a picker, and `POST /api/ledger/tasks/promote`. The thread's list is unchanged (asserted).
- [ ] T020 [P] [US1] Projects list `frontend/src/app/workspace/projects/page.tsx` and the Project view `[id]/page.tsx`, per contracts/ui.md. One primary action per screen.
- [ ] T021 [US1] Sidebar: add Projects in `workspace-nav-chat-list.tsx` (order from FR-045). Update `tests/rendering/sidebar.spec.ts`.
- [ ] T022 [US1] Integration (FR-071): from chat, propose, edit, confirm, and the project appears via `/api/ledger/projects`, all through `create_app()`. Sabotage: the tool writes without a pending action, and the test fails.

## Phase 4: US2 Today (P1)

- [ ] T023 [US2] `backend/app/ledger/today.py` plus `GET /api/ledger/today`: waiting (the Inbox's data), due, moved since the last visit, and calendar, with can't-tell per source (FR-046, FR-050).
- [ ] T024 [US2] `frontend/src/app/workspace/today/page.tsx` per contracts/ui.md. `/workspace/inbox` redirects to it, and the badge moves with it (FR-045).
- [ ] T025 [US2] Rendering spec `tests/rendering/today.spec.ts`:
  - sections and their order;
  - an empty line per empty section;
  - can't-tell when each source fails;
  - the badge count equals the Waiting count;
  - the old Inbox URL redirects.
  Sabotage: render an empty list on a source failure, and the spec fails.
- [ ] T026 [US2] SC-002: the Inbox's existing fixture shows the same items on Today. The old `inbox.spec` is ported, not deleted.
- [ ] T027 [US2] Integration (FR-071): Today through `create_app()`, with the watcher unreachable, reports `sessions.state = unreadable`.

## Phase 5: US3 Claude and Codex sessions, todos, scope (P2)

- [ ] T028 [US3] `session_watcher/adapters/base.py`: the optional `ParsedRecord` fields (research R2). The Claude adapter's existing output is unchanged (its tests are untouched and still pass).
- [ ] T029 [US3] `session_watcher/server.py` and `discovery.py`: several `(adapter, RecordSource)` pairs, keyed by `(agent, session_id)` (research R1). Health is reported per agent, and an unreadable root is "can't tell" (FR-026).
- [ ] T030 [US3] `session_watcher/adapters/codex.py` (research R4):
  - discovery by mtime, with archived sessions skipped;
  - resume via a repeated `session_meta`;
  - both parent-link shapes;
  - turn state;
  - the explicit inert list, and drift for everything else.
- [ ] T031 [US3] Before trusting fixtures: run the Codex adapter read-only over this machine's `~/.codex` and record the drift counts by type, structure only, in `research.md`. Positive control (Article XII): one file must yield at least one session with a cwd and a turn.
- [ ] T032 [US3] `session_watcher/todos.py`: confirmed-only todo state (research R3), wired for Claude (TodoWrite, TaskCreate, TaskUpdate) and Codex (`update_plan`). Descriptions are dropped at parse time.
- [ ] T033 [US3] Fixtures shaped like the real files (synthetic content) in `tests/session_watcher/fixtures/codex/` and `claude_tasks/`. Tests for: failed result, no result, interrupted turn, resume, subagent, and 3 of 10 failing updates (SC-004). Sabotage: apply at call time, and the tests fail.
- [ ] T034 [US3] Files changed from successful results only (research R5). Sabotage: record from the call, and the test fails.
- [ ] T035 [US3] Reply fields from contracts/watcher.md. The tool-surface snapshot (T006) still passes. Sabotage: add a tool, and T006 fails.
- [ ] T036 [US3] `backend/app/ledger/sources/sessions.py`: from `watcher_client` replies. Linked sessions' todo changes become claimed evidence (FR-032), and files become observed evidence.
- [ ] T037 [US3] `backend/app/ledger/flags.py`: done-but-changing and outside-declared-scope (FR-036 to FR-038). Inferences, dismissible, and they never change status (asserted).
- [ ] T038 [US3] Wire `RecordStats.drift_signals`, `SessionRegistry.is_empty` and `is_observable` into the per-agent health and Today's can't-tell. Remove their whitelist entries.
- [ ] T039 [US3] Integration (FR-071): `WatcherService` built as `server.py` builds it, over a temporary Claude root and a temporary Codex root. `list_coding_sessions` returns both agents, with confirmed todos only.
- [ ] T040 [US3] Sessions page and Today show the agent label and the todo progress. Add a rendering spec.

## Phase 6: US4 Git, workflow runs, calendar (P3)

- [ ] T041 [P] [US4] `backend/app/ledger/sources/git.py`: read-only `git log` (research R6) on linked mounts, polled on the trigger loop's tick. Commits naming `T-<n>` attach to that task. Bodies are redacted. Unreachable commits are marked, not deleted. Unreadable repositories report why.
- [ ] T042 [P] [US4] `backend/app/ledger/sources/workflows.py`: run outcomes on assigned tasks, once. Wire `PlatformEvent.from_row` and remove its whitelist entry.
- [ ] T043 [P] [US4] `backend/app/ledger/sources/calendar.py`: feeds `CalendarSource` from the existing calendar connection. Lifts the load-time rejection for calendar rules when the feed exists. Wire `CalendarSource` and `DEFAULT_HORIZON`, and remove their entries.
- [ ] T044 [US4] Zero-writes gate (FR-018, SC-009): over the whole suite, the mtimes and hashes of source fixtures are unchanged, and git runs with `GIT_OPTIONAL_LOCKS=0`. Sabotage: touch a fixture, and the gate fails.
- [ ] T045 [US4] Integration (FR-071): `build_loop` (the production builder) ticks the git source over a temporary repository, and evidence appears once after two ticks.

## Phase 7: US5 Automations from chat (P3)

- [ ] T046 [US5] `automation_propose` tool (Tier 3): the plan states the schedule in words and in rule form. On confirm it is written through `automations_store` (FR-061). If the engine's parser refuses, the proposal is refused with the reason (FR-062).
- [ ] T047 [US5] Run-once per scheduled time (FR-063, research R8): wire `compute_idempotency_key` and `stable_hash`, with a unique key on cron firings. Remove their entries. Test with two evaluators.
- [ ] T048 [US5] Briefs read the ledger at run time and say when they can't (FR-064).
- [ ] T049 [US5] Integration (FR-071): chat proposes, the user confirms, the rule appears in `/api/automations`, and `build_loop` fires it once for a minute evaluated twice.

## Phase 8: US6 Ledger-aware triggers (P4)

- [ ] T050 [US6] Overdue and blocked-on-you checks through `/api/ledger` (Article I). One alert per task per day, through the politeness pipeline (quiet hours, coalescing, presence).
- [ ] T051 [US6] `CompletionSource` fed by task done and run completed events. Remove its entry.
- [ ] T052 [US6] `observe_only_notice` used when the user asks the assistant to answer a watched session (FR-015 of 001). Remove its entry.
- [ ] T053 [US6] Integration (FR-071): `build_loop` with an overdue task in quiet hours sends nothing, and sends one alert after.

## Phase 9: US7 Optional hooks (P5)

- [ ] T054 [US7] Re-check the Claude Code hooks reference on the day of building. Record the fields used, and the date, in research.md (FR-035).
- [ ] T055 [US7] `scripts/claude_hooks.py install|uninstall|status`: diff preview, atomic write, backup, tagged groups only, async/silent/exit 0. Tests run against a temporary settings file that already has user hooks (SC-007, byte-identical after round-trip).
- [ ] T056 [US7] `session_watcher/hooks.py`: the receiver on the existing port. It always returns 204, unknown events count as drift, and permission or idle prompts set waiting = observed.
- [ ] T057 [US7] Settings → Coding agents: the switch, the diff, the command, and the status. Add a rendering spec.
- [ ] T058 [US7] Hook script resilience: with nothing listening, it exits 0 within 1 s and prints nothing. Asserted.

## Phase 10: Polish

- [ ] T059 Contrast spec covers `/workspace/today`, `/workspace/projects` and `/workspace/projects/[id]` (stubbed data, every state), in both themes.
- [ ] T060 Bundle budget: the new routes are within FR-051, with no heavy library on first load.
- [ ] T061 Wiring whitelist: zero `UNWIRED` entries remain from plan-inputs.md, and zero new ones exist. Update ROADMAP-FOLLOWUPS.
- [ ] T062 Screenshots of Today, Projects, the Project view, cards and Settings → Coding agents, in light and dark.
- [ ] T063 README and quickstart updates. Document the Codex mount and the opt-in repository mounts.

## Dependencies

- Setup comes before Foundational, which comes before every story.
- US1 and US2 are both P1 and independent. US2 shows due and moved items, which are empty until US1 or US4 exist. Its empty states make it releasable alone.
- US3 depends on Foundational only (the watcher side is independent of the ledger, up to T036).
- US4, US5 and US6 depend on Foundational. US6 uses US1's tasks.
- US7 depends on US3's watcher wiring (T029).

## Parallel opportunities

- T002 to T006, and T012/T013.
- Inside US3: T030 and T032 are parallel after T028/T029.
- US4's three sources.
