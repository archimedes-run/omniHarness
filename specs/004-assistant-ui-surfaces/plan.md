# Implementation Plan: Assistant UI Surfaces

**Branch**: `004-assistant-ui-surfaces` | **Date**: 2026-08-25 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/004-assistant-ui-surfaces/spec.md`

## Summary

Four browser surfaces over Features 001–003, plus the backend work three of them turn
out to require. Planning was halted once and resumed after a scope decision: verification
found that **Tier 3 confirmation has no completion path in production**, so Surface 1 —
the feature's reason for existing — had nothing to operate. That path is now Phase 1.

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript / Next.js (frontend)
**Primary Dependencies**: langchain 1.2.17 (`AgentMiddleware`), FastAPI, `@tanstack/react-query` v5.90.17
**Storage**: JSON-per-action pending store; append-only JSONL audit logs (policy, trigger); in-memory session registry in the watcher process
**Testing**: pytest + mypy (backend); vitest (frontend units); Playwright in CI only (rendering)
**Target Platform**: desktop browser; gateway runs `uvicorn --workers 4`
**Project Type**: web application (frontend + backend)
**Performance Goals**: not a driver; volumes are single-user scale
**Constraints**: no rule editor; read surfaces perform no writes; rendering assertions CI-only; no gitignored reads including tests
**Scale/Scope**: 4 surfaces, ~39 functional requirements, 19 success criteria

## Constitution Check

*Gate: checked before Phase 0, re-checked after Phase 1 design.*

| Article | Bearing on this feature | Status |
|---|---|---|
| I — Gateway-only integration | Surfaces call the gateway; the watcher is reached by the gateway, never by the browser | PASS |
| II — Three-tier action policy | Phase 1 completes the Tier 3 loop rather than weakening it; classification is unchanged | PASS |
| III — Provenance over trust | `recognise` keeps both structural checks — synthetic-turn and message-lineage — and the UI route adds a third channel that is provenance-checked in its own right | PASS |
| IV — Human-in-the-loop | The whole feature is this article made operable | PASS |
| VI — Lite by default | No new runtime dependency; reuses existing libraries | PASS |
| VIII — Privacy defaults | FR-031: rendered content passes the redactor and fails closed | PASS |
| IX — Ship in slices | Six phases, each independently valuable; phase boundaries stated below | PASS |
| X — Honest limits | FR-009's default is labelled a guess in the requirement itself; the watcher dependency is a specified state, not a hidden failure | PASS |
| XI — Production shape | Confirmation is tested at the real worker count; rendering assertions run against a real build | PASS |
| XII — A probe must be seen finding something | Every gate ships with a sabotage; the `before_model` probe recorded its positive control and its one false failure | PASS |
| XIII — Initiation and confirmation are separate defences | Preserved: the assistant proposes, the user presses. FR-009 adds a scope-proportionate second factor | PASS |
| XIV — No gitignored guarantee | FR-032, enforced by the existing shipped-paths scan, now covering both navigation idioms | PASS |

**No violations requiring justification.**

## Phasing — and why the order is not negotiable

Two phases are backend work inside a UI feature. **Neither phase boundary is a
releasable slice that includes a view over data that is not yet recorded.** Stated
explicitly because the natural reading of "UI feature, six phases" is that each phase
ships a surface, and here the first two ship none.

### Phase 1 — The confirmation completion path (blocking; no UI)

**Nothing in Surface 1 can be built before this.** Tier 3 today is
deny-with-explanation: the assistant states the plan, records a `PendingAction`, and no
code path can ever grant it. A user approves, nothing happens, approves again, nothing
happens — and learns to route around the gate by doing the thing manually. That is the
failure the deterministic-decline requirement exists to prevent, and it is live on main.

- Chat confirmation via `before_model` / `abefore_model` on the policy middleware:
  read the latest human turn, `recognise` against `open_actions`, `claim`,
  `execute_confirmed`, return the outcome into the conversation.
- **One recognition-and-claim implementation**, shared by both routes. The UI route in
  Phase 3 calls the same function. A gate asserts there is exactly one.
- `expire_due` gets a caller, closing Feature 003's FR-019 — expiry currently produces
  the silence that requirement forbids.
- Delivers value with no UI at all: Tier 3 becomes usable in chat.

### Phase 2 — Trigger recording (blocking for Surface 3; no UI)

- **FR-020**: record when each rule was last evaluated. Without it, "evaluated five
  hundred times, never fired" and "never evaluated" are the same row, which is the
  distinction that makes a silently-broken rule findable and the one the calendar
  lead-time bug fell into.
- **FR-021**: shared batch identity across firings delivered together after coalescing.
  Deliberately **not** a sixth outcome — a coalesced firing was delivered, and recording
  otherwise would put a false statement in the audit log.
- Backfill is not attempted; historical rows render as "not recorded" (FR-022).

### Phase 3 — Surface 1, pending confirmations (P1, first UI)

Read + confirm/decline, including FR-009's scope threshold. Cross-worker behaviour tested
at the production worker count.

### Phase 4 — Surface 3, trigger activity (P2)

Depends on Phase 2. First phase whose data was created by this feature.

### Phase 5 — Surface 2, coding sessions (P3)

Gateway reaches the watcher's SSE server (research R2). Four conditions kept distinct:
unreachable, never-observed, stale, live.

### Phase 6 — Surface 4, policy inspector (P4), and the cross-cutting gates

Includes the a11y promotion (FR-034) and the generalised wiring gate (research R3).

## Project Structure

### Documentation (this feature)

```
specs/004-assistant-ui-surfaces/
├── spec.md
├── verification-findings.md     # why planning halted, and what was verified
├── plan.md                      # this file
├── research.md                  # Phase 0
├── data-model.md                # Phase 1
├── quickstart.md                # Phase 1
└── contracts/
    └── api.md                   # Phase 1
```

### Source Code (repository root)

```
backend/
├── app/policy/
│   ├── confirm_flow.py          # NEW — the one recognition-and-claim implementation
│   └── middleware.py            # before_model added
├── app/trigger_engine/
│   ├── models.py                # Firing gains batch identity
│   └── engine.py                # evaluation recording
├── app/gateway/routers/
│   ├── confirmations.py         # NEW
│   ├── sessions.py              # NEW
│   ├── triggers.py              # NEW
│   └── policy.py                # NEW
└── tests/
    ├── policy/                  # confirmation path, gates
    └── gates/test_wiring.py     # NEW — generalised from Gate 4

frontend/
├── src/app/workspace/{confirmations,sessions,triggers,policy}/
├── src/core/{confirmations,sessions,triggers,policy}/hooks.ts
├── src/components/workspace/{confirmations,sessions,triggers,policy}/
└── tests/rendering/             # CI-only rendering assertions
```

## Complexity Tracking

| Deviation | Why needed | Simpler alternative rejected because |
|---|---|---|
| Backend work inside a UI feature (Phases 1–2) | Three surfaces read data that is not recorded, and Surface 1 operates a path that does not exist | Building the views first would ship blank columns and a control that cannot act — the spec's own success criteria (SC-002, SC-008, SC-009, SC-010) would be untestable |
| A second confirmation route | The UI is the point of the feature | A UI-only route was the alternative and was rejected: chat confirmation is broken today, and leaving it broken teaches users to bypass the gate |
| Generalising Gate 4 rather than adding a policy copy | The same gap would reopen for Feature 005 | A `app/policy`-scoped copy would be the third hardcoded module path, and the gap is the hardcoding |
