---
description: "Task list for Feature 004 — Assistant UI Surfaces"
---

# Tasks: Assistant UI Surfaces

**Input**: Design documents from `/specs/004-assistant-ui-surfaces/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/api.md

**Tests**: Requested and required. FR-035 makes rendered-output assertions a
requirement, and every gate ships with a sabotage.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1 pending confirmations, US2 trigger activity, US3 coding sessions,
  US4 policy inspector

## Phase numbering

Phases follow **plan.md**, not the generic template. Phases 1 and 2 are backend and
**ship no UI by design** — they are not user-story phases and carry no story label.

---

## Phase 1: The confirmation completion path (no UI) 🚨 BLOCKING

**Purpose**: Make Tier 3 grantable. On main it is deny-with-explanation: the assistant
states the plan, records a `PendingAction`, and no code path can ever grant it. The user
approves, nothing happens, approves again, nothing happens, and learns to route around
the gate by doing the thing manually.

**This phase is a real release boundary.** It delivers value with no UI at all, and
nothing in it may depend on work sequenced later.

### Observing the defect first

- [ ] T001 Write `backend/tests/policy/test_confirmation_completes.py` asserting that a Tier 3 action proposed in an agent run and answered with a recognised confirmation is executed once and audited. It MUST FAIL on current main with the action still open — record the failure output in the commit message
- [ ] T002 Confirm T001's failure is the missing path and not a harness error: assert in the same run that the `PendingAction` was created and `open_actions` returns it, so "nothing executed" cannot be confused with "nothing was proposed"

### The single shared implementation

- [ ] T003 Create `backend/app/policy/confirm_flow.py` with one function taking a message or an explicit verdict, a `PendingActionStore`, a runtime context and a tool runner, performing recognise → **scope-threshold check** → claim → `execute_confirmed` → resolve, and returning one of exactly seven outcomes: `executed`, `declined`, `already_resolved`, `expired`, `targets_drifted`, `unrecognised`, `threshold_not_met` (FR-004)
- [ ] T004 [P] Unit-test every outcome branch of `confirm_flow` in `backend/tests/policy/test_confirm_flow.py`, including that a losing claimant receives `already_resolved` naming the prior outcome rather than a generic failure
- [ ] T005 Add `before_model` and `abefore_model` to `PolicyMiddleware` in `backend/app/policy/middleware.py`, reading the latest human turn from state and delegating to `confirm_flow`; return the outcome as a message so the assistant narrates it
- [ ] T006 Verify the round trip in `backend/tests/policy/test_before_model_confirmation.py` against a real `create_agent` run using the `ToolCapableFake` pattern from `tests/policy/test_suspend_resume_control.py`
- [ ] T007 Include the POSITIVE CONTROL in T006 as its own test: assert `before_model` is invoked at all. Without it, "the confirmation did not complete" is indistinguishable from "the hook never ran" — the plan's probe hit exactly this
- [ ] T008 Assert in T006 that a phrase outside the closed set (`"maybe later"`) leaves the action open and returns `unrecognised`, so the test cannot pass by accepting everything

### The scope threshold — both routes, not just the UI (FR-009)

- [ ] T009 Add `threshold_targets` to the policy rule set with default **10**, labelled in the config comment as a stated guess with no production distribution behind it — the confirmation path has never run, so there is no distribution of target counts to set it from (Article X)
- [ ] T010 Implement the threshold inside `confirm_flow` so it applies to EVERY route: above it, a confirmation must supply a value matching the resolved target count; a wrong or absent value returns `threshold_not_met` and **does not consume, claim or resolve the action**
- [ ] T011 [P] Test in `backend/tests/policy/test_scope_threshold.py` that below-threshold confirms with a bare affirmation, above-threshold rejects one, a correct count confirms, and a wrong count leaves the action open and unclaimed
- [ ] T012 [P] Test that the threshold is read from configuration and that changing it changes which actions demand a count (SC-019)
- [ ] T013 Test that the CHAT route enforces the threshold identically to the future UI route. This is the whole point of the move: FR-009 previously sat under the Surface 1 heading, which scoped it to the UI by placement, and would have shipped Phase 1 as a route where `yes` grants sixty targets

### Closed-set coverage (addition)

- [ ] T014 Enumerate what `_CONFIRM_FORMS` and `_DECLINE_FORMS` actually accept after normalisation, and write the enumeration to `specs/004-assistant-ui-surfaces/closed-set-coverage.md` (FR-037) as a table of phrase → accepted/rejected. Include the natural affirmations a real user types: `yes`, `yes please`, `yes, do it`, `do it`, `go ahead`, `sure`, `ok`, `okay`, `confirm`, `yep`, `please do`, and the decline equivalents
- [ ] T015 Judge each rejected-but-natural phrase in that table and record a verdict per entry (FR-037). The set MUST remain closed and matched exactly — interpretation was rejected as a security property and that is not reopened. Closed is not the same as narrow: a set that rejects `"yes, do it"` trains users to fight the gate, which is the failure deterministic decline exists to prevent
- [ ] T016 Extend `_CONFIRM_FORMS` / `_DECLINE_FORMS` in `backend/app/policy/confirm.py` with the phrases T010 approves, each carrying an inline justification. Additions are a deliberate edit, one line of reasoning per entry
- [ ] T017 [P] Test in `backend/tests/policy/test_confirm_forms.py` that every phrase T009 lists as accepted is accepted and every phrase listed as rejected is rejected, driven by the same table so the document and the code cannot drift (SC-020)
- [ ] T018 Assert in the same file that normalisation cannot be bypassed: punctuation, case and surrounding whitespace do not change a verdict, and no phrase containing an additional instruction (`"yes and also delete the rest"`) is accepted

### Closing Feature 003's FR-019

- [ ] T019 Expire LAZILY ON READ: have `open_actions` and `confirm_flow` resolve any action past its expiry as they encounter it, so `expire_due`'s effect happens without a background task (FR-038)
- [ ] T020 NO LIFESPAN HOOK, and the reason is recorded at the call site: the gateway's only periodic work is the trigger engine's task, behind `config.trigger_engine.enabled`, which defaults to false. Hanging expiry off it would make FR-038 silently inert whenever that flag is off — reintroducing the built-but-never-runs family that this phase exists to close
- [ ] T021 [P] Test in `backend/tests/policy/test_expiry_is_announced.py` that an action passing its expiry is resolved EXPIRED on the next read and produces a user-visible statement, not silence (SC-021)
- [ ] T022 [P] Test that lazy expiry is idempotent and safe under concurrent readers: two workers reading the same expired action must not both announce it

### Gate — one recognition-and-claim implementation

- [ ] T023 Write `backend/tests/gates/test_single_confirmation_path.py` asserting exactly one call site of `claim(` exists in production code, and that it is inside `confirm_flow.py`. This is FR-004 made checkable: a second route reimplementing the claim is what allows one confirmation to execute twice
- [ ] T024 SABOTAGE T023: add a second module that calls `claim` directly and confirm the gate fails **at the assertion**, naming the offending file. Confirm the run reports `failed` — a `skipped`, `error` or collection failure has exercised nothing, and grepping the output for `pass|fail` hides all three

### Production shape

- [ ] T025 Extend `backend/tests/policy_multiworker/` so a confirmation arriving through chat on one worker resolves an action created on another, at the worker count read from the compose file
- [ ] T026 Verify Phase 1 is standalone: run the full backend suite with no frontend build and no Phase 2+ work present, and confirm Tier 3 is usable end to end
- [ ] T027 Manual validation per quickstart.md: ask the assistant for a Tier 3 action, reply `yes`, observe it happen. Record the before/after, since on main nothing happens

**Checkpoint**: Tier 3 is grantable in chat. Releasable on its own.

---

## Phase 2: Trigger recording (no UI) 🚨 BLOCKING for US2

**Purpose**: Record what Surface 3 must read. A view over unrecorded data is a blank
column, so this precedes any trigger UI.

- [ ] T028 Add `last_evaluated_at` per rule in `backend/app/trigger_engine/`, updated whenever a rule is evaluated regardless of whether it fires (FR-020)
- [ ] T029 [P] Test in `backend/tests/trigger_engine/test_evaluation_record.py` that a rule evaluated repeatedly without firing is distinguishable from one never evaluated — the distinction the calendar lead-time bug fell into (SC-009)
- [ ] T030 Add `batch_id` to `Firing` in `backend/app/trigger_engine/models.py`, set at release for every firing delivered in one coalesced message (FR-021)
- [ ] T031 Write the batch id through `backend/app/trigger_engine/audit.py` and `politeness/release.py` so each survivor's audit entry carries it
- [ ] T032 [P] Test in `backend/tests/trigger_engine/test_batch_identity.py` that coalesced firings share a batch id and that **each is still recorded DELIVERED**. Coalescing is not an outcome; a firing that was merged was delivered, and recording otherwise would put a false statement in the audit log
- [ ] T033 [P] Test that a single uncoalesced delivery has no batch id, so the field's presence means something
- [ ] T034 Ensure audit rows written before T028 and T030 read back as "not recorded" rather than as a recorded absence (FR-022), tested against a fixture of pre-existing rows
- [ ] T035 Run mypy over the changed trigger modules and keep them clean under the strict override

**Checkpoint**: The trigger record can answer "why did nothing arrive". Still no UI.

---

## Phase 3: User Story 1 — Pending confirmations (Priority: P1) 🎯 MVP

**Goal**: Confirm or decline a Tier 3 action from a control instead of typing a phrase.

**Independent Test**: Create a Tier 3 pending action, open the surface, press Confirm,
observe it execute exactly once with the claiming worker named in the audit entry.

### Backend

- [ ] T036 [US1] Create `backend/app/gateway/routers/confirmations.py` with `GET /api/confirmations`, `POST /api/confirmations/{id}/confirm`, `POST /api/confirmations/{id}/decline`, all delegating to `confirm_flow`
- [ ] T037 [US1] Register the router in `backend/app/gateway/app.py`
- [ ] T038 [US1] Return distinct outcomes from the endpoints — `already_resolved` naming the prior outcome, `expired`, `targets_drifted` carrying both target lists, `threshold_not_met` — never collapsed into a generic failure (FR-007)
- [ ] T039 [P] [US1] Test that `GET /api/confirmations` distinguishes "no actions pending" from "the pending set could not be read" (FR-008)

### Frontend

- [ ] T040 [P] [US1] Create `frontend/src/core/confirmations/hooks.ts` using `@tanstack/react-query` v5, matching the existing per-domain hook convention
- [ ] T041 [US1] Create the route at `frontend/src/app/workspace/confirmations/page.tsx`
- [ ] T042 [US1] Build the pending action card in `frontend/src/components/workspace/confirmations/`, showing what was requested, the plan exactly as stated, the resolved targets, the requesting agent with its delegation chain, and time remaining (FR-002)
- [ ] T043 [US1] Implement the confirm and decline controls, with decline as prominent and as deterministic as confirm (FR-003)
- [ ] T044 [US1] Implement the typed-count control shown only above threshold, stating the count is required because the action affects more than the configured number of targets
- [ ] T045 [US1] Implement client-side expiry: an action expiring while displayed becomes visibly expired without a reload and its controls become inoperable rather than remaining pressable (FR-005)
- [ ] T046 [US1] Surface drifted targets clearly, stating that the targets changed rather than reporting a generic failure (FR-006)
- [ ] T047 [P] [US1] Unit-test the countdown and threshold logic in `frontend/tests/unit/confirmations.test.ts`

### Rendering and cross-worker

- [ ] T048 [US1] Rendering assertions in `frontend/tests/rendering/confirmations.spec.ts`: an above-threshold action cannot be confirmed by clicking; a wrong typed count neither confirms nor resolves; an expired action's controls are inoperable. CI only
- [ ] T049 [US1] Extend `backend/tests/policy_multiworker/` so an action created on one worker is confirmed through the HTTP route on another, and the audit entry names the claiming worker (SC-001, SC-005)
- [ ] T050 [US1] Test simultaneous confirmation through the UI route and the chat path, asserting exactly one execution (SC-002). This is now meaningful because Phase 1 exists

**Checkpoint**: The feature's reason for existing is operable.

---

## Phase 4: User Story 2 — Trigger activity (Priority: P2)

**Goal**: Find out why a trigger produced nothing.

**Independent Test**: Load a rule that cannot fire, let the engine run, confirm the
surface shows it evaluating and never firing — visibly different from never evaluated.

- [ ] T051 [US2] Create `backend/app/gateway/routers/triggers.py` with `GET /api/triggers/rules` and `GET /api/triggers/firings`, and register it
- [ ] T052 [P] [US2] Pass outcome reasons through verbatim rather than summarising them into a status word (FR-019), tested
- [ ] T053 [P] [US2] Resolve batch siblings at read time so a coalesced firing can name what it was delivered with
- [ ] T054 [P] [US2] Create `frontend/src/core/triggers/hooks.ts`
- [ ] T055 [US2] Create the route at `frontend/src/app/workspace/triggers/page.tsx` with two panels: loaded rules, and a chronological firing log
- [ ] T056 [US2] Render rules with id, type, enabled, last evaluated and last fired, with never-evaluated, evaluated-never-fired and fired-recently all visually distinct (FR-017)
- [ ] T057 [US2] Render `null` timestamps as "not recorded", distinct from "never" (FR-022)
- [ ] T058 [US2] Render a coalesced firing alongside the others in its batch, so "what it was merged with" is visible rather than only resolvable server-side — the second half of FR-021, which T053 alone does not deliver
- [ ] T059 [US2] Render each outcome distinguishably — delivered, suppressed, queued, expired, failed — with its reason shown
- [ ] T060 [P] [US2] Rendering assertions in `frontend/tests/rendering/triggers.spec.ts`: a quiet-hours suppression is distinguishable from a delivery and from a rule that never evaluated (SC-008), and firings coalesced into one message each name the others they were delivered with (SC-010)

**Checkpoint**: A silently-broken rule is findable.

---

## Phase 5: User Story 3 — Coding sessions (Priority: P3)

**Goal**: See what the coding sessions are doing, and whether we can see them at all.

**Independent Test**: Start sessions in two projects and confirm each appears with the
right state; stop the watcher and confirm the surface says sessions cannot be seen.

- [ ] T061 [US3] Create `backend/app/gateway/routers/sessions.py` reaching the watcher's SSE server per research R2, returning `{reachable, observability, staleness_seconds, sessions[]}`
- [ ] T062 [US3] Keep `reachable` separate from `observability`. Unreachable is a transport fact; live, stale and never-observed arrive inside the watcher's envelope. Collapsing them would undo Feature 001's FR-011a, which exists to keep three conditions from becoming two
- [ ] T063 [P] [US3] Test all four conditions in `backend/tests/gateway/test_sessions_router.py`, including watcher unreachable, with a stopped server rather than a mocked exception
- [ ] T064 [P] [US3] Create `frontend/src/core/sessions/hooks.ts`
- [ ] T065 [US3] Create the route at `frontend/src/app/workspace/sessions/page.tsx`
- [ ] T066 [US3] Render watcher health first-class — live, stale with its age, unreachable — never inferable only from an empty list (FR-013)
- [ ] T067 [US3] Render inferred states visually distinct from observed ones, and keep completed distinct from stalled (FR-011, FR-012)
- [ ] T068 [US3] Label observe-only sessions, so the absence of controls reads as a property rather than a missing feature (FR-015)
- [ ] T069 [P] [US3] Rendering assertions in `frontend/tests/rendering/sessions.spec.ts`: with the watcher stopped the page states sessions cannot be seen and renders no empty list (SC-006); a waiting session differs from a finished one without reading the text (SC-007)

**Checkpoint**: The watcher is visible, and so is its absence.

---

## Phase 6: User Story 4 — Policy inspector, plus cross-cutting

**Goal**: Learn a tool's tier without triggering it, and close the gate gaps this
feature exposed.

- [ ] T070 [US4] Create `backend/app/gateway/routers/policy.py` with `GET /api/policy/rules`, `GET /api/policy/explain`, `GET /api/policy/audit`, and register it
- [ ] T071 [P] [US4] Test that `explain` does not execute the tool it is asked about and uses the same `classify()` as live dispatch (SC-011)
- [ ] T072 [P] [US4] Return `from_default` so unclassified-defaults-to-Tier-3 is distinguishable from explicitly-classified-as-Tier-3 (FR-027, SC-012)
- [ ] T073 [US4] Serve the rules actually in force, including after a failed reload left previous rules active (FR-029), tested by forcing a bad reload
- [ ] T074 [P] [US4] Create `frontend/src/core/policy/hooks.ts` and the route at `frontend/src/app/workspace/policy/page.tsx`
- [ ] T075 [US4] Render the loaded rules, the tier check with its deciding rule, the default marker, and recent Tier 3 executions with actor, plan as stated and authorising confirmation
- [ ] T076 [P] [US4] Rendering assertions in `frontend/tests/rendering/policy.spec.ts`

### Gate sweep (addition) — report before changing

- [ ] T077 Audit EVERY existing gate for hardcoded scope and write the finding to `specs/004-assistant-ui-surfaces/gate-scope-audit.md` BEFORE changing any of them (FR-039). Cover at least `tests/trigger_engine/test_wiring.py`, `tests/test_module_wiring.py`, `tests/policy/test_gate_single_dispatch.py`, `tests/policy/test_gate_raise_only.py`, `tests/policy/test_gate_structural.py`, `tests/workers/test_gate_tool_surface.py`, `tests/test_shipped_paths.py`, `tests/test_harness_boundary.py`. For each: is it general, or scoped to the module that motivated it?
- [ ] T078 For each one-off found in T077, record what the next instance would look like and whether that instance is plausible. A gate scoped to its motivating module will miss the next occurrence exactly as Gate 4 missed `recognise` — but a gate whose subject genuinely is one module is not a defect, and the report must separate those two cases rather than counting all narrow scopes as bugs
- [ ] T079 Generalise `tests/trigger_engine/test_wiring.py` into `backend/tests/gates/test_wiring.py` covering every feature module, with: framework-invoked hooks exempt (`wrap_tool_call`, `awrap_tool_call`, `before_model`, `abefore_model`, `after_model`), references scanned across `app/` and `packages/`, and **both the alias and the original name recorded for `import ... as`** — the last is a real bug in the current gate, which reads `install` as unreferenced because the gateway imports it as `install_policy`
- [ ] T080 Generalise any other one-off T078 judges worth generalising; leave the rest with a comment stating why their scope is correct
- [ ] T081 SABOTAGE T079: add a function that nothing calls and confirm the gate names it. Then confirm the gate on today's tree is green **only** because of its whitelist, not because it finds nothing — a gate that cannot fail is the thing this feature exists to prevent (SC-022)
- [ ] T082 Populate the new gate's whitelist with a mandatory reason per entry, and assert reasons are non-empty. Read APIs consumed by this feature must NOT be whitelisted — they have real consumers by Phase 6

### Cross-cutting

- [ ] T083 [P] Write `backend/tests/gates/test_read_surfaces_do_not_write.py` asserting the sessions, triggers and policy routers contain no write call (FR-030, SC-014). This also discharges FR-036 — a rule editor would have to write through one of these routers
- [ ] T084 SABOTAGE T083: add a write to a read router and confirm the gate fails at the assertion naming the file
- [ ] T085 Promote the six accessibility rules from warn to error in `frontend/eslint.config.mjs` (FR-034)
- [ ] T086 SABOTAGE T085: introduce a deliberate a11y violation and confirm the build fails on it (SC-017), then remove it
- [ ] T087 [P] Extend `frontend/tests/rendering/theme.spec.ts` to assert the computed background changes on every one of the four new surfaces (SC-013)
- [ ] T088 [P] Assert no new surface hardcodes a colour utility, extending the existing token check to the four new component directories (FR-033)
- [ ] T089 SABOTAGE T088: add a hardcoded colour utility to one of the four new component directories and confirm the check fails naming the file. Confirm the run reports `failed` — `skipped`, `error` or a collection failure has exercised nothing
- [ ] T090 Confirm `backend/tests/test_shipped_paths.py` covers this feature's tests, including the frontend `join(__dirname, "..")` idiom, and that no test added here reads a gitignored path (FR-032, SC-016)
- [ ] T091 [P] Route all rendered session summaries, page content and email bodies through the existing redactor, suppressing display on failure rather than falling through (FR-031, SC-015)
- [ ] T092 SABOTAGE T091: feed content that fails redaction and confirm the surface suppresses rather than renders, and that the suppression is visible as such rather than as absent data
- [ ] T093 Run quickstart.md end to end and record which steps ran locally and which only in CI
- [ ] T094 Update `specs/ROADMAP-FOLLOWUPS.md` with what this feature deliberately did not do: no rule editor, mobile out of scope, the browser worker still open, and any gate T078 judged not worth generalising

---

## Dependencies & Execution Order

### Phase dependencies

- **Phase 1 (T001–T027)** — no dependencies. **Releasable alone.** Nothing in it may depend on Phase 2+
- **Phase 2** — independent of Phase 1; may run in parallel by a second person
- **Phase 3 (US1)** — requires Phase 1. Cannot start before it
- **Phase 4 (US2)** — requires Phase 2. Cannot start before it
- **Phase 5 (US3)** — requires neither Phase 1 nor Phase 2
- **Phase 6 (US4)** — the inspector requires neither; the gate sweep is best last, when the gates have this feature's code to look at

### Critical rule

**Phases 1 and 2 ship no UI, and their checkpoints are not surface deliveries.** Reading
either as "a slice that includes a view" would produce a blank column or a control that
cannot act.

### Parallel opportunities

- Phase 1 and Phase 2 are fully independent of each other
- Phase 5 (US3) can begin at any time
- Within phases, all [P] tasks touch different files
- T037/T051/T060/T070 (frontend hooks) are parallel across stories

## Implementation Strategy

### MVP

Phase 1 → Phase 3. Tier 3 becomes grantable, then operable from a control.

### Release boundaries

1. **Phase 1 alone** — Tier 3 usable in chat. A genuine release with no UI
2. **+ Phase 3** — the control
3. **+ Phase 2, 4** — trigger visibility
4. **+ Phase 5, 6** — the remaining read surfaces and the gates

## Notes

- Every gate task is followed by its sabotage, and each sabotage must be confirmed to
  fail **at the gate**. A run reporting `skipped`, `error` or a collection failure has
  exercised nothing, and grepping output for `pass|fail` hides all three
- Rendering assertions run in CI only; the local browser bundle stalls at 448 KB against
  369 MB in CI — measured
- No `__init__.py` in test directories
