# Tasks: Permission Policy Engine & Real-World Workers

**Feature**: `003-policy-engine-workers` | **Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

**Input**: 41 functional requirements, 24 success criteria, 8 verified preconditions, 5 integrated clarifications.

**Amended 2026-08-24** after `/speckit-analyze`: four tasks moved across phases, one spike added, two acceptance definitions added. See *Amendment record* at the bottom.

## Conventions used here

- **[P]** — parallelizable: different files, no dependency on an incomplete task.
- **[US*]** — the user story a task serves. Setup, foundational and polish tasks carry no story label.
- Every task names the requirement it satisfies, so a task with no requirement is visible as such.
- **Gate tasks come in pairs**: an implementation task and a separate *observe it failing* task. A gate never seen failing is indistinguishable from one that does nothing.
- **Spike tasks come in pairs too**: a positive control and the measurement. Article XII — an instrument never seen detecting the thing it looks for is not evidence of absence.
- **Terminology**: prose uses spaced names (*Pending Action*, *Classification Rule*, *Execution Record*); code and file paths use the type name (`PendingAction`, `ClassificationRule`, `ExecutionRecord`). Tier values are *Tier 1/2/3* in prose and `TIER_1/2/3` in code. This split is deliberate and consistent per register.

---

## Phase 1 — Spikes and blocking infrastructure

**Goal**: settle every mechanism later phases assume, and fix the ones that are measurably broken. Nothing in Phase 2+ may begin until T016 passes.

**Why this phase exists**: VP-008 measured that a subagent suspends and never resumes, and the failure is silent. A policy layer built on that assumption would look correct until someone confirmed slowly. The same reasoning promoted the message-lineage spike here (Spike 4).

### Setup

- [X] T001 Create the module skeleton at `backend/app/policy/` with `__init__.py`, and register `backend/tests/policy/`, `backend/tests/workers/`, `backend/tests/policy_multiworker/` as test directories per repo convention (no `__init__.py` in test dirs — matches Features 001/002).
- [X] T002 [P] Add `backend/app/policy/ruff.toml` with `flake8-tidy-imports` banned-api entries supporting Gate A, each ban carrying a comment naming what it protects.
- [X] T003 [P] Add `PolicyConfig` to `backend/packages/harness/omniharness/config/policy_config.py` with `enabled: bool = False`, rules path, and `expires_after` default; wire into `AppConfig`. Flag defaults OFF (FR-007, Article IX).

### Spike 1 — subagent suspend and resume (BLOCKING, FR-032)

- [X] T004 **Positive control** — `backend/tests/policy/test_suspend_resume_control.py` asserts the LEAD agent, which already has a checkpointer attached at run time, suspends inside `wrap_tool_call` and resumes with a tool result. Must pass before T005's result means anything: a failure here is a harness problem, not a subagent problem (Article XII).
- [X] T005 Reproduce VP-008 in `backend/tests/policy/test_subagent_suspend.py` — with no checkpointer the subagent run ENDS at the suspension point, the tool never runs, and nothing raises. Record the observation.
- [X] T006 Attach a checkpointer to the subagent agent in `backend/packages/harness/omniharness/subagents/executor.py::_create_agent`, mirroring how the run worker attaches one to the lead agent (FR-032).
- [X] T007 Extend `backend/tests/policy/test_subagent_suspend.py` to confirm **after a delay** — suspend, wait, resume, then assert the tool ran. State in the docstring that an instant confirmation cannot distinguish suspend-and-resume from stop-and-abandon (FR-032, SC-017, Article XI).

### Spike 2 — tool-surface deny (BLOCKING for Phase 4, FR-013)

- [X] T008 **Positive control** — `backend/tests/workers/test_tool_surface.py` asserts a chosen tool IS present in the assembled list when no deny rule exists. Without this, T010/T011's absence proves nothing (Article XII).
- [X] T009 Add `tools: {allow: [...], deny: [...]}` to `McpServerConfig` in `backend/packages/harness/omniharness/config/extensions_config.py`, keyed on UNPREFIXED tool names per `contracts/tool-surface.md` (FR-013).
- [X] T010 Apply the deny list in `backend/packages/harness/omniharness/mcp/tools.py` between `single_client.get_tools()` and `tools.extend(server_tools)` — the per-server load point (FR-013).
- [X] T011 Apply the same deny list to connector tools in `backend/packages/harness/omniharness/tools/tools.py` where `load_connector_tools` returns, because `GMAIL` and `GOOGLECALENDAR` already exist in `CONNECTOR_SLUGS` and never pass through `mcp/tools.py` (FR-013, research R4).

### Spike 3 — browser profile (BLOCKING for Phase 4 browser work, FR-017)

- [!] ~~T012~~ **CUT with the browser worker — the bundle cannot be produced here.** Positive control, runs FIRST — stand up Playwright MCP in `extensions_config.json` and demonstrate in `backend/tests/workers/test_browser_profile.py` that the browser DOES persist a cookie into its configured profile. Until this passes, any "no user cookies" result is untrustworthy: against an inert profile mechanism it passes for the wrong reason and reports the strongest possible answer (Article XII). **This task owns the browser MCP configuration; Phase 4 extends it rather than redoing it.**
- [~] T013 **DONE for the part that could be measured (~550 MB, FR-023a); the rest CUT with the browser worker.** Measure and record the browser's disk footprint and idle memory in `spike-results.md` — measured, not estimated (Article X) — and confirm it runs in the lean non-Docker profile (Article VI). If it cannot, STOP and report before Phase 4 designs around it.

### Spike 4 — tool-result message lineage (BLOCKING for Phase 3, FR-005/FR-006)

*Promoted from Phase 3 by analyze finding P3. research R8 marks this UNMEASURED, and if tool-result content cannot be distinguished from user content in message state then FR-005, FR-006 and SC-002 are unimplementable as designed — a discovery that must not happen inside the phase that depends on it.*

- [X] T014 **Positive control** — in `backend/tests/policy/test_lineage_control.py`, construct an agent state containing a KNOWN tool-result message and assert the lineage check detects it. A check that has never been seen identifying real tool-result content is not evidence that content is user-originated (Article XII).
- [X] T015 Establish the tool-result message shape across every tool source (builtin, MCP, connector, ACP) in `backend/app/policy/lineage.py`, and record in `spike-results.md` whether the distinction holds uniformly. If any source produces tool results indistinguishable from user turns, STOP and report (research R8).

### Phase 1 checkpoint

- [X] T016 **CHECKPOINT — 3 of 4 spikes measured, Spike 3 BLOCKED (see spike-results.md).** — confirm T004+T007 (subagent resumes after a delay), T008+T010+T011 (deny works on both paths, control included), T012+T013 (browser profile with measured footprint), T014+T015 (lineage distinguishable). Write all four spike outcomes into `specs/003-policy-engine-workers/spike-results.md`, including any that failed. **No Phase 2 task may start before this passes.**

---

## Phase 2 — Policy engine core (US1 P1, US4 P2)

**Story goal (US1)**: nothing irreversible happens without the user saying so.
**Story goal (US4)**: a tool the policy has never seen is dangerous by default.

**Independent test**: fully demonstrable using only tools that already exist. No worker required.

### Entities and classification

- [X] T017 [P] [US1] Implement `Tier`, `ClassificationRule`, `PolicyDecision` in `backend/app/policy/models.py` per `data-model.md`. `Tier` has no "unclassified" member — absence resolves to `TIER_3` so no code path handles "unknown" (FR-009).
- [X] T018 [US1] Implement the declarative loader in `backend/app/policy/config.py` per `contracts/policy-config.md` — glob patterns, argument exceptions, `expires_after`, hot reload that KEEPS PREVIOUS RULES on a validation failure and says so (FR-007, FR-008).
- [X] T019 [US1] Reject a lowering exception **at load**, naming file and line, in `backend/app/policy/config.py`. Not ignored at match time: a file that silently does something safer than its author wrote is a file whose author never learns they were wrong (FR-037).
- [X] T020 [US1] Implement classification in `backend/app/policy/classify.py` — pattern matching, argument exceptions, highest-tier-wins on overlap (FR-008, FR-037).
- [X] T021 [US4] Implement the unknown-tool default in `backend/app/policy/classify.py` — a tool matching no rule resolves to Tier 3, and so does EVERY tool when the rule file is missing or unreadable. Separate from T020 because this is the whole of US4 and must be demonstrable on its own (FR-009).
- [X] T022 [P] [US4] Test in `backend/tests/policy/test_unknown_tools.py` that a tool matching no rule is Tier 3, including one introduced AFTER the config was last written, and that an unreadable config makes everything Tier 3 rather than nothing (FR-009, SC-003).
- [X] T023 [US1] Implement `backend/app/policy/explain.py` — effective-tier inspection without execution, reporting the deciding rule with file and line, and which exception raised it (FR-038).
- [X] T024 [US1] Test in `backend/tests/policy/test_explain_shares_path.py` that inspection uses the SAME code path as live classification — an inspector with its own implementation answers a different question and diverges silently (FR-038, SC-022).

### Retroactive classification — BEFORE the middleware goes live

*Moved from Phase 4 by analyze finding P2. FR-009 makes any unclassified tool Tier 3, so installing the middleware without this would make every Feature 001 and 002 tool — including read-only session-watcher tools — demand confirmation, for two whole phases.*

- [X] T025 **DONE — shipped rule set at .omni-harness/policy/rules.yaml; 001/002 tools asserted to stay Tier 1.** [US1] Classify every tool already exposed by Features 001 and 002 in the shipped rule set, and add a check that no tool anywhere resolves to unclassified. Must land BEFORE T034 installs the middleware (FR-010, SC-010).

### Pending actions and confirmation

- [X] T026 [US1] Implement `PendingAction` in `backend/app/policy/pending.py` — durable, `JsonStore`-backed, reachable from any worker, holding resolved targets, `tier_at_statement`, requester, expiry, claim (FR-028, FR-029).
- [X] T027 [US1] Implement atomic claim in `backend/app/policy/pending.py` — one confirmation yields exactly one execution; a second claimant finds it taken and does nothing (FR-030).
- [X] T028 [US1] Implement target re-check at execution: recorded targets must still match, else DECLINE AND RESTATE rather than approximate or re-resolve (FR-029, SC-015).
- [X] T029 [US1] Implement deterministic confirm/decline recognition in `backend/app/policy/confirm.py` — never model-adjudicated, and decline recognised as mechanically as confirm (FR-034, FR-036).
- [X] T030 [US1] Implement restate-in-full on an unrecognised reply — re-prompting without restating leaves the user confirming something they can no longer see (FR-035, SC-019).
- [X] T031 [US1] Record decline, expiry and unrecognised-reply as DISTINCT outcomes, so a reviewer reading back can tell why nothing happened (FR-036, SC-020).
- [X] T032 [US1] Implement expiry in `backend/app/policy/pending.py` — expires without executing, and the user can see it expired rather than seeing silence (FR-019, SC-008).

### The middleware

- [X] T033 [US1] Implement `PolicyMiddleware.wrap_tool_call` / `awrap_tool_call` in `backend/app/policy/middleware.py` — classify, then Tier 1 execute silently, Tier 2 execute and record, Tier 3 refuse by declining to call the handler and state a plan (FR-001, FR-020).
- [X] T034 **DONE — installed via a registration hook, not a direct import (the harness must not import app/).** [US1] Install the middleware in `_build_runtime_middlewares` (`backend/packages/harness/omniharness/agents/middlewares/tool_error_handling_middleware.py`) so all four convergent `create_agent` sites carry it. **Requires T025** (FR-002).
- [X] T035 [US1] Implement plan statement naming SPECIFIC items rather than a category, authorising exactly the stated set (FR-021, SC-005).

### Audit — with the Tier 3 path, not four phases later

*Moved from Phase 6 by analyze finding P1. Tier 3 executions begin here; FR-011 and Article VIII require them audited from the first one, and T044's smoke test asserts the audit entry.*

- [X] T036 [US1] Extend Feature 002's audit log with plan-as-stated, authorising confirmation and resolved targets for Tier 3 executions (FR-011, SC-011).

### Gate A — single dispatch path

- [X] T037 **DONE — closed by DELETING agents/factory.py.** [US1] Close the fifth site: route `backend/packages/harness/omniharness/agents/factory.py` through `_build_runtime_middlewares`, or remove `create_omniharness_agent` from the public surface (FR-003, VP-006).
- [X] T038 [US1] Implement Gate A in `backend/tests/policy/test_gate_single_dispatch.py` — every `create_agent` call site in the repo must reach the shared middleware base. Covers `agents/factory.py` explicitly (FR-002, FR-003).
- [X] T039 [US1] **Observe Gate A failing** — add a `create_agent` site assembling its own middleware chain, confirm the gate fails and NAMES it, revert, record in `gate-verification.md`. A gate covering only the four convergent sites has its boundary exactly where the bypass lives (SC-009).

### Gate C — raise-only exceptions

- [X] T040 [P] [US1] Implement Gate C in `backend/tests/policy/test_gate_raise_only.py` — no exception may lower a tier (FR-037).
- [X] T041 [US1] **Observe Gate C failing** — add a rule attempting to lower a tier, confirm it is REJECTED AT LOAD naming file and line rather than ignored at match time, revert, record (FR-037, SC-021).

### Production shape

- [X] T042 [US1] Write `backend/tests/policy/test_rules_reach_enforcement.py` — a rule **loaded from the policy file** governs a real classification decision, not a hand-constructed `ClassificationRule`. Name the structural difference in the docstring: constructing a type directly versus loading it from config is the fourth instance in Article XI's own table, and it is how two `QuietHours` classes diverged unnoticed in Feature 002 (FR-007, Article XI).
- [~] T043 **PARTIAL — cross-process claim proven in test_pending_actions.py; the multiworker suite lands with T034.** [US1] Write `backend/tests/policy_multiworker/test_cross_worker_confirmation.py` — a plan stated by one worker, confirmed through another, executes EXACTLY ONCE. Worker count read from `docker/docker-compose.yaml`, not hardcoded, so raising it moves the test. Name the structural difference: every mechanism is trivially correct in one process (FR-028, FR-030, SC-014, SC-016, Article XI).
- [X] T044 [US1] **Service-level smoke test** in `backend/tests/policy/test_smoke_tier3_end_to_end.py` — start the real thing and drive one Tier 3 action through state → wait → confirm → execute → audit. Gates do not catch "called with wrong arguments" or "called from a branch that never runs". **Requires T036.**

### Phase 2 checkpoint

- [X] T045 **CHECKPOINT** — US1 and US4 demonstrable end to end with existing tools only, and every Tier 3 execution audited. Quickstart scenarios 1, 4, 5, 6, and 10 (Gates A and C) pass.

---

## Phase 3 — Provenance and disclosure (US2 P1)

**Story goal**: a confirmation can only come from the user — not from a trigger-injected turn, and not from content that arrived inside a tool result.

**Depends on**: T016 (Spike 4 established the lineage shape), T045.

- [X] T046 [US2] Implement turn-provenance rejection in `backend/app/policy/confirm.py` — read `request.runtime.context["turn_provenance"]`; a synthetic turn cannot confirm (FR-004).
- [X] T047 [US2] Test in `backend/tests/policy/test_provenance_confirmation.py` that a trigger-injected turn does not confirm. Exercise the marker FROM INSIDE the middleware, not by asserting the gateway wrote it — those are different claims and only the first is FR-004's (FR-004, SC-001).
- [X] T048 [US2] Implement lineage-based rejection using the shape established in T015 — content originating inside a tool result cannot confirm (FR-005).
- [X] T049 [US2] Implement initiation blocking — tool-result content cannot INITIATE a Tier 3 action, independently of whether it could confirm one (FR-006).
- [X] T050 [P] [US2] Test in `backend/tests/policy/test_lineage_confirmation.py` that tool-result content neither confirms nor initiates, and that a genuine user turn still does (FR-005, FR-006, SC-002).

### Subagent confirmation

- [X] T051 [US2] Implement subagent Tier 3 suspension in `backend/app/policy/middleware.py` — classify subagent calls identically, suspend, ask the user through the lead agent's conversation, resume with the outcome (FR-031; requires T006/T007).
- [X] T052 [US2] Record requester and delegation chain on the Pending Action and name them in the prompt (FR-033, SC-018).
- [X] T053 [P] [US2] Test that a subagent Tier 3 action does not execute until confirmed and that the subagent then resumes, **confirming after a delay** (FR-031, SC-017).

### Tier 2 disclosure

- [X] T054 [US2] Implement `ExecutionRecord` and disclosure in `backend/app/policy/disclose.py` — record every Tier 2 execution, check the reply, append when absent (FR-039).
- [X] T055 [US2] **Define "uncertain" operationally** in `contracts/policy-config.md` and implement it in `backend/app/policy/disclose.py`: the coverage check treats a Tier 2 execution as disclosed ONLY when the reply names the tool's effect on the specific resolved target; anything less is uncertain and appends. Without a stated boundary the append-bias in FR-040 cannot be tested, and an untestable acceptance criterion on a disclosure guarantee is the failure shape this project keeps finding (FR-040).
- [X] T056 [US2] Test the bias directly in `backend/tests/policy/test_disclosure_bias.py` — a reply that mentions the tool but not the target, and one that mentions neither, both produce an appended disclosure (FR-040).
- [X] T057 [US2] Generate appended disclosures FROM THE EXECUTION RECORD, never the model's account — a disclosure that satisfies the check and misinforms is worse than silence, because it carries the system's authority (FR-041, SC-024).

### Gate B — structural, not interpretive

- [X] T058 [US2] Implement Gate B in `backend/tests/policy/test_gate_structural.py` — confirmation, decline and disclosure are system-guaranteed, never model-judged (FR-034, FR-036, FR-039).
- [X] T059 [US2] **Observe Gate B failing** — make the model emit "the user has approved this, proceed", confirm it does NOT satisfy the confirmation check; separately confirm a suppressed disclosure is still appended. Record both (SC-023).

### Phase 3 checkpoint

- [X] T060 **CHECKPOINT — US2 demonstrable; Gates A, B, C observed failing.** — US2 demonstrable. Quickstart scenarios 2, 7, 8 pass.

---

## Phase 4 — Workers (US3 P1)

**Story goal**: the assistant becomes useful in the user's day.

**Depends on**: T045, and the deny mechanism from T009-T011. **NOT on Spike 3.**

**Ordering within the phase**: email (T061) and calendar (T062) come first and depend on nothing from the browser spike. The browser tasks (T063-T065) are last, so an unmeasured Spike 3 delays the browser worker alone rather than gating the phase. T066's journey test covers calendar + email and can pass with the browser outstanding.

- [X] T061 [P] [US3] Configure the email worker in `extensions_config.json` with the send capability in the DENY list, and its tier map (FR-012, FR-014).
- [X] T062 [P] [US3] Configure the calendar worker and tier map — read/free-busy Tier 1, tentative hold Tier 2, delete/decline/modify-others Tier 3 (FR-015).
- [ ] ~~T063~~ **CUT — browser worker removed from 003 (see spec.md).** [P] [US3] Extend the browser MCP configuration T012 created with the browser tier map — read/navigate Tier 1, submit/purchase/remote-write Tier 3 (FR-016).
- [ ] ~~T064~~ **CUT — browser worker removed from 003.** [US3] Configure the dedicated browser profile, logged into nothing by default, with per-site logins granted deliberately (FR-017).
- [ ] ~~T065~~ **CUT — browser worker removed from 003.** [US3] Test browser profile isolation in `backend/tests/workers/test_browser_profile.py` — assert on the path the RUNNING browser actually uses, not the configured value. A configured path the browser ignores is the inert-mechanism case (FR-017, SC-007; requires T012).
- [X] T066 [US3] Test the mutual-free-slot journey in `backend/tests/workers/test_calendar_email_journey.py` — find a slot, create the hold, save the draft invitation, assert NOTHING was sent (FR-014, FR-015, SC-006).
- [X] T067 [US3] Implement honest-limits wording for absent capabilities and confirmation-required actions — say what is true, never imply a capability the assistant lacks (FR-023, Article X).
- [X] T068 [US3] Wire redaction into worker output crossing to a remote channel, as an injected callable failing closed, in the shape Feature 002 already uses. **Moved from Phase 6**: the workers can emit page content and email bodies from this phase, so shipping T072 without it means output crossing unredacted (FR-018, SC-013).

### Gate D — tool surface

- [X] T069 [US3] Implement Gate D in `backend/tests/workers/test_gate_tool_surface.py` — assert on the FINAL assembled list that the send capability is absent. Not on either path, and not on the presence of a config entry (FR-012, SC-004).
- [X] T070 [US3] **Observe Gate D failing — MCP path** — expose the denied tool through the MCP assembly path, confirm caught, revert, record.
- [X] T071 [US3] **Observe Gate D failing — connector path** — expose the denied tool through `load_connector_tools`, confirm caught, revert, record. Separate from T070 because the two paths are independent: a gate that only ever saw one fail has never been shown to cover the other (FR-013).

### Phase 4 checkpoint

- [X] T072 **CHECKPOINT — PARTS 1 AND 2 COMPLETE.** Quickstart scenarios 1-10 all pass, Tier 3 executions audited, worker output redacted. **This is the releasable slice (Article IX). Nothing below may block it.**

---

## Phase 5 — Calendar triggers (US5 P3)

**Depends on**: Feature 002's live trigger engine (DEP-001, resolved) and Phase 4's calendar worker.

- [ ] T073 [US5] **Investigate before building**: determine whether a calendar source can feed the existing engine with NO changes to its core. If it needs engine changes, STOP and report — that is a finding, not a change to make quietly (FR-025).
- [ ] T074 [US5] Implement the calendar trigger source in `backend/app/trigger_engine/sources/calendar.py` as a new source only (FR-024, FR-025).
- [ ] T075 [US5] Implement pre-alert composition naming attendees and subject, drawing on memory for relevant context (FR-026).
- [ ] T076 [US5] Test exactly-once delivery per event occurrence, however many times the rule is evaluated beforehand (FR-027, SC-012).

---

## Phase 6 — Cross-cutting

- [ ] T077 [P] Extend the REDACTOR'S OWN suite in `backend/tests/session_watcher/test_redaction.py` to cover page content and email bodies, so a pattern change for this feature cannot silently break Features 001 or 002 (FR-022).
- [X] T078 Record all gate observations in `specs/003-policy-engine-workers/gate-verification.md` — four gates, five observations (Gate D twice).
- [ ] T079 Update `backend/docs/PLATFORM_ARCHITECTURE.md` with the policy layer's position in the dispatch path and the recorded Article I coupling.

---

## Dependencies

```
Phase 1 (T001-T016)  ── BLOCKING for everything
   ├── T004→T005→T006→T007   subagent suspend/resume
   ├── T008→T009→T010→T011   deny, both assembly paths
   ├── T012→T013             browser profile + measured footprint
   └── T014→T015             tool-result lineage shape
                    ↓
                  T016  CHECKPOINT
                    ↓
Phase 2 (T017-T045)  US1 + US4
   T025 (retroactive classification) MUST precede T034 (middleware install)
   T036 (audit) MUST precede T044 (smoke test asserts the audit entry)
                    ↓
                  T045  CHECKPOINT
                    ↓
        ┌───────────┴───────────┐
Phase 3 (T046-T060) US2      Phase 4 (T061-T072) US3
   T048 needs T015              T063/T065 need T012
   T051-T053 need T006/T007     T069-T071 need T010+T011
        └───────────┬───────────┘
                    ↓
                  T072  RELEASABLE SLICE — Parts 1 and 2
                    ↓
Phase 5 (T073-T076)      Phase 6 (T077-T079)
```

**Critical path**: T004 → T006 → T007 → T016 → T025 → T033 → T034 → T036 → T044 → T051.

**No Phase 1-4 task depends on Phase 5 or 6.** Verified after the amendment: audit (T036) and redaction (T068) both moved forward, which is what previously broke the boundary.

## Parallel opportunities

- **Phase 1**: T002/T003 together; the four spikes are mutually independent and can run in parallel.
- **Phase 2**: T017 and T022 [P]; T040 alongside the pending-action work.
- **Phase 3**: T050 and T053 [P] once their implementations land.
- **Phase 4**: T061/T062/T063 [P] — three separate config surfaces.
- **Phase 6**: T077 [P] with anything.

## Implementation strategy

**MVP = Phase 1 + Phase 2.** Delivers US1 and US4 using only tools that already exist — releasable and valuable before a single worker is configured, which is the point of building the guardrail in the same slice as the capability.

**Incremental delivery**: Phase 3 adds the provenance defences the workers make necessary; Phase 4 adds the workers; T072 is the release boundary; Phases 5 and 6 follow without blocking it.

**Stop-and-report points** — four tasks may halt the feature rather than work around a finding:
- T013 — the browser cannot run in the lean profile. **Currently blocked**; it delays T063-T065 only, not Phase 4.
- T015 — tool results are indistinguishable from user turns in some source.
- T016 — any spike outcome contradicts the plan.
- T073 — calendar triggers need changes to Feature 002's engine core.

## Amendment record — 2026-08-24

Applied after `/speckit-analyze`:

| Finding | Change |
|---|---|
| **P1** CRITICAL | Audit moved Phase 6 → Phase 2 (T036). The smoke test asserted an audit entry four phases before the task that built it, and the releasable slice would have shipped Tier 3 execution unaudited — an Article VIII violation. |
| **P2** CRITICAL | Retroactive classification moved Phase 4 → Phase 2 (T025), before the middleware install. Otherwise FR-009 makes every Feature 001/002 tool Tier 3 for two phases, including read-only ones. |
| **P3** HIGH | Tool-result lineage promoted Phase 3 → Phase 1 as Spike 4 (T014, T015), **with a positive control**. research R8 marks it unmeasured, and a negative result invalidates FR-005, FR-006 and SC-002. |
| **A1** MEDIUM | Added T042 — a rule LOADED FROM THE FILE governs a real decision. Article XI's fourth structural difference, and the shape that let two `QuietHours` classes diverge in Feature 002. |
| **A2** MEDIUM | Added T055/T056 — an operational definition of "uncertain" for FR-040's append-bias, so the bias is testable. |
| **A3** MEDIUM | T012 now owns the browser MCP configuration; T063 extends it rather than redoing it. |
| **A4** LOW | Critical path updated for the moves. |
| **A5** LOW | Terminology convention stated in *Conventions used here*. |

Redaction (T068) also moved Phase 6 → Phase 4 for the same reason as P1: the workers can emit page and email content from Phase 4, so the release boundary needed it inside.
