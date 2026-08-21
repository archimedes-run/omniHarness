---
description: "Task list for feature 001 — read-only coding-session watcher"
---

# Tasks: Read-Only Coding-Session Watcher

**Input**: Design documents from `/specs/001-coding-session-watcher/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/mcp-tools.md](./contracts/mcp-tools.md)

**Tests**: Included. The spec carries 26 success criteria and the plan's standing convention
requires every gate to be observed failing — both demand test tasks.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1–US4, mapping to the spec's user stories
- **GATE**: a plan-review gate task. Each gate has an implementation task *and* a separate
  observe-it-fail task, per plan.md's standing convention — a gate never seen failing is
  indistinguishable from one that does nothing.

## Path Conventions

Module: `backend/packages/session_watcher/session_watcher/`
Tests: `backend/tests/session_watcher/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Package skeleton placed to satisfy Gate 1, dependencies, fixture corpus — and
proof that the chosen transport actually works before anything is built on top of it.

- [X] T001 Create uv workspace package skeleton at `backend/packages/session_watcher/pyproject.toml` — name `session-watcher`, requires-python >=3.12, and **no dependency on `omniharness-harness`** (Gate 1 placement; FR-018, Article I)
- [X] T002 [P] Create `backend/packages/session_watcher/ruff.toml` setting `flake8-tidy-imports.banned-api` on `omniharness*`, `langgraph*`, `subprocess`, `os.system`, `os.popen`, and `shell=True` (**GATE 1 impl**; SC-008, research R2 finding 2)
- [X] T003 [P] Add `watchdog` and `mcp` to `backend/pyproject.toml` dependencies and run `uv sync` (FR-022, FR-018)
- [X] T004 Create test package `backend/tests/session_watcher/__init__.py` and `conftest.py` with a `tmp_session_dir` fixture factory
- [X] T005 [P] Build fixture corpus in `backend/tests/session_watcher/fixtures/` — valid records, malformed JSON, truncated final line, unknown `type` values, and **a project directory whose name begins with a hyphen** reproducing the real `-Users-...` slug (FR-009, FR-020, research R2 finding 2)

- [X] T006 **TRANSPORT SPIKE — blocking, do before Phase 2.** Stand up a throwaway SSE server on the host in `backend/packages/session_watcher/spike_transport.py` returning a hardcoded status payload, register it in `extensions_config.json`, and reach it **from the containerized backend**. Proves `host.docker.internal` reachability and the whole SSE registration path (`extensions_config.json` → `get_enabled_mcp_servers()` → `local:<name>` catalog → agent). **If this fails, stop and revisit the transport decision before any Phase 2 work.** Delete the spike once the real server lands (SC-008b, FR-018a, FR-021)

**Checkpoint**: `uv run ruff check packages/session_watcher/` runs clean, the hooks match the path,
and a containerized backend has successfully called a host-resident SSE tool. **The transport is
proven before anything depends on it** — discovering otherwise at the end of Phase 6 would cost the
design, not ten minutes.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Everything every story needs. No user story can start until this phase completes.

### Data model and the record seam

- [X] T007 Implement `Session`, `SessionEvent`, `SessionState`, `IdleReason` in `backend/packages/session_watcher/session_watcher/models.py`, enforcing at construction that `idle_reason` is non-None **iff** state is IDLE (FR-003, FR-003a; data-model.md)
- [X] T008 Implement `RecordSource` in `backend/packages/session_watcher/session_watcher/record_source.py` — `open()` as the **single seam** for opening any record, incrementing `stats.records_opened`, plus `stats.records_skipped` and `select_candidates(window)` filtering by mtime before parsing (**GATE 3 impl**; FR-005d, FR-005e, SC-004i)

### Adapter boundary

- [X] T009 [P] Define the `SessionAdapter` interface in `backend/packages/session_watcher/session_watcher/adapters/base.py` — `discover(window)` and `parse(record)`, where `parse` returning None means skip (FR-023, FR-009)
- [X] T010 Implement the Claude Code adapter in `backend/packages/session_watcher/session_watcher/adapters/claude_code.py` — the **only** format-aware file; read `sessionId` (alias `session_id`), `cwd`, `gitBranch`, `timestamp`, `type`, `isSidechain`; sidechain records update parent activity without creating a registry entry (FR-023, research R2)
- [X] T011 Implement record→event normalization in `backend/packages/session_watcher/session_watcher/events.py` — map each parsed record onto exactly one of `STARTED | PROGRESS | QUESTION | COMPLETED | FAILED`; a record matching no kind produces no event rather than a defaulted one (FR-007)
- [X] T012 [P] Test adapter against the fixture corpus in `backend/tests/session_watcher/test_adapter_claude_code.py` — malformed, truncated, and unknown-`type` records are skipped at debug level and never crash; other records in the same file still parse (FR-009, SC-005)
- [X] T013 [P] Test hyphen-prefixed path handling in `backend/tests/session_watcher/test_paths.py` — discovery works against the hyphen fixture directory, asserting `pathlib` handling end to end (FR-020, SC-006 groundwork)
- [X] T014 **GATE 1 VERIFY** — add `import omniharness` to a scratch file under `backend/packages/session_watcher/`, confirm `uv run ruff check packages/session_watcher/` **fails**, then remove it. Repeat for `import subprocess`. Record both outcomes in the PR description (plan.md standing convention)

### Discovery window

- [X] T015 Implement the recency window in `backend/packages/session_watcher/session_watcher/discovery.py` — configurable, default 24h; sessions observed active become `sticky` and are exempt from re-testing against the window on subsequent queries. Covers discovery of sessions started outside the assistant, with no user registration (FR-001, FR-005a, FR-005b, FR-005c)
- [X] T016 Test the startup bound in `backend/tests/session_watcher/test_discovery_window.py` — synthesise 5 000 records of which 5 fall inside the window, assert `stats.records_opened <= 10`. **Assert on records opened, never elapsed time** (SC-004i, SC-004g)
- [X] T017 **GATE 3 VERIFY** — temporarily bypass `RecordSource.select_candidates` so startup scans the whole directory; confirm `test_discovery_window.py` **fails on `records_opened`**. If it still passes, the assertion is on the wrong quantity (most likely elapsed time) and the requirement is unprotected. Restore and record the outcome (plan.md standing convention)
- [X] T018 [P] Test sticky membership in `backend/tests/session_watcher/test_discovery_window.py` — a session observed active then quiet beyond the window remains listed for the rest of its run (FR-005c, SC-004h)

### State machine

- [X] T019 Implement the state machine in `backend/packages/session_watcher/session_watcher/state.py` — **marker first, time second**: an observed end-of-turn record sets IDLE/COMPLETED immediately; only in its absence does the configurable inactivity period (default 5 min) set IDLE/STALLED. **Also emit UNKNOWN** when records exist but cannot be interpreted at all, rather than defaulting to any confident state (FR-006, FR-006a, FR-006b)
- [X] T020 [P] Test completed-vs-stalled in `backend/tests/session_watcher/test_state_machine.py` — a session recording end-of-turn reports COMPLETED; one killed without a marker reports STALLED; the two are never conflated, and a session with a marker is never reported stalled merely because the timeout also elapsed (SC-004a)
- [X] T021 [P] Test the quiet-but-working case in `backend/tests/session_watcher/test_state_machine.py` — a session quiet for less than the inactivity period still reports WORKING (SC-004b, FR-006b)

### Registry and liveness

- [X] T022 [P] Test the UNKNOWN state in `backend/tests/session_watcher/test_state_machine.py` — records present but uninterpretable yield UNKNOWN and never a confident state; assert UNKNOWN is distinguishable from IDLE/STALLED, since unknown means *could not interpret* while stalled means *interpreted and saw nothing* (FR-006, Article X)
- [X] T023 Implement `SessionRegistry` in `backend/packages/session_watcher/session_watcher/registry.py` — keyed by `session_id`, with `last_heartbeat_at`, configurable `heartbeat_interval_s` (default 30) and `staleness_threshold_s` (default 90), exposing `is_stale` (FR-002, FR-024a)
- [X] T024 Implement the observability tri-state in `registry.py` — populated+fresh, empty+fresh, and stale must be **three distinguishable conditions**, never two (FR-011a)
- [X] T025 [P] Test liveness in `backend/tests/session_watcher/test_registry_liveness.py` — with the watcher stopped, a query reports "cannot observe" and **never** "no sessions running", including when the registry is empty (SC-004e, FR-011a)

### Summarization

- [X] T026 Define `SummarizerPort` in `backend/packages/session_watcher/session_watcher/summarize/port.py` returning text plus `MODEL | MECHANICAL` provenance (FR-008c)
- [X] T027 Implement `MechanicalSummarizer` in `backend/packages/session_watcher/session_watcher/summarize/mechanical.py` as the **default** path — take the latest assistant message, strip fenced code blocks and terminal control sequences, collapse whitespace, clip at a sentence boundary, never mid-word. This is what gives every event its one-line summary (**GATE 2 impl**; FR-008, FR-008b, SC-004d)
- [X] T028 Implement `OnDemandModelSummarizer` in `backend/packages/session_watcher/session_watcher/summarize/on_demand_model.py` — acquire the model inside a context manager scoped to one batch, release on exit; the handle is never stored on the registry, adapter, or any module-level singleton (**GATE 2 impl**; FR-008a, Article VI)
- [X] T029 Test model release in `backend/tests/session_watcher/test_summarizer_lifecycle.py` — hold a `weakref` to the model handle, force collection after a batch, assert the referent is dead (**GATE 2**; Article VI, FR-008a)
- [X] T030 **GATE 2 VERIFY** — deliberately retain the model handle on the summarizer instance, confirm `test_summarizer_lifecycle.py` **fails** on the live weakref, then revert. Record the outcome (plan.md standing convention)
- [X] T031 [P] Test no-content-egress in `backend/tests/session_watcher/test_summarizer_lifecycle.py` — with no cloud provider opted in, a full observe-and-query cycle makes no outbound request (SC-004c, FR-008a)

### Redaction

- [X] T032 Implement the redactor in `backend/packages/session_watcher/session_watcher/redaction.py` — runs on **every** channel; `Channel.LOCAL | REMOTE` governs aggressiveness only; remote additionally shortens paths and trims code fragments; emits visible `[redacted]` markers; **raises on failure so the caller suppresses the send** (FR-011c, FR-011e, FR-011f)
- [X] T033 [P] Test redaction in `backend/tests/session_watcher/test_redaction.py` — seeded credential patterns never appear on any channel and are replaced by visible markers rather than silently dropped; a forced redactor error suppresses the reply entirely; remote replies carry no full paths or multi-line code while local ones do (SC-004k, SC-004l, SC-004m)
- [X] T034 [P] Assert the weaker claim in `backend/tests/session_watcher/test_redaction.py` — no user-facing string, docstring, or tool description states that the filter removes *secrets*; only *recognized patterns* (FR-011d, Article X)

### Zero writes and core isolation

- [X] T035 [P] Test zero writes in `backend/tests/session_watcher/test_zero_writes.py` — snapshot content hash, size, **and mtime** of every fixture record before a full observation cycle and assert all three unchanged after. Hash *and* mtime, because a write-then-restore leaves content equal (**GATE 1**; FR-019, SC-007)
- [X] T036 [P] Test core isolation in `backend/tests/session_watcher/test_no_core_imports.py` — walk the module's import graph and assert no `omniharness*` or `langgraph*` member appears; a runtime backstop for the static ruff ban (SC-008, Article I)

### Transport

- [X] T037 Implement the SSE MCP server in `backend/packages/session_watcher/session_watcher/server.py` using `mcp.server` with SSE transport, bound to a host-local address, `--port` defaulting to 18101 (FR-018, FR-018a)
- [X] T038 Add the `session-watcher` SSE entry to `extensions_config.json` per [contracts/mcp-tools.md](./contracts/mcp-tools.md) — `"type": "sse"`, `url` `http://host.docker.internal:18101/sse`. **stdio is forbidden**: it would be spawned as a backend subprocess and could not read the host's session directory under Docker (FR-018a, FR-021)
- [X] T039 Implement filesystem watching in `backend/packages/session_watcher/session_watcher/watcher.py` — `watchdog` observers as the fast path, plus a low-frequency reconciliation sweep so a coalesced or dropped event delays an update rather than losing it (FR-022, FR-024)
- [X] T040 [P] Test sleep/wake resilience in `backend/tests/session_watcher/test_reconciliation.py` — simulate a missed-event window, assert reconciliation restores correct state with no restart (FR-024, SC-006)

**Checkpoint**: full test suite green; all three gates implemented **and observed failing**.

---

## Phase 3: User Story 1 — Ask what my coding sessions are doing (P1) 🎯 MVP

**Goal**: A roll-up, from any channel, of every known session with project, state, last activity.

**Independent test**: Start two sessions in different projects, ask "what are my sessions doing?"
from a remote channel, confirm both appear with correct project and state.

- [X] T041 [US1] Implement the `list_coding_sessions` MCP tool in `backend/packages/session_watcher/session_watcher/server.py` — no arguments, Tier 1, returning `observable`, `as_of`, `staleness_seconds`, and `sessions[]` per the contract (FR-011, FR-014)
- [X] T042 [US1] Wire the `observable` flag from `SessionRegistry.is_stale` in `server.py` — an empty list with `observable: false` means *cannot see*; empty with `observable: true` means *nothing running* (FR-011a)
- [X] T043 [US1] Implement caveat-first reply composition in `backend/packages/session_watcher/session_watcher/reply.py` — when stale, the health caveat **leads** and last-known data with its age follows; never the reverse ordering (FR-011b)
- [X] T044 [P] [US1] Test the roll-up in `backend/tests/session_watcher/test_us1_rollup.py` — two live sessions yield one accurate line each within the answer budget, distinguishing working from completed (SC-001, SC-004)
- [X] T045 [P] [US1] Test caveat ordering in `backend/tests/session_watcher/test_us1_rollup.py` — every reply drawn from a stale registry presents the health caveat **before** any session data and states the data's age (SC-004f, FR-011b)
- [X] T046 [P] [US1] Test the empty-vs-unobservable distinction in `backend/tests/session_watcher/test_us1_rollup.py` — a stopped watcher with sessions running never produces "no sessions running" (SC-004e)

**Checkpoint**: User Story 1 is independently shippable. This is the MVP.

---

## Phase 4: User Story 2 — Spot the session that is blocked on me (P1)

**Goal**: Name the sessions waiting on a question, and say so honestly given it is an inference.

**Independent test**: Drive one session to a question, ask "is anything stuck waiting on me?",
confirm only that session is named with its pending question — and that the wording hedges.

- [X] T047 [US2] Implement waiting-on-user inference in `backend/packages/session_watcher/session_watcher/state.py` — latest record is `assistant`, no `user` record follows, inactivity threshold not yet elapsed (research R2 finding 3)
- [X] T048 [US2] Encode the error direction in `state.py` — when the inference is uncertain, resolve toward **possible-blocked rather than silence**. The errors are asymmetric: a false "waiting on you" costs one wasted walk to the machine, a false "working" leaves a blocked session all evening, which is the failure this feature exists to prevent (plan.md post-design ruling)
- [X] T049 [US2] Implement hedged wording in `backend/packages/session_watcher/session_watcher/reply.py` — the qualifier **leads** and the observable evidence accompanies it: "Looks like it's waiting on you — last activity was a question 8 minutes ago, nothing since" (FR-016a)
- [X] T050 [US2] Emit the waiting-on-user event in `backend/packages/session_watcher/session_watcher/events.py` for a future trigger consumer; **nothing consumes it this phase** and no proactive push is implemented (FR-010, FR-025)
- [X] T051 [P] [US2] Test the wording as an acceptance criterion in `backend/tests/session_watcher/test_us2_blocked.py` — assert the reply contains a hedge and the observable evidence (what was seen, when). Assert the bare-assertion shape "It's waiting for your input" is **never** produced (FR-016a, SC-010)
- [X] T052 [P] [US2] Test error direction in `backend/tests/session_watcher/test_us2_blocked.py` — an ambiguous case yields a possible-blocked flag rather than silence or a confident WORKING (plan.md post-design ruling)
- [X] T053 [P] [US2] Test blocked-session identification in `backend/tests/session_watcher/test_us2_blocked.py` — with one waiting and one working, only the waiting session is named, and a session that receives its answer stops being reported as waiting (SC-002)
- [X] T054 [P] [US2] Test the observe-only refusal in `backend/tests/session_watcher/test_us2_blocked.py` — asking the assistant to answer or intervene yields a plain statement of the limit and no attempted action. There is no tool to call; verify the surface offers none (FR-015, SC-010)
- [X] T055 [US2] **TIMEBOXED SPIKE (max 1 day)** — investigate whether `mode` / `permission-mode` records carry a permission-prompt state that would upgrade the inference toward observation. Record findings in `specs/001-coding-session-watcher/research.md`. **Exit condition**: if a bounded look comes back empty, state the limit plainly in the reply wording and ship on the inference. **This task must not block T047–T054** — Story 2 ships either way, and a P1 story must not wait on reverse-engineering a format that is explicitly not a public API (research R2 finding 3)

**Checkpoint**: Stories 1 and 2 together deliver the full P1 slice.

---

## Phase 5: User Story 3 — Ask about one session in detail (P2)

**Goal**: Drill into one session — elapsed time, what it has done, its last message.

**Independent test**: With one session running, ask about it by project name; confirm elapsed
time, recent activity, and last message are accurate.

- [X] T056 [US3] Implement the `get_session_status` MCP tool in `backend/packages/session_watcher/session_watcher/server.py` — accepts a session id or project name, Tier 1, returning `found`, `ambiguous`, `candidates`, and `session` per the contract (FR-012, FR-013, FR-014)
- [X] T057 [US3] Implement `SessionDetail` assembly in `backend/packages/session_watcher/session_watcher/registry.py` — `started_at`, `elapsed_seconds`, and ordered `recent_events` each carrying summary provenance (FR-013, FR-008c)
- [X] T058 [P] [US3] Test detail retrieval in `backend/tests/session_watcher/test_us3_detail.py` — elapsed time and ordered activity summary are accurate; an unknown project yields "not found" rather than a similar session (FR-012)
- [X] T059 [P] [US3] Test ambiguity handling in `backend/tests/session_watcher/test_us3_detail.py` — a project reference matching two sessions returns `ambiguous` with candidates, and the assistant asks which one rather than picking (FR-017)

---

## Phase 6: User Story 4 — Status stays correct as sessions come and go (P2)

**Goal**: Kills, completions, and fresh starts all reflected without a watcher restart.

**Independent test**: While the watcher runs, kill one session, let another complete, start a
third; ask for the roll-up and confirm all three are represented correctly.

- [X] T060 [US4] Implement registry lifecycle transitions in `backend/packages/session_watcher/session_watcher/registry.py` — terminal sessions retain their terminal state; new sessions are discovered live; nothing requires a restart (FR-004, FR-005)
- [X] T061 [P] [US4] Test the kill/complete/start cycle in `backend/tests/session_watcher/test_us4_lifecycle.py` — all three reflected correctly with no restart; the killed session reports stalled and is described as possibly stalled or killed, not finished (SC-003, SC-004a)
- [X] T062 [P] [US4] Test sleep/wake in `backend/tests/session_watcher/test_us4_lifecycle.py` — after a simulated sleep/wake the watcher answers correctly for all previously known sessions with no user action (SC-006, FR-024)
- [X] T063 [P] [US4] Test late discovery in `backend/tests/session_watcher/test_us4_lifecycle.py` — a session started after the watcher launches appears without restart, and a pre-existing mid-run session is discovered rather than ignored until its next activity (FR-005, FR-005b)

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T064 [P] Test the first-query latency smoke bound in `backend/tests/session_watcher/test_startup.py` — first status answerable within 5 s of launch regardless of history size. **This is a smoke assertion with generous margin and is explicitly NOT the mechanism protecting FR-005e** — T016 is (SC-004j)
- [X] T065 [P] Verify Windows path behaviour in `backend/tests/session_watcher/test_paths.py` — path handling correct under Windows conventions, including the hyphen-prefixed directory (FR-020)
- [X] T066 Test MCP surface stability in `backend/tests/session_watcher/test_contract.py` — the tool set, names, and arguments match [contracts/mcp-tools.md](./contracts/mcp-tools.md) exactly; adding an adapter must not change them. **Also assert sole-reachability**: disabling the `session-watcher` entry in `extensions_config.json` removes the capabilities entirely, leaving no residual path (FR-018b, FR-023, SC-008a). *SC-011 — that a second adapter needs no change beyond the adapter — is only fully verifiable once one exists; the tool-surface half is asserted here, the remainder deferred to that feature*
- [X] T067 [P] Confirm no write surface exists in `backend/tests/session_watcher/test_contract.py` — neither tool accepts a mutation argument and no third tool is registered. The observe-only limit is enforced by absence, not policy (FR-015, Article IV)
- [X] T068 [P] Test honest absence in `backend/tests/session_watcher/test_contract.py` — any field the watcher has not observed is returned as null and stated as absent; assert no field is ever populated with an estimate or a plausible-looking default (FR-016, Article X)
- [X] T069 Walk every scenario in [quickstart.md](./quickstart.md) manually against two real sessions and record results, including the documented idle-RSS measurement (Article VI, SC-009)
- [X] T070 [P] Write `backend/packages/session_watcher/README.md` — how to run on the host, the configurable values and their defaults (inactivity 5 min, heartbeat 30 s, staleness 90 s, window 24 h), and a plain statement that externally-started sessions are observe-only (FR-015, Article X)
- [X] T071 **Containerized end-to-end validation** — run the backend in Docker with the real watcher (not the Phase 1 spike) on the host; confirm the containerized backend reaches it over SSE and receives real session data. **Scope corrected:** this demonstrates that the chosen transport works end to end. It does NOT validate the stdio exclusion — `~/.claude` is bind-mounted into the container (research.md R6b), so stdio is excluded on process-lifecycle grounds, which no runtime check here exercises. A validation that overclaims its own scope is the same defect as a gate that never fails (SC-008b, FR-018a, FR-021)
- [X] T072 Record gate-verification outcomes from T014, T017, and T030 in [gate-verification.md](./gate-verification.md) (a PR description is not durable). **A gate whose failure was never observed is not done** (plan.md standing convention)

---

## Dependencies

```
Phase 1 (Setup)  →  Phase 2 (Foundational)  →  ┬→ Phase 3 (US1, P1)  ─┐
                                               ├→ Phase 4 (US2, P1)  ─┤→ Phase 7 (Polish)
                                               ├→ Phase 5 (US3, P2)  ─┤
                                               └→ Phase 6 (US4, P2)  ─┘
```

- **Phase 2 blocks everything.** Every story needs the adapter, registry, state machine, and
  transport.
- **US1–US4 are mutually independent** once Phase 2 lands and may proceed in parallel.
- **T055 (spike) blocks nothing.** It runs alongside US2 and cannot delay it.
- Gate verifications (T014, T017, T030) depend only on their own gate's implementation.

## Parallel Execution Examples

**Phase 2, after T010:** T012, T013 run together (different test files).
**Phase 2, after T027/T028:** T029, T031 run together; T032–T034 run alongside T035/T036.
**Phase 3:** T044, T045, T046 run together once T041–T043 land.
**Phase 4:** T051, T052, T053, T054 run together once T047–T050 land; T055 runs throughout.
**Across stories:** with Phase 2 complete, four developers can take US1–US4 simultaneously.

## Implementation Strategy

**MVP = Phase 1 + Phase 2 + Phase 3 (US1).** A roll-up of what every session is doing, answerable
from a phone, is already the daily value the feature exists for (Article IX).

**Increment 2 = Phase 4 (US2)** completes the P1 slice — the blocked-session case is what turns
the roll-up from informative into actionable.

**Increment 3 = Phases 5–6 (US3, US4)** add detail and lifecycle correctness.

**Phase 7 before release.** T072 in particular: the three gates are the feature's constitutional
guarantees, and an unverified gate is a guarantee in name only.
