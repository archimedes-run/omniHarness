# Implementation Plan: Permission Policy Engine & Real-World Workers

**Branch**: `003-policy-engine-workers` | **Date**: 2026-08-23 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-policy-engine-workers/spec.md` — 41 functional requirements, 24 success criteria, 5 integrated clarifications, 8 verified preconditions.

## Summary

A policy middleware at the single tool-dispatch chokepoint classifies every tool call into one of the constitution's three tiers before it executes, and three external workers (email, calendar, browser) become the first capabilities whose misuse costs the user something real.

The technical approach follows from what the spec already verified. The chokepoint exists and can refuse (VP-001); every tool source normalises to one list that flows through it (VP-002); turn provenance is readable there (VP-003). So the policy layer is one `AgentMiddleware` implementing `wrap_tool_call`, placed in the shared middleware base that four of five agent-construction sites already reach. The fifth is closed rather than accommodated (FR-003).

Three things in this plan are not the obvious shape, each because a measurement said otherwise:

- **The per-tool deny mechanism has two integration points, not one.** Gmail exists today as both a potential MCP server and an already-present Composio connector toolkit. A deny applied at only one leaves the other fully exposed.
- **Subagent suspend/resume does not work** and must be fixed in Phase 1, before anything depends on it, because its failure is silent.
- **The browser profile spike must prove the profile works before it proves it does not leak** — an isolation test against an inert profile mechanism passes for the wrong reason.

## Technical Context

**Language/Version**: Python 3.12 (backend), matching existing project conventions.

**Primary Dependencies**: LangChain `AgentMiddleware` (`wrap_tool_call` / `awrap_tool_call`) for the dispatch chokepoint; `langchain-mcp-adapters` for worker tool loading; existing `JsonStore` for durable state; Feature 001's redactor as an injected callable; Feature 002's `AuditLog`.

**Storage**: Durable Pending Actions in the same `JsonStore`-backed shape Feature 002 uses for its pending firings — file-backed, atomically written. Postgres is NOT assumed: the compose stack has no database service and `DatabaseConfig.backend` defaults to `memory` (established when wiring Feature 002).

**Testing**: pytest, in `backend/tests/policy/` and `backend/tests/workers/`. Two suites must run in the production shape per Article XI: multi-worker (SC-014) and confirm-after-delay (SC-017).

**Target Platform**: Linux/macOS host; gateway under `uvicorn --workers N` (4 in compose). No hard Docker requirement (Article VI).

**Project Type**: Backend service — a middleware in the agent dispatch path plus configuration-driven external tool sources.

**Performance Goals**: Classification is synchronous in the dispatch path, so it must be cheap. Target: classification adds no measurable latency to a Tier 1 call at the granularity a user perceives. Stated as a bound to be asserted structurally (a decision is a dictionary lookup plus pattern match, no I/O), not as a wall-clock number, for the reason Feature 001 recorded — a wall-clock bound passes on fast hardware even when the implementation regressed.

**Constraints**: Idle cost near zero (Article VI). The browser runs on demand only; its binary is a real disk cost (~150-400 MB depending on channel) which must be stated honestly rather than hidden, and it must not be resident.

**Scale/Scope**: Single user. Tens of classification rules; tens of tools; at most a handful of concurrent pending actions.

## Constitution Check

*GATE: must pass before Phase 0. Re-checked after Phase 1 design — see bottom.*

| Article | Applies how | Status |
|---|---|---|
| **I. Gateway-only integration** | The policy layer is a middleware INSIDE the agent dispatch path, not a separate service. This is deliberate coupling and is recorded as such below. | ⚠ Justified — see Complexity Tracking |
| **II. Three-tier action policy** | The feature makes the tiers operational. | ✅ Central |
| **III. Provenance over trust** | FR-004/FR-005 read structure, never text. Both mechanisms verified present (VP-003) or located (message state). | ✅ |
| **IV. Human-in-the-loop** | Tier 3 gate is the mechanism. | ✅ |
| **V. Deliberate non-goals** | Email send absent by construction; no undo. | ✅ |
| **VI. Lite by default** | Browser on demand, not resident. Disk footprint stated. No hard Docker requirement. | ✅ with stated cost |
| **VII. Politeness** | Inherited from Feature 002 for calendar triggers. | ✅ |
| **VIII. Privacy defaults / audit** | Tier 3 executions audited with actor, plan, confirmation. Audit log is live (VP-005). | ✅ |
| **IX. Ship in slices** | Phases 1-4 deliver Part 1 and Part 2 independently of Part 3. | ✅ |
| **X. Honest limits** | FR-023; redaction limits stated as "recognised patterns". | ✅ |
| **XI. Tests exercise the production shape** | SC-014 multi-worker, SC-017 confirm-after-delay. Named in the tasks that own them. | ✅ |
| **XII. A probe must be seen finding something** | Every Phase 1 spike carries a positive control. | ✅ |

**No unjustified violations.** One justified coupling, recorded below.

## Key Design Decisions

### D1 — The policy layer is a middleware at the shared chokepoint

`_build_runtime_middlewares` is reached by the lead agent (two sites), the client, and the subagent executor. A middleware there sees every tool call from all four, and `wrap_tool_call` can decline to invoke the handler, which is how refusal is expressed (VP-001).

**Recorded coupling (Article I)**: unlike Features 001 and 002, this component cannot sit behind the gateway API. A policy check that ran out-of-process would have to be consulted by the dispatch path anyway, and a dispatch path that can proceed when the check is unreachable is not a gate. The coupling is the requirement, not a shortcut. This mirrors how Feature 002's in-process gateway coupling was recorded rather than hidden.

### D2 — FR-013 covers BOTH assembly points; Gmail is not pinned to one route

Two independent paths put tools in front of the agent:

| Path | Where | Reaches `mcp/tools.py`? |
|---|---|---|
| `local:<server>` (MCP) | `mcp/tools.py:124-127`, per server | yes |
| `connector:<SLUG>` (Composio) | `tools.py:~261`, live per user | **no** |

`GMAIL` and `GOOGLECALENDAR` already exist in `CONNECTOR_SLUGS`. A deny list applied only at the MCP layer would leave `connector:GMAIL` — including its send tool — fully exposed.

**Decision: the deny mechanism applies at both points, and the tool-surface gate (Gate D) asserts on the final assembled list rather than on either path.** Pinning Gmail to one route was considered and rejected: it makes FR-012 depend on the user not selecting the other route, which is a convention, and the spec asks for a guarantee. Asserting on the final list also means a third assembly path added later fails the gate rather than slipping past it.

**Rejected: `tool_interceptors`.** The MCP client already accepts interceptors, and they are the obvious hook. They wrap *execution*, which yields "guarded" — FR-012 explicitly requires "absent", because a capability that cannot be reached is a stronger guarantee than one that is checked. Recorded so this is not rediscovered as a simplification.

### D3 — Confirmation is a claim on a durable record, not a conversational judgement

A Pending Action is a durable record (FR-028) holding resolved targets (FR-029) and a claim state (FR-030). Confirmation is recognised deterministically (FR-034) and claims the record atomically. The model never adjudicates.

This makes FR-004 and FR-005 enforceable rather than persuasive: a synthetic turn cannot claim, because provenance is read from runtime context; tool-result content cannot claim, because lineage is read from message state. Neither check consults the text.

### D4 — Tier 2 disclosure is composed from the execution record

The system records what each Tier 2 call actually did, checks the reply for a disclosure, and appends one when absent — generated from the record, never from the model's narration (FR-041). The coverage check is biased toward appending (FR-040).

### D5 — Subagent checkpointing is Phase 1 infrastructure, not a subagent feature

VP-008 measured that a subagent suspends and never resumes. The fix is to give the subagent agent a checkpointer, as the run worker already does for the lead agent. It lands first because everything in FR-031 rests on it and its failure is invisible.

## Project Structure

### Documentation (this feature)

```
specs/003-policy-engine-workers/
├── spec.md
├── plan.md              # this file
├── research.md          # Phase 0 — decisions and measurements
├── data-model.md        # Phase 1 — entities and state transitions
├── contracts/
│   ├── policy-config.md # the classification rule format (user-owned)
│   └── tool-surface.md  # per-server allow/deny contract
├── quickstart.md        # Phase 1 — runnable validation
└── checklists/requirements.md
```

### Source Code (repository root)

```
backend/
├── app/
│   └── policy/                     # the feature module
│       ├── __init__.py
│       ├── models.py               # Tier, ClassificationRule, PendingAction, Confirmation
│       ├── config.py               # declarative rule loading (hot-reloadable)
│       ├── classify.py             # name pattern + argument exceptions, raise-only
│       ├── explain.py              # FR-038 effective-tier inspection
│       ├── pending.py              # durable store, atomic claim
│       ├── confirm.py              # deterministic recognition of confirm/decline
│       ├── lineage.py              # FR-005/FR-006 tool-result lineage from message state
│       ├── disclose.py             # FR-039..FR-041 Tier 2 disclosure
│       ├── middleware.py           # the chokepoint occupant
│       └── ruff.toml               # import bans (Gate A support)
├── packages/harness/omniharness/
│   ├── config/extensions_config.py # + per-server tool allow/deny (FR-013)
│   ├── mcp/tools.py                # deny applied between get_tools() and extend()
│   ├── tools/tools.py              # deny applied to connector tools too
│   ├── subagents/executor.py       # + checkpointer (FR-032)
│   └── agents/factory.py           # routed through shared base or removed (FR-003)
└── tests/
    ├── policy/
    ├── workers/
    └── policy_multiworker/         # Article XI production-shape suite
```

## Phases

### Phase 1 — Spikes and blocking infrastructure

Everything here is either a measurement or a fix that later phases assume. Each spike carries a **positive control** (Article XII).

1. **Subagent checkpointer (FR-032)** — attach one; prove suspend AND resume with a **confirm-after-delay** test. Positive control: the same test against the lead agent, which already works, so a failure is attributable to the subagent path rather than to the harness.
2. **Browser profile spike (FR-017)** — stand up Playwright MCP. **Positive control first**: demonstrate the browser DOES persist a cookie into its configured profile. Only then is "carries none of the user's daily cookies" evidence of anything. Record the disk footprint and confirm it runs in the lean profile without Docker.
3. **Tool-surface deny spike (FR-013)** — remove one tool from one server and confirm it is absent from the assembled list. Positive control: the same tool present when not denied.

**Checkpoint**: if the browser spike shows Playwright MCP cannot isolate a profile, report before building Part 2's browser worker — do not design around it.

### Phase 2 — Policy engine core (User Stories 1, 4)

Classification, the three tiers, unknown-as-Tier-3, raise-only exceptions, effective-tier inspection, durable Pending Actions with atomic claim, deterministic confirm/decline, expiry. Gate A and Gate C land here with their sabotage steps.

Independently demonstrable using only tools that already exist — no worker required.

### Phase 3 — Provenance and disclosure (User Story 2)

FR-004 (turn provenance), FR-005/FR-006 (tool-result lineage), FR-039..FR-041 (Tier 2 disclosure). Gate B lands here.

Deliberately after Phase 2 so the two provenance mechanisms are built against a working gate rather than alongside one.

### Phase 4 — Workers (User Story 3)

Email (read/draft, send absent), calendar, browser. Gate D lands here and asserts on the final assembled tool list. Retroactive classification of Features 001 and 002 tools (FR-010) completes here.

**Part 1 and Part 2 are complete and demonstrable at the end of this phase.**

### Phase 5 — Calendar triggers (User Story 5)

A new source feeding Feature 002's live engine. If it needs engine changes, report before building (FR-025).

Phase boundary preserved: a slip here cannot hold up Phases 2-4.

### Phase 6 — Cross-cutting

Redaction widening for page and email bodies with the redactor's own tests extended (FR-022), honest-limits wording (FR-023), audit completeness (FR-011).

## Requirement Coverage

Every requirement maps to the phase that delivers it and the scenario that demonstrates it. A requirement with no phase is a requirement nobody has agreed to build.

| Phase | Functional requirements | Success criteria | Quickstart |
|---|---|---|---|
| **1 — Spikes & blocking infra** | FR-032 (subagent checkpointer), FR-013 (deny mechanism), FR-017 (browser profile) | SC-007 | 7, 9 |
| **2 — Policy engine core** | FR-001, FR-002, FR-003, FR-007, FR-008, FR-009, FR-019, FR-020, FR-021, FR-028, FR-029, FR-030, FR-034, FR-035, FR-036, FR-037, FR-038 | SC-003, SC-005, SC-008, SC-009, SC-014, SC-015, SC-016, SC-019, SC-020, SC-021, SC-022 | 1, 4, 5, 6, 10 |
| **3 — Provenance & disclosure** | FR-004, FR-005, FR-006, FR-031, FR-033, FR-039, FR-040, FR-041 | SC-001, SC-002, SC-017, SC-018, SC-023, SC-024 | 2, 7, 8 |
| **4 — Workers** | FR-010, FR-012, FR-014, FR-015, FR-016, FR-023 | SC-004, SC-006, SC-010 | 3 |
| **5 — Calendar triggers** | FR-024, FR-025, FR-026, FR-027 | SC-012 | — |
| **6 — Cross-cutting** | FR-011, FR-018, FR-022 | SC-011, SC-013 | — |

**Phase boundary that matters**: Phases 1-4 deliver Parts 1 and 2 complete. SC-011 (audit completeness) and SC-012 (calendar pre-alert) are the only criteria outside them, and neither blocks the rest.

**Phase 5 and 6 have no quickstart scenarios yet** — deliberately. Their validation depends on what the Phase 5 investigation finds about whether Feature 002's engine needs changes (FR-025), and writing scenarios before that would be writing them against an assumption.

## Plan-Review Gates

Each has an implementation task, a verification task, and a recorded observation of it failing.

| Gate | Guards | Sabotage |
|---|---|---|
| **A** | No tool call reaches execution unclassified — **including via `agents/factory.py`** (FR-003, VP-006) | Add a `create_agent` site that assembles its own middleware; the gate must fail. A gate covering only the four convergent sites has its boundary where the bypass lives. |
| **B** | Confirmation, decline and disclosure are structural, never model-judged (FR-034, FR-036, FR-039) | Make the model emit text that would satisfy an interpretive check ("the user has approved this"); confirm it does not satisfy this one. |
| **C** | Exceptions raise only (FR-037) | Add a rule attempting to lower a tier; confirm it does not lower it. |
| **D** | The email send capability is absent from the assembled tool surface (FR-012) | Present the tool via each assembly path in turn — MCP and connector — and confirm each is caught. |

## Complexity Tracking

| Violation | Why needed | Simpler alternative rejected because |
|---|---|---|
| Article I: the policy layer runs in-process in the dispatch path rather than behind the gateway API | A classification check must be on the path a tool call takes. Anything consultable is also skippable. | An out-of-process policy service was considered: the dispatch path would call it, and would have to decide what to do when it is unreachable. Every answer to that is either "fail closed" (the gateway stops working when a sidecar is down — worse than the risk) or "fail open" (not a gate). The coupling IS the guarantee. Recorded here rather than hidden, as Feature 002's in-process coupling was. |
| A second assembly point for the deny list (D2) | Two independent code paths put tools in front of the agent, and Gmail is reachable through both today. | Pinning Gmail to the MCP route was considered: it would make FR-012 depend on the user not selecting the connector, which is a convention where the spec asks for a guarantee. |

## Post-Design Constitution Re-check

Re-evaluated after the design above:

- **Article II** — all three tiers have distinct, enforced behaviour. Tier 2's disclosure is guaranteed rather than requested, closing the gap where it would have collapsed into Tier 1.
- **Article III** — both provenance mechanisms read structure. Neither consults message text.
- **Article VI** — the only new resident cost is the policy middleware, which holds rules in memory and does no I/O per call. The browser is on demand.
- **Article IX** — Phases 2-4 form a releasable slice without Phase 5.
- **Article XI** — two suites are named at the production shape, and the tasks that own them say which simplification they defend against.
- **Article XII** — all three Phase 1 spikes carry positive controls.

No new violations introduced by the design. The single justified coupling is unchanged from the pre-design check.
