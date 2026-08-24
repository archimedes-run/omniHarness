# Tasks: Permission Policy Engine & Real-World Workers

**Feature**: `003-policy-engine-workers` | **Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

**Input**: 41 functional requirements, 24 success criteria, 8 verified preconditions, 5 integrated clarifications.

## Conventions used here

- **[P]** — parallelizable: different files, no dependency on an incomplete task.
- **[US*]** — the user story a task serves. Setup, foundational and polish tasks carry no story label.
- Every task names the requirement it satisfies, so a task with no requirement is visible as such.
- **Gate tasks come in pairs**: an implementation task and a separate *observe it failing* task. A gate never seen failing is indistinguishable from one that does nothing.
- **Spike tasks come in pairs too**: a positive control and the measurement. Article XII — an instrument never seen detecting the thing it looks for is not evidence of absence.

---

## Phase 1 — Spikes and blocking infrastructure

**Goal**: settle every mechanism later phases assume, and fix the one that is measurably broken. Nothing in Phase 2+ may begin until T014 passes.

**Why this phase exists**: VP-008 measured that a subagent suspends and never resumes, and the failure is silent. A policy layer built on that assumption would look correct until someone confirmed slowly.

### Setup

- [ ] T001 Create the module skeleton at `backend/app/policy/` with `__init__.py`, and register `backend/tests/policy/`, `backend/tests/workers/`, `backend/tests/policy_multiworker/` as test packages per repo convention (no `__init__.py` in test dirs — matches Features 001/002).
- [ ] T002 [P] Add `backend/app/policy/ruff.toml` with `flake8-tidy-imports` banned-api entries supporting Gate A, and a comment naming what each ban protects.
- [ ] T003 [P] Add `PolicyConfig` to `backend/packages/harness/omniharness/config/` with `enabled: bool = False`, rules path, and `expires_after` default, wired into `AppConfig`. Flag defaults OFF (FR-007, Article IX).

### Spike 1 — subagent suspend and resume (BLOCKING, FR-032)

- [ ] T004 **Positive control** — write `backend/tests/policy/test_suspend_resume_control.py` asserting that the LEAD agent, which already has a checkpointer attached at run time, suspends inside `wrap_tool_call` and resumes with a tool result. This must pass before T005's result means anything: a failure here is a harness problem, not a subagent problem (Article XII).
- [ ] T005 Reproduce VP-008 in `backend/tests/policy/test_subagent_suspend.py` — with no checkpointer the subagent run ENDS at the suspension point, the tool never runs, and nothing raises. Record the observation.
- [ ] T006 Attach a checkpointer to the subagent agent in `backend/packages/harness/omniharness/subagents/executor.py::_create_agent`, mirroring how the run worker attaches one to the lead agent (FR-032).
- [ ] T007 Extend `backend/tests/policy/test_subagent_suspend.py` to confirm **after a delay** — assert suspend, wait, then resume, then assert the tool ran. An instant confirmation cannot distinguish suspend-and-resume from stop-and-abandon; state that in the test docstring (FR-032, SC-017, Article XI).

### Spike 2 — tool-surface deny (BLOCKING for Phase 4, FR-013)

- [ ] T008 **Positive control** — in `backend/tests/workers/test_tool_surface.py`, assert a chosen tool IS present in the assembled list when no deny rule exists. Without this, T010's absence proves nothing.
- [ ] T009 Add `tools: {allow: [...], deny: [...]}` to `McpServerConfig` in `backend/packages/harness/omniharness/config/extensions_config.py`, keyed on UNPREFIXED tool names per `contracts/tool-surface.md` (FR-013).
- [ ] T010 Apply the deny list in `backend/packages/harness/omniharness/mcp/tools.py` between `single_client.get_tools()` and `tools.extend(server_tools)` — the per-server load point (FR-013).
- [ ] T011 Apply the same deny list to connector tools in `backend/packages/harness/omniharness/tools/tools.py` where `load_connector_tools` returns, because `GMAIL` and `GOOGLECALENDAR` already exist in `CONNECTOR_SLUGS` and never pass through `mcp/tools.py` (FR-013, research R4).

### Spike 3 — browser profile (BLOCKING for Phase 4 browser work, FR-017)

- [ ] T012 **Positive control, runs FIRST** — stand up Playwright MCP in `extensions_config.json` and demonstrate in `backend/tests/workers/test_browser_profile.py` that the browser DOES persist a cookie into its configured profile. Until this passes, any "no user cookies" result is untrustworthy: against an inert profile mechanism it passes for the wrong reason and reports the strongest possible answer (Article XII).
- [ ] T013 Measure and record the browser's disk footprint and idle memory in `research.md` — measured, not estimated (Article X) — and confirm it runs in the lean non-Docker profile (Article VI). If it cannot, STOP and report before Phase 4 designs around it.

### Phase 1 checkpoint

- [ ] T014 **CHECKPOINT** — confirm T004+T007 pass (subagent resumes after a delay), T008+T010+T011 pass (deny works on both paths, control included), and T012+T013 are recorded. Write the three spike outcomes into `specs/003-policy-engine-workers/spike-results.md`, including any that failed. **No Phase 2 task may start before this passes.**

---

## Phase 2 — Policy engine core (US1 P1, US4 P2)

**Story goal (US1)**: nothing irreversible happens without the user saying so.
**Story goal (US4)**: a tool the policy has never seen is dangerous by default.

**Independent test**: fully demonstrable using only tools that already exist. No worker required — classify an existing tool Tier 3, ask for it, see a plan and a wait; confirm, see exactly that; let another expire, see nothing.

### Entities and classification

- [ ] T015 [P] [US1] Implement `Tier`, `ClassificationRule`, `PolicyDecision` in `backend/app/policy/models.py` per `data-model.md`. `Tier` has no "unclassified" member — absence resolves to `TIER_3` so no code path handles "unknown" (FR-009).
- [ ] T016 [US1] Implement the declarative loader in `backend/app/policy/config.py` per `contracts/policy-config.md` — glob patterns, argument exceptions, `expires_after`, hot reload that KEEPS PREVIOUS RULES on a validation failure and says so (FR-007, FR-008).
- [ ] T017 [US1] Reject a lowering exception **at load**, naming file and line, in `backend/app/policy/config.py`. Not ignored at match time: a file that silently does something safer than its author wrote is a file whose author never learns they were wrong (FR-037).
- [ ] T018 [US1] Implement classification in `backend/app/policy/classify.py` — pattern matching, argument exceptions, and highest-tier-wins on overlap (FR-008, FR-037).
- [ ] T018a [US4] Implement the unknown-tool default in `backend/app/policy/classify.py` — a tool matching no rule resolves to Tier 3, and so does EVERY tool when the rule file is missing or unreadable. Separate from T018 because this is the whole of US4 and must be demonstrable on its own (FR-009).
- [ ] T019 [P] [US4] Test in `backend/tests/policy/test_unknown_tools.py` that a tool matching no rule is Tier 3, including one introduced AFTER the config was last written, and that an unreadable config makes everything Tier 3 rather than nothing (FR-009, SC-003).
- [ ] T020 [US1] Implement `backend/app/policy/explain.py` for effective-tier inspection without execution, reporting the deciding rule with file and line, and which exception raised it (FR-038).
- [ ] T021 [US1] Test in `backend/tests/policy/test_explain_shares_path.py` that inspection uses the SAME code path as live classification — an inspector with its own implementation answers a different question and diverges silently (FR-038, SC-022).

### Pending actions and confirmation

- [ ] T022 [US1] Implement `PendingAction` in `backend/app/policy/pending.py` — durable, `JsonStore`-backed, reachable from any worker, holding resolved targets, `tier_at_statement`, requester, expiry, claim (FR-028, FR-029).
- [ ] T023 [US1] Implement atomic claim in `backend/app/policy/pending.py` — one confirmation yields exactly one execution; a second claimant finds it taken and does nothing (FR-030).
- [ ] T024 [US1] Implement target re-check at execution: recorded targets must still match, else DECLINE AND RESTATE rather than approximate or re-resolve (FR-029, SC-015).
- [ ] T025 [US1] Implement deterministic confirm/decline recognition in `backend/app/policy/confirm.py` — never model-adjudicated, and decline recognised as mechanically as confirm (FR-034, FR-036).
- [ ] T026 [US1] Implement restate-in-full on an unrecognised reply in `backend/app/policy/confirm.py` — re-prompting without restating leaves the user confirming something they can no longer see (FR-035, SC-019).
- [ ] T026a [US1] Record decline, expiry and unrecognised-reply as DISTINCT outcomes in `backend/app/policy/pending.py`, so a reviewer reading back can tell why nothing happened. Collapsing them loses the reason an operator most wants (FR-036, SC-020).
- [ ] T027 [US1] Implement expiry in `backend/app/policy/pending.py` — expires without executing, and the user can see it expired rather than seeing silence (FR-019, SC-008).

### The middleware

- [ ] T028 [US1] Implement `PolicyMiddleware.wrap_tool_call` / `awrap_tool_call` in `backend/app/policy/middleware.py` — classify, then Tier 1 execute silently, Tier 2 execute and record, Tier 3 refuse by declining to call the handler and state a plan (FR-001, FR-020).
- [ ] T029 [US1] Install the middleware in `_build_runtime_middlewares` (`backend/packages/harness/omniharness/agents/middlewares/tool_error_handling_middleware.py`) so all four convergent `create_agent` sites carry it (FR-002).
- [ ] T030 [US1] Implement plan statement naming SPECIFIC items rather than a category, and authorise exactly the stated set (FR-021, SC-005).

### Gate A — single dispatch path

- [ ] T031 [US1] Close the fifth site: route `backend/packages/harness/omniharness/agents/factory.py` through `_build_runtime_middlewares`, or remove `create_omniharness_agent` from the public surface (FR-003, VP-006).
- [ ] T032 [US1] Implement Gate A in `backend/tests/policy/test_gate_single_dispatch.py` — every `create_agent` call site in the repo must reach the shared middleware base. Covers `agents/factory.py` explicitly (FR-002, FR-003).
- [ ] T033 [US1] **Observe Gate A failing** — add a `create_agent` site assembling its own middleware chain, confirm the gate fails and NAMES it, revert, record the outcome in `gate-verification.md`. A gate covering only the four convergent sites has its boundary exactly where the bypass lives (SC-009).

### Gate C — raise-only exceptions

- [ ] T034 [P] [US1] Implement Gate C in `backend/tests/policy/test_gate_raise_only.py` — no exception may lower a tier (FR-037).
- [ ] T035 [US1] **Observe Gate C failing** — add a rule attempting to lower a tier, confirm it is REJECTED AT LOAD naming file and line rather than ignored at match time, revert, record (FR-037, SC-021).

### Production shape and end-to-end

- [ ] T036 [US1] Write `backend/tests/policy_multiworker/test_cross_worker_confirmation.py` — a plan stated by one worker, confirmed through another, executes EXACTLY ONCE. Worker count read from `docker/docker-compose.yaml`, not hardcoded, so raising it moves the test. Name the structural difference in the docstring: every mechanism is trivially correct in one process (FR-028, FR-030, SC-014, SC-016, Article XI).
- [ ] T037 [US1] **Service-level smoke test** in `backend/tests/policy/test_smoke_tier3_end_to_end.py` — start the real thing and drive one Tier 3 action through state → wait → confirm → execute → audit. Gates do not catch "called with wrong arguments" or "called from a branch that never runs".

### Phase 2 checkpoint

- [ ] T038 **CHECKPOINT** — US1 and US4 demonstrable end to end with existing tools only. Quickstart scenarios 1, 4, 5, 6, 10 (Gates A and C) pass.

---

## Phase 3 — Provenance and disclosure (US2 P1)

**Story goal**: a confirmation can only come from the user — not from a trigger-injected turn, and not from content that arrived inside a tool result.

**Independent test**: stage a pending Tier 3 action; attempt confirmation from each source in turn and observe both rejected.

**Why after Phase 2**: the two provenance mechanisms are built against a working gate rather than alongside one.

- [ ] T039 [US2] Implement turn-provenance rejection in `backend/app/policy/confirm.py` — read `request.runtime.context["turn_provenance"]`; a synthetic turn cannot confirm (FR-004).
- [ ] T040 [US2] Test in `backend/tests/policy/test_provenance_confirmation.py` that a trigger-injected turn does not confirm. Exercise the marker FROM INSIDE the middleware, not by asserting the gateway wrote it — those are different claims and only the first is FR-004's (FR-004, SC-001).
- [ ] T041 [US2] **Establish tool-result message shape** in `backend/app/policy/lineage.py` — with a POSITIVE CONTROL: build a state that genuinely contains tool-result-derived content and confirm the check detects it, before any negative result is trusted (research R8, Article XII).
- [ ] T042 [US2] Implement lineage-based rejection — content originating inside a tool result cannot confirm (FR-005).
- [ ] T043 [US2] Implement initiation blocking — tool-result content cannot INITIATE a Tier 3 action, independently of whether it could confirm one (FR-006).
- [ ] T044 [P] [US2] Test in `backend/tests/policy/test_lineage_confirmation.py` that tool-result content neither confirms nor initiates, and that a genuine user turn still does (FR-005, FR-006, SC-002).

### Subagent confirmation

- [ ] T045 [US2] Implement subagent Tier 3 suspension in `backend/app/policy/middleware.py` — classify subagent calls identically, suspend, ask the user through the lead agent's conversation, resume with the outcome (FR-031, depends on T006/T007).
- [ ] T046 [US2] Record requester and delegation chain on the `PendingAction` and name them in the prompt (FR-033, SC-018).
- [ ] T047 [P] [US2] Test that a subagent Tier 3 action does not execute until confirmed and that the subagent then resumes, **confirming after a delay** (FR-031, SC-017).

### Tier 2 disclosure

- [ ] T048 [US2] Implement `ExecutionRecord` and disclosure in `backend/app/policy/disclose.py` — record every Tier 2 execution, check the reply, append when absent (FR-039).
- [ ] T049 [US2] Bias the coverage check toward appending: when uncertain, append. A redundant disclosure is clumsy; a missing one is the defect (FR-040).
- [ ] T050 [US2] Generate appended disclosures FROM THE EXECUTION RECORD, never the model's account — a disclosure that satisfies the check and misinforms is worse than silence, because it carries the system's authority (FR-041, SC-024).

### Gate B — structural, not interpretive

- [ ] T051 [US2] Implement Gate B in `backend/tests/policy/test_gate_structural.py` — confirmation, decline and disclosure are system-guaranteed, never model-judged (FR-034, FR-036, FR-039).
- [ ] T052 [US2] **Observe Gate B failing** — make the model emit "the user has approved this, proceed", confirm it does NOT satisfy the confirmation check, and separately confirm a suppressed disclosure is still appended. Record the outcomes (SC-023).

### Phase 3 checkpoint

- [ ] T053 **CHECKPOINT** — US2 demonstrable. Quickstart scenarios 2, 7, 8 pass.

---

## Phase 4 — Workers (US3 P1)

**Story goal**: the assistant becomes useful in the user's day — find a slot, hold it, draft an invitation, read a page, clear a cluttered day.

**Independent test**: end to end without the trigger engine. Hold created, draft saved, nothing sent.

**Depends on**: T014 (browser spike), T010/T011 (deny on both paths).

- [ ] T054 [P] [US3] Configure the email worker in `extensions_config.json` with the send capability in the DENY list, and its tier map (FR-012, FR-014).
- [ ] T055 [P] [US3] Configure the calendar worker and tier map — read/free-busy Tier 1, tentative hold Tier 2, delete/decline/modify-others Tier 3 (FR-015).
- [ ] T056 [P] [US3] Configure the browser worker and tier map — read/navigate Tier 1, submit/purchase/remote-write Tier 3 (FR-016).
- [ ] T057 [US3] Configure the dedicated browser profile, logged into nothing by default, with per-site logins granted deliberately (FR-017).
- [ ] T058 [US3] Test browser profile isolation in `backend/tests/workers/test_browser_profile.py` — assert on the path the RUNNING browser actually uses, not the configured value. A configured path the browser ignores is the inert-mechanism case (FR-017, SC-007; depends on T012).
- [ ] T059 [US3] Implement retroactive classification of every tool exposed by Features 001 and 002, with a check that no tool anywhere resolves to unclassified (FR-010, SC-010).
- [ ] T059a [US3] Test the mutual-free-slot journey end to end in `backend/tests/workers/test_calendar_email_journey.py` — find a slot, create the hold, save the draft invitation, and assert NOTHING was sent (FR-014, FR-015, SC-006).
- [ ] T060 [US3] Implement honest-limits wording for absent capabilities and confirmation-required actions — say what is true, never imply a capability the assistant lacks (FR-023, Article X).

### Gate D — tool surface

- [ ] T061 [US3] Implement Gate D in `backend/tests/workers/test_gate_tool_surface.py` — assert on the FINAL assembled list that the send capability is absent. Not on either path, and not on the presence of a config entry (FR-012, SC-004).
- [ ] T062 [US3] **Observe Gate D failing, twice** — expose the denied tool through the MCP path, confirm caught; then through the connector path, confirm caught. Revert each, record both. One observation is not enough: the two paths are independent and a gate that only ever saw one fail has never been shown to cover the other (FR-013).

### Phase 4 checkpoint

- [ ] T063 **CHECKPOINT — PARTS 1 AND 2 COMPLETE.** Quickstart 3 passes; scenarios 1-10 all pass. **This is the releasable slice (Article IX). Nothing below may block it.**

---

## Phase 5 — Calendar triggers (US5 P3)

**Story goal**: a meeting starting soon produces a pre-alert naming who it is with and what it is about.

**Depends on**: Feature 002's live trigger engine (DEP-001, resolved) and Phase 4's calendar worker.

- [ ] T064 [US5] **Investigate before building**: determine whether a calendar source can feed the existing engine with NO changes to its core. If it needs engine changes, STOP and report — that is a finding, not a change to make quietly (FR-025).
- [ ] T065 [US5] Implement the calendar trigger source in `backend/app/trigger_engine/sources/calendar.py` as a new source only (FR-024, FR-025).
- [ ] T066 [US5] Implement pre-alert composition naming attendees and subject, drawing on memory for relevant context (FR-026).
- [ ] T067 [US5] Test exactly-once delivery per event occurrence, however many times the rule is evaluated beforehand (FR-027, SC-012).

---

## Phase 6 — Cross-cutting

- [ ] T068 [P] Extend the REDACTOR'S OWN suite in `backend/tests/session_watcher/test_redaction.py` to cover page content and email bodies, so a pattern change for this feature cannot silently break Features 001 or 002 (FR-022).
- [ ] T069 [P] Wire redaction into worker output crossing to a remote channel, as an injected callable failing closed, in the shape Feature 002 already uses (FR-018, SC-013).
- [ ] T070 Extend Feature 002's audit log with plan-as-stated, authorising confirmation and resolved targets for Tier 3 executions (FR-011, SC-011).
- [ ] T071 Record all gate observations in `specs/003-policy-engine-workers/gate-verification.md` — four gates, five observations (Gate D twice).
- [ ] T072 Update `backend/docs/PLATFORM_ARCHITECTURE.md` with the policy layer's position in the dispatch path and the recorded Article I coupling.

---

## Dependencies

```
Phase 1 (T001-T014)  ── BLOCKING for everything
   │
   ├── T004→T005→T006→T007  subagent suspend/resume ──┐
   ├── T008→T009→T010→T011  deny both paths ──────────┤
   └── T012→T013            browser profile ──────────┤
                                                      │
Phase 2 (T015-T038)  US1 + US4  ←── needs T014        │
   │                                                  │
Phase 3 (T039-T053)  US2        ←── needs T038, and T045-T047 need T006/T007
   │
Phase 4 (T054-T063)  US3        ←── needs T038; T057/T058 need T012; T061/T062 need T010+T011
   │
   └── T063 = RELEASABLE SLICE (Parts 1 and 2)
   │
Phase 5 (T064-T067)  US5        ←── needs T063 + Feature 002 live
Phase 6 (T068-T072)             ←── T070 needs T063
```

**Critical path**: T004 → T006 → T007 → T014 → T028 → T029 → T045. Everything about subagent confirmation traces back to the Phase 1 spike, which is why it is first.

## Parallel opportunities

- **Phase 1**: T002/T003 with each other; the three spikes (T004-T007, T008-T011, T012-T013) are mutually independent and can run in parallel with each other.
- **Phase 2**: T015 and T019 [P]; T034 alongside the pending-action work.
- **Phase 3**: T044 and T047 [P] once their implementations land.
- **Phase 4**: T054/T055/T056 [P] — three separate config surfaces.
- **Phase 6**: T068/T069 [P].

## Implementation strategy

**MVP = Phase 1 + Phase 2.** That delivers US1 and US4 — nothing irreversible without saying so, and unknown tools dangerous by default — using only tools that already exist. It is releasable and valuable before a single worker is configured, which is the point of building the guardrail in the same slice as the capability rather than after it.

**Incremental delivery**: Phase 3 adds the provenance defences the workers make necessary. Phase 4 adds the workers. T063 is the release boundary. Phases 5 and 6 follow without blocking it.

**Stop-and-report points** — three tasks are permitted to halt the feature rather than work around a finding:
- T013 — if the browser cannot run in the lean profile.
- T014 — if any spike outcome contradicts the plan.
- T064 — if calendar triggers need changes to Feature 002's engine core.
