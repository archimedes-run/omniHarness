---
description: "Task list for feature 002 — trigger & scheduler engine"
---

# Tasks: Trigger & Scheduler Engine

**Input**: Design documents from `/specs/002-trigger-scheduler-engine/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/rule-schema.md](./contracts/rule-schema.md)

**Tests**: Included. 50 functional requirements and 34 success criteria demand them, and four
gates require observed failures.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1–US5, mapping to the spec's user stories
- **GATE**: a plan-review gate. Each has an implementation task **and** a separate
  observe-it-fail task — a gate never seen failing is indistinguishable from one that does
  nothing.

## Path Conventions

Module: `backend/app/trigger_engine/` · Tests: `backend/tests/trigger_engine/`

---

## Phase 1: Setup

**Purpose**: Module skeleton, the two import gates, and the dependency the engine needs.

- [X] T001 Create the module skeleton at `backend/app/trigger_engine/__init__.py` with the package layout from plan.md (sources/, politeness/, destinations/) — placed under `backend/app/` alongside `gateway/` and `channels/` because it runs in that process and is a peer of the channel manager (FR-024)
- [X] T002 [P] Create `backend/app/trigger_engine/ruff.toml` banning `omniharness`, `langgraph`, `langgraph.*`, `app.gateway.routers`, `subprocess`, `os.system`, `os.popen` — with **`langgraph_sdk` allowed as a named exception carrying its rationale in a comment**: it is a client for a server, not a reach into internals (**GATE 1 impl**; SC-011, Article I)
- [X] T003 [P] Add `croniter` (schedule arithmetic) and a dead-code detector (`vulture` or equivalent) to `backend/pyproject.toml` dev dependencies and run `uv sync` (FR-018, GATE 4)
- [X] T004 Create `backend/tests/trigger_engine/conftest.py` with fixtures for a fake clock, an in-memory destination, and a rule-file factory. **Do not add `__init__.py`** — `backend/tests/` has none, and adding one puts `tests/` on `sys.path` where the directory shadows the real package (the Feature 001 lesson)
- [X] T005 [P] Build the rule-file fixture corpus in `backend/tests/trigger_engine/fixtures/` — valid rules of each type, a duplicate id, a template referencing an unavailable field, a `calendar` rule, and a syntactically invalid file (FR-006)
- [X] T006 **GATE 1 VERIFY — both directions.** (a) Add `import langgraph.graph` to a scratch file under the module and confirm `uv run ruff check app/trigger_engine/` **fails**. (b) Remove the `langgraph_sdk` exception from `ruff.toml` and confirm the check **also fails**, because the SDK is required. Restore both. **A one-directional test would let a later simplification restore the glob or drop the ban, and neither would fail** (plan.md standing convention)

- [X] T007 **INJECTION SPIKE — blocking, run before Phase 2.** Drive the engine's own chain end to end against a real gateway: resolve a thread, set its tools, inject a synthetic turn carrying the FR-009 provenance marker, observe the reply, confirm the marker survives. **Not "does the endpoint exist"** — reading proved that; this proves the caller we are about to build. Run **in-process**, because `create_internal_auth_headers()` is process-local and no other process reproduces the engine's real situation. **RESULT: PASS** (2026-08-21), and it corrected three assumptions that would otherwise have surfaced deep in Phase 3: `assistant_id` is `lead_agent` not `agent`; the tools body field is `sources` not `tool_ids`; and the provenance marker is **absent from the `runs/wait` response body** — it is observable via `GET /threads/{id}/state` and `/runs`, so FR-009 must read it from the run record (FR-007, FR-009, FR-011, SC-015)

**Checkpoint**: lint clean, both ban directions observed, and **the injection chain proven against a real gateway before anything is built on it**.

---

## Phase 2a: Foundational — data, injection, and the delivery path

**Purpose**: the foundation every story needs. Ends at a reviewable checkpoint before the engine
and scheduler are built on top of it.

### Models and configuration

- [X] T008 Implement `Rule`, `TriggerEvent`, `Firing`, `Outcome`, `TriggerType` in `backend/app/trigger_engine/models.py` per data-model.md, enforcing that every non-`DELIVERED` outcome carries a reason — a firing that vanished without one is indistinguishable from one that never happened (FR-012)
- [X] T009 Implement rule-file loading and validation in `backend/app/trigger_engine/config.py` — unique ids (duplicates are a load-time error since the id is the thread-map key), per-type `match` validation, and **template fields validated at load** so a missing field is not a render-time surprise (FR-001, FR-006, contracts/rule-schema.md)
- [X] T010 Implement hot reload in `config.py` — changes take effect on the next evaluation; **an invalid config leaves the previous one in effect and reports the error.** A config that fails open is worse than one that fails to load, because nobody notices (FR-005, FR-006)
- [X] T011 [P] Reject `calendar` rules at load with an explicit not-implemented error in `config.py`, so adding the type later is a new source rather than a schema migration (FR-003)
- [X] T012 [P] Test config load, validation, and hot reload in `backend/tests/trigger_engine/test_config_reload.py` — including that a syntax error leaves the prior config active (SC-008, SC-009)

### Event identity

- [X] T013 Implement fingerprinting in `backend/app/trigger_engine/fingerprint.py` — key is `(rule_id, event_id, hash(canonical(inputs)))`, with **the permitted inputs enumerated per trigger type** exactly as data-model.md tabulates them (FR-017a, FR-017b)
- [X] T014 Implement the daily fingerprint reset and durable store in `fingerprint.py`, JSON-backed with atomic writes following `app/channels/store.py`. Durable because a restart must not re-fire everything already delivered (FR-017c)
- [X] T015 [P] Test fingerprint identity in `backend/tests/trigger_engine/test_fingerprint.py` — a changed question yields a new event and fires; an unchanged one does not (SC-002, SC-002a)
- [X] T016 [P] **Test that no drifting field contributes** in `test_fingerprint.py` — run **100 consecutive evaluations against an unchanged blocked session and assert exactly one delivery**. A drifting input makes every cycle yield a "new" event, which is FR-017's failure inverted and the worse of the two because it is the version that gets the feature muted (SC-002b, FR-017b)
- [X] T017 [P] Test fingerprint retention in `test_fingerprint.py` — the store does not grow across a multi-day run (SC-002c)

### Thread mapping

- [X] T018 Implement the durable rule-id → thread-id map in `backend/app/trigger_engine/threads.py`, JSON-backed and atomically written, creating a thread on first firing and reusing it thereafter (FR-011a, FR-011b)
- [X] T019 Implement the rolling firing-retention window in `threads.py` so a rule thread keeps recent context rather than months of it (FR-011c)
- [X] T020 [P] **Test that the mapping survives a restart** in `backend/tests/trigger_engine/test_threads_mapping.py` — construct a fresh mapper against the same store and assert the same thread id. A mapping held only in memory presents as a stable thread and behaves as a fresh one (SC-015b, FR-011b)
- [X] T021 [P] Test cross-firing continuity in `backend/tests/trigger_engine/test_threads_mapping.py` — a rule fired on two consecutive days targets the same thread and the second firing can reference the first; and after more firings than the retention window allows, the thread holds only the configured number (SC-015a, SC-015c, FR-011c)
- [X] T022 [P] Test thread-mapping edge cases in `test_threads_mapping.py` — a deleted thread is treated as a first firing; a renamed rule gets a new thread and does not inherit the old mapping (FR-011a)

### Injection and provenance

- [X] T023 Implement turn injection in `backend/app/trigger_engine/injector.py` using `langgraph_sdk`'s `client.runs.wait()` with `create_internal_auth_headers()`, following the pattern already in production at `app/channels/manager.py:749` (FR-007, research R1/R2)
- [X] T024 Implement synthetic-turn provenance marking in `injector.py` — **structural, not a content convention** — so a trigger turn is distinguishable from a user turn by shape (FR-009)
- [X] T025 Implement the confirmation guard so trigger-injected content cannot satisfy a confirmation requiring a trusted channel, **regardless of what the content says** (FR-010, Article III)
- [X] T026 [P] Test provenance and the confirmation guard in `backend/tests/trigger_engine/test_injection_provenance.py` — including content **crafted to resemble** a user confirmation, which must still fail (SC-014)
- [X] T027 Implement thread tool configuration in `injector.py` via `PUT /api/threads/{thread_id}/tools` before injecting, so a system-initiated turn has the tools its prompt needs with no human to attach them (FR-011, SC-015)

### Presence

- [X] T028 Implement presence in `backend/app/trigger_engine/presence.py` as the timestamp of the most recent turn **lacking** the synthetic marker — derived from provenance rather than tracked separately, so there is no second source of truth to drift (FR-022, research R4)
- [X] T029 Expose the presence signal for runtime inspection in `backend/app/trigger_engine/presence.py` — readable while only remote destinations are registered, so adding the local destination later needs no rework of presence itself (FR-023)
- [X] T030 [P] Test presence in `backend/tests/trigger_engine/test_presence.py` — asserting it is **unaffected by the engine host's own idle state**, that it never reads the engine's own injected turns as user activity, and that it is inspectable at runtime (SC-016, FR-022, FR-023)

### Audit log — before the delivery paths, not after

*Ahead of `release()` deliberately. Audit logging is cross-cutting: every delivery path must call
it, so landing it last means retrofitting call sites into paths already written. It is also the
first casualty if this phase is cut short, which is the wrong property for a constitutional
obligation.*

- [X] T031 Implement the audit log in `backend/app/trigger_engine/audit.py` — append every firing and its outcome (delivered / suppressed / queued / expired / failed) with its reason to the local append-only log Article VIII names (FR-012, FR-012a)
- [X] T032 [P] Test audit completeness in `backend/tests/trigger_engine/test_audit.py` — drive one firing of each outcome and read the log back, asserting all five appear with their reasons (SC-010a)

### The release path

- [X] T033 Implement `release(items, reason)` in `backend/app/trigger_engine/politeness/release.py` as the **single** delivery mechanism: re-check → coalesce → redact → deliver. Quiet-hours release, queue expiry, and immediate delivery are three entry conditions into this one function (**GATE 3 impl**; FR-013b, FR-013d, FR-016c)
- [X] T034 Implement coalescing in `backend/app/trigger_engine/politeness/coalesce.py` — firings within the window merge into one delivered message (FR-015)
- [X] T035 Implement the output-destination port and its two implementations in `backend/app/trigger_engine/destinations/` — remote (Telegram) and quiet (records, delivers nothing), with `auto` resolving to remote while no local destination is registered (FR-019, FR-020, FR-021)
- [X] T036 Wire redaction into `release.py` at the delivery boundary for **every** destination including quiet, failing closed with the can't-relay message. This matters more here than in Feature 001, not less: no human is waiting on a proactive reply, so a silent pass-through would be invisible (FR-008a, FR-008b)
- [X] T037 [P] **Widen the recognized-pattern set** in `backend/packages/session_watcher/session_watcher/redaction.py` to cover cloud credentials, bearer tokens, private-key headers, and env-style assignments — agent-composed output can contain anything the agent can reach. **Keep the "recognized patterns, never secrets" wording unchanged**; widening coverage does not license strengthening the claim (FR-008c, FR-008d)
- [X] T038 [P] Test the widened patterns in `backend/tests/session_watcher/test_redaction.py` — seeded credential patterns never appear in any delivered message on any destination; a forced redactor error suppresses delivery entirely; each newly covered shape (cloud credential, bearer token, private-key header, env assignment) verified by its own seeded case (SC-014a, SC-014b, SC-014c)
- [X] T039 [P] **Give the redactor's own suite both input shapes** in `backend/tests/session_watcher/test_redaction.py` — session-record text **and** arbitrary agent output — so a pattern change made for this feature cannot silently break Feature 001's case. Neither consumer's tests currently guard the other's input shape, and that is the whole risk of sharing the module (plan.md, shared-redactor decision)
- [X] T040 **Prove `release()` actually delivers** in `backend/tests/trigger_engine/test_release_path.py` — drive one firing through re-check → coalesce → redact → the quiet destination and assert it arrives with content intact. Gate 3 verifies that a *second* path fails the test; it does not verify that *this* path works, and four entry conditions are about to depend on it (FR-013b, FR-013d, FR-015)
- [X] T041 **GATE 3 VERIFY** — add a second delivery path that bypasses `release()` and confirm `backend/tests/trigger_engine/test_release_path.py` **fails**; restore and confirm it passes. Implemented twice, the copy that runs least often acquires defects nobody sees (plan.md standing convention)

### The engine, supervised

**CHECKPOINT — end of Phase 2a.** Models, config, fingerprint, threads, injector, presence, audit,
`release()`, coalescing and redaction have landed; Gates 1 and 3 have been observed failing; and
`release()` has been observed *delivering*. Everything after this point **builds on** that
foundation rather than being part of it.

---

## Phase 2b: Foundational — engine, scheduling, sources, wiring gate

**Purpose**: the machinery that drives the foundation built in 2a.

- [ ] T042 Implement the evaluation loop in `backend/app/trigger_engine/engine.py` — **each rule evaluated inside its own supervised task with an exception barrier and a timeout**, and no rule work on a request-handling path (**GATE 2 impl**; FR-030, FR-031, FR-032)
- [ ] T043 Implement error backoff in `engine.py` — a repeatedly failing rule is reported and its retry rate reduced, never silently retried forever at full rate (FR-026)
- [ ] T044 [P] Test blast radius in `backend/tests/trigger_engine/test_blast_radius.py` — a **crashing** rule does not stop the engine and every other rule still evaluates; a **blocking** rule is bounded, abandoned and reported, and ordinary requests serve with no measurable added latency while it hangs (SC-017, SC-018, FR-033)
- [ ] T045 **GATE 2 VERIFY** — remove the exception barrier and confirm the crashing-rule test **fails**; remove the timeout and confirm the blocking-rule test **fails**. Restore both. Feature 001 got this boundary free from process separation; sharing the gateway process removes it, and an isolation claim never tested against a real failure is not evidence (plan.md standing convention)

### Scheduling and sources

- [ ] T046 Implement the scheduler in `backend/app/trigger_engine/scheduler.py` — compute the next due moment across all rules, sleep until it, evaluate, recompute. **No tick loop** (FR-027)
- [ ] T047 Implement missed-schedule and clock-jump handling in `scheduler.py` — a schedule passed while stopped fires **once, late**; sleep/wake, NTP correction and DST each yield at most one fire per scheduled instant (FR-018)
- [ ] T048 [P] Implement the trigger-source interface and the cron source in `backend/app/trigger_engine/sources/base.py` and `sources/cron.py` (FR-002)
- [ ] T049 [P] Implement the watcher source in `backend/app/trigger_engine/sources/watcher.py`, consuming Feature 001's events over its MCP surface. **It may be on another host** — no co-location assumption (FR-002, FR-028)
- [ ] T050 [P] Implement the completion source in `backend/app/trigger_engine/sources/completion.py` (FR-002)
- [ ] T051 Implement unreachable-source handling in `sources/watcher.py` — an unreachable source is an **unobservable condition**, never an absence of events, and nothing may report or act as though it had successfully observed nothing (FR-029, SC-013, Article X)
- [ ] T052 [P] Test the scheduler in `backend/tests/trigger_engine/test_scheduler.py` — one fire per scheduled instant across restart, sleep/wake and DST (SC-003, SC-004)

### Audit log


### Gate 4 — wiring

- [ ] T053 Configure cross-module dead-code detection over `backend/app/trigger_engine/` **with the test tree excluded**, so anything defined and never referenced outside tests fails the build (**GATE 4 impl**; plan.md)
- [ ] T054 Whitelist framework-invoked entry points for the Gate 4 check — decorated handlers, `main()`, and polymorphic port implementations — **with a comment on every entry explaining why**. An unexplained whitelist entry is indistinguishable from one added to silence a real finding, which is the obvious way this gate quietly stops working (plan.md)
- [ ] T055 **GATE 4 VERIFY** — delete a real call site (the `release()` call in the engine's delivery path, the direct analogue of Feature 001's unwired `merge()`) and confirm the check **fails**; restore and confirm it passes. Four defects of this shape have been found in this project, every one by running the service and none by the suite (plan.md standing convention)

**Checkpoint**: full suite green; all four gates implemented **and observed failing**.

---

## Phase 3: User Story 1 — Tell me a session is blocked while I'm away (P1) 🎯 MVP

**Goal**: A blocked session produces one message on the phone, and only one.

**Independent test**: Drive a watched session into a waiting state; confirm exactly one message
naming that session, and none while it stays blocked.

- [ ] T056 [US1] Wire the watcher source through evaluation to `release()` in `backend/app/trigger_engine/engine.py`, so a waiting-on-user event composes a prompt, injects a turn, and delivers the reply (FR-007, FR-008)
- [ ] T057 [US1] Implement prompt-template interpolation from event fields in `backend/app/trigger_engine/config.py` (FR-004)
- [ ] T058 [P] [US1] Test the blocked-session path end to end in `backend/tests/trigger_engine/test_us1_blocked_session.py` — one delivered message within the bound, naming the session and its apparent question (SC-001)
- [ ] T059 [P] [US1] Test no-repetition in `test_us1_blocked_session.py` — a session that stays blocked produces no second message; one answered and blocked again on a **different** question does (SC-002, SC-002a)
- [ ] T060 [P] [US1] Test non-matching rules in `test_us1_blocked_session.py` — a rule whose criteria do not cover the event does not fire (Story 1 scenario 4)

**Checkpoint**: US1 is independently shippable. **This is the MVP** — a blocked session reaching
your phone is the whole payoff for Feature 001's unconsumed event.

---

## Phase 4: User Story 2 — A briefing on its own schedule (P1)

**Goal**: A scheduled rule delivers once per scheduled time, including across sleep/wake.

**Independent test**: Run across several scheduled times including a sleep/wake cycle; confirm one
delivery each, none missed, none duplicated.

- [ ] T061 [US2] Wire the cron source through evaluation to `release()` in `engine.py` (FR-002, FR-018)
- [ ] T062 [US2] Persist last-fired times per scheduled instant in `backend/app/trigger_engine/scheduler.py` so restarts neither skip nor re-fire (FR-018)
- [ ] T063 [P] [US2] Test the seven-day schedule in `backend/tests/trigger_engine/test_scheduler.py` — exactly one delivery per scheduled time, zero missed, zero duplicated (SC-003)
- [ ] T064 [P] [US2] Test the missed-schedule case in `test_scheduler.py` — a time that passes while stopped fires **once, late**, rather than being skipped or fired once per missed tick (SC-004)

---

## Phase 5: User Story 3 — Several things happen and I get one message (P1)

**Goal**: Rules firing together arrive as one message.

**Independent test**: Fire three rules inside the window; confirm exactly one message containing
all three.

- [ ] T065 [US3] Wire coalescing into the `release()` path in `backend/app/trigger_engine/politeness/release.py` (FR-015)
- [ ] T066 [P] [US3] Test coalescing in `backend/tests/trigger_engine/test_coalesce.py` — three rules within the window produce one message with all three; two far apart produce two, so coalescing never delays unrelated items indefinitely (SC-005)
- [ ] T067 [P] [US3] Test window accumulation in `test_coalesce.py` — a rule firing while a window is open joins it rather than starting a new one (Story 3 scenario 3)

---

## Phase 6: User Story 4 — Don't wake me, don't talk over me (P1)

**Goal**: Nothing non-urgent in quiet hours; nothing mid-exchange.

**Independent test**: Fire a non-urgent rule in quiet hours and confirm silence plus a recorded
reason; mark it urgent and confirm delivery. Separately, fire during an exchange and confirm
delivery after.

- [ ] T068 [US4] Implement quiet-hours suppression and **deferral** in `backend/app/trigger_engine/politeness/quiet_hours.py`, handling a window that spans midnight (FR-013, FR-013a)
- [ ] T069 [US4] Implement release-time re-check in `quiet_hours.py` — only items whose condition still holds are delivered; **event types with no re-checkable condition expire rather than deliver blind**, so "re-check" is never implemented as "deliver anything we cannot disprove" (FR-013b, FR-013c)
- [ ] T070 [US4] Route the quiet-hours release **through `release()`** so a backlog arrives as one message. A release that bypasses coalescing produces a notification storm at the moment the user wakes, which is the single behaviour most likely to get the feature muted (FR-013d)
- [ ] T071 [US4] Implement the explicit per-rule urgent override in `quiet_hours.py`, with **no implicit escalation** (FR-014)
- [ ] T072 [US4] Implement mid-exchange detection in `backend/app/trigger_engine/politeness/interrupt.py` — query `GET /api/threads/{id}/state`, and treat a `ConflictError` on injection as the race fallback as the channel manager does (FR-016, research R3)
- [ ] T073 [US4] Implement the queued-turn bound in `interrupt.py`, **as the primary release path rather than a fallback**: both mid-exchange signals are pull, so for a hung run no completion signal will ever arrive and this is the only mechanism that will release the item. Document its default as a **heuristic** in the code as well as the spec (FR-016a, FR-016b, Article X)
- [ ] T074 [US4] Route queue-expiry release **through the same `release()`** as quiet hours (FR-016c, GATE 3)
- [ ] T075 [P] [US4] Test quiet hours in `backend/tests/trigger_engine/test_quiet_hours.py` — non-urgent suppressed with reason recorded, urgent delivered, a blocked session surviving re-check delivered at release, a resolved one not, and a suppressed cron item expiring (SC-006, SC-006a, SC-006b, SC-006c)
- [ ] T076 [P] [US4] Test backlog coalescing in `test_quiet_hours.py` — six items surviving re-check arrive as **one** message (SC-006d)
- [ ] T077 [P] [US4] Test the interrupt queue in `backend/tests/trigger_engine/test_interrupt_queue.py` — delivery after the exchange and never during; an exchange emitting **no completion signal** still releases at the bound; multiple queued items arrive coalesced (SC-007, SC-007a, SC-007c)
- [ ] T078 [P] [US4] Test the shared release path in `backend/tests/trigger_engine/test_release_path.py` — assert quiet-hours release and queue-expiry release reach the **same** function (SC-007b, GATE 3)

---

## Phase 7: User Story 5 — Change rules without stopping (P2)

**Goal**: Rules editable live.

**Independent test**: Add, edit and remove rules while running; each takes effect with no restart.

- [ ] T079 [US5] Wire hot reload into the running engine in `backend/app/trigger_engine/engine.py` so config changes apply on the next evaluation (FR-005)
- [ ] T080 [P] [US5] Test add, edit and remove without restart in `backend/tests/trigger_engine/test_config_reload.py` (SC-008)
- [ ] T081 [P] [US5] Test that an invalid edit leaves the prior configuration active and reports the error in `test_config_reload.py` (SC-009)

---

## Phase 8: Polish & Cross-Cutting Concerns

- [ ] T082 **Service-level smoke test** in `backend/tests/trigger_engine/test_smoke_end_to_end.py` — start the engine for real against a live gateway and drive one rule end to end. **Gate 4 explicitly does not catch a function called with wrong arguments, or called from a branch that never executes**; this is the only check that does, and it is the activity that found all four wiring defects in this project (plan.md)
- [ ] T083 [P] Test rule isolation in `backend/tests/trigger_engine/test_blast_radius.py` — one rule's error prevents no other rule from being evaluated in the same cycle, and never stops the engine (SC-010, FR-025)
- [ ] T084 [P] Test the banned-import backstop in `backend/tests/trigger_engine/test_no_banned_imports.py` — walk the module's import graph and assert no `omniharness`/`langgraph` member appears, **while `langgraph_sdk` does** (SC-011, GATE 1)
- [ ] T085 [P] Measure idle cost with no rule due and record it — documented, not CI-gated, since absolute RSS is environment-dependent and a flaky constitutional gate is worse than a recorded measurement (SC-012, Article VI)
- [ ] T086 [P] Test the unreachable-source case in `backend/tests/trigger_engine/test_sources.py` — watcher rules do not fire, the condition is observable, and no reply states or implies that no events occurred (SC-013, FR-029)
- [ ] T087 [P] Write `backend/app/trigger_engine/README.md` — how to author rules, the configurable values and their **stated-heuristic** defaults, the four gates and how to break each, and the plain statement that this feature makes the assistant act with no human in the loop
- [ ] T088 Walk every scenario in [quickstart.md](./quickstart.md) manually and record results
- [ ] T089 Record gate-verification outcomes from T006, T041, T045 and T055 in `specs/002-trigger-scheduler-engine/gate-verification.md` — durable, because a PR description is not. **A gate whose failure was never observed is not done**

---

## Dependencies

```
Phase 1 (Setup + INJECTION SPIKE)
    │   the spike is blocking — if the chain does not work, nothing after it matters
    ▼
Phase 2a (foundation: data, injection, audit, release path)
    │   ← CHECKPOINT: gates 1 & 3 observed failing, release() observed delivering
    ▼
Phase 2b (engine, scheduler, sources, Gate 4)
    │
    ├→ Phase 3 (US1, P1) 🎯 MVP
    ├→ Phase 4 (US2, P1)
    ├→ Phase 5 (US3, P1)
    ├→ Phase 6 (US4, P1)
    └→ Phase 7 (US5, P2)
                                  └→ Phase 8 (Polish)
```

- **The Phase 1 spike blocks Phase 2a.** It proves the caller works against a real gateway; it
  already corrected three assumptions that would otherwise have surfaced in Phase 3.
- **Phase 2a blocks Phase 2b**, and the checkpoint between them is where to stop and review.
- **Phase 2b blocks all user stories.** US1–US5 are mutually independent after it.
- Gate verifications depend only on their own gate's implementation.
- The redaction tasks touch Feature 001's module and tests; independent of the rest of 2a.

## Parallel Execution Examples

**Phase 2, after T014:** T015, T016, T017 together (same file, coordinate) — T020, T022 in parallel.
**Phase 2, after T036:** T037, T039 alongside T044, T052.
**Phase 6:** T075, T076, T077, T078 together once T068–T074 land.
**Across stories:** with Phase 2 complete, five developers can take US1–US5 simultaneously.

## Implementation Strategy

**MVP = Phase 1 + Phase 2 + Phase 3 (US1).** A blocked session reaching your phone is the payoff
for the event Feature 001 already emits and nothing consumes.

**Increment 2 = Phases 4–6** completes the P1 set. US4 in particular is not optional polish:
Article VII makes politeness a requirement, and a proactive feature that is impolite gets muted,
after which every other requirement is moot.

**Increment 3 = Phase 7** makes rules cheap to experiment with.

**Phase 8 before release.** T089 especially — four gates are this feature's constitutional
guarantees, and an unverified gate is a guarantee in name only.
