# Implementation Plan: Trigger & Scheduler Engine

**Branch**: `002-trigger-scheduler-engine` | **Date**: 2026-08-21 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-trigger-scheduler-engine/spec.md`

## Summary

A rule engine running in the gateway process. Rules evaluate on a scheduler tick or an inbound
event; a fired rule composes a prompt, injects it as an ordinary user turn through the public
SDK client, and routes the reply to a destination — after redaction, coalescing, and the
politeness gates.

The load-bearing decision is FR-007's: a firing is *just a turn*. Everything the agent can
already do — skills, tools, memory — comes along at no cost, and no second execution path exists
to diverge from the first.

## Technical Context

**Language/Version**: Python 3.12, matching `backend/pyproject.toml`.

**Primary Dependencies**: `langgraph-sdk` (already a backend dependency — the public client, not
LangGraph internals; see Gate 1), `croniter` or equivalent for schedule arithmetic (**new**),
`app.gateway` public surfaces. Reuses Feature 001's redaction module.

**Storage**: A durable rule-id → thread-id map and a fingerprint store, both JSON-file-backed
with atomic writes, following the `ChannelStore` pattern already in the repo
(`backend/app/channels/store.py`). No database.

**Testing**: `pytest` in `backend/tests/trigger_engine/`.

**Target Platform**: In-process with the gateway. See the Article I record below for why that is
a deliberate decision rather than a convenience.

**Project Type**: An in-process engine with a scheduler, not a service and not a library.

**Performance Goals**: A watcher event reaches delivery within 60 s (SC-001). Idle cost
indistinguishable from idle with no rule due (SC-012).

**Constraints**: Must not crash or stall the gateway (FR-030–033). Must not busy-poll (FR-027).
Must not assume co-location with the user, their machine, or the event source (FR-028).

**Scale/Scope**: Tens of rules, a single user. Fingerprints reset daily.

## Verification Record — mechanisms checked before planning on them

*Feature 001 cost a cycle by planning against a gateway registration API that did not exist, and
another by asserting a stdio limitation that was false. Every mechanism this plan depends on was
read in the code first. What follows is what was found, including where a first reading was
wrong.*

| Question | Finding | Source |
|---|---|---|
| Can a server-side caller post a user turn? | **Yes.** `client.runs.wait(thread_id, assistant_id, input={"messages": [{"role": "human", ...}]}, config, context)` — already in production use by the Telegram channel. | `app/channels/manager.py:749` |
| How is the reply observed off-browser? | **Two ways.** `runs.wait()` returns the final result; `runs.stream()` yields chunks. The manager selects per channel capability. | `manager.py:749, 808` |
| Does auth admit a non-browser caller? | **Yes, in-process only.** `create_internal_auth_headers()` is accepted by the auth middleware, which sets `request.state.auth` to the internal user. | `internal_auth.py`, `auth_middleware.py:85-114` |
| Is the thread model constrained? | **No.** `runs.wait()` accepts any thread id; the channel manager persists a key→thread map and reuses it. Pre-existing, per-rule and per-firing are equally supported. | `manager.py:709`, `channels/store.py:82` |
| Can a caller configure a thread's tools? | **Yes.** `PUT /api/threads/{thread_id}/tools`, guarded by `require_permission`, which internal auth satisfies. FR-011 is solvable. | `routers/thread_tools.py:176` |
| Can the engine tell whether the user is mid-exchange? | **Yes — corrected on second reading.** A first pass found only `_is_thread_busy_error` (a `ConflictError` raised when *attempting* a run) and concluded there was no query surface. There is: `GET /api/threads/{thread_id}/state` returns a live status derived from the checkpoint. | `routers/threads.py:412`, `manager.py:78` |

**Two consequences that shape the design:**

**There is no exchange-finished event.** Both mid-exchange signals are pull, not push — a status
query and an error on attempt. Nothing calls back when a run ends. This independently confirms
the FR-016b ruling that the queued-turn bound is the *primary* release path rather than a
fallback: for a hung run, no signal will ever arrive.

**Presence falls out of provenance.** FR-009 already requires synthetic turns to be structurally
distinguishable from user turns. A run *without* that marker is therefore a user turn, and its
timestamp is the presence signal FR-022 needs — derived from channel interaction, never from host
idleness, with no separate tracking mechanism to keep in sync.

## Constitution Check

*GATE: evaluated before Phase 0, re-evaluated after Phase 1.*

| Article | Requirement | Design response | Status |
|---|---|---|---|
| I — Gateway-only | No core imports | Public SDK + gateway HTTP surfaces. **Satisfied differently from 001** — see the record below. | **PASS (recorded)** |
| II — Three-tier policy | Every tool call classified | The engine calls no tools itself; it injects turns and the agent's existing policy applies unchanged. | **PASS** |
| III — Provenance | External content is data; confirmations only from trusted channels | FR-009/FR-010: synthetic turns structurally marked, and incapable of satisfying a confirmation. SC-014 tests the adversarial case. | **PASS (central)** |
| IV — Human-in-the-loop | Never auto-approve coding-agent permissions | The engine observes watcher events and never answers them. Feature 001 exposes no answer path. | **PASS** |
| V — Non-goals | No autonomous email/browser/companion | A rule could be written to draft email, but the engine adds no such capability and initiates no browser action. | **PASS** |
| VI — Lite by default | < 500 MB idle, near-zero idle CPU, no hard Docker | Event-driven scheduler, no busy-poll (FR-027). Shares the gateway process rather than adding one. | **PASS (gated)** |
| VII — Politeness | Quiet hours, coalescing, no interruption, presence routing | **This is the feature that discharges it.** FR-013–FR-018, each with success criteria. | **PASS (central)** |
| VIII — Privacy defaults | Local-first, audit log | Redaction at every delivery boundary (FR-008a–d). **Audit log: see below.** | **PASS w/ note** |
| IX — Ship in slices | Independently useful | US1 alone — a blocked session reaching your phone — is shippable. | **PASS** |
| X — Honest limits | No fake precision | Heuristic defaults labelled as heuristics; FR-029 forbids reporting an unreachable source as an absence of events. | **PASS** |

**Article VIII — the audit-log obligation activates here.** Feature 001 recorded that no audit log
was required because every tool was Tier 1 and no approval was relayed, and that the obligation
would arrive with the first Tier-3 action. This feature does not itself introduce a Tier-3 tool —
but it does cause the agent to act **without a human in the loop**, which is the condition the
article's logging exists to make reviewable. **Decision: log every firing and its outcome**
(FR-012 already requires the outcome be recorded); route it to the same local append-only audit
log Article VIII names. This is cheap now and expensive to retrofit once rules are numerous.

**No violations require justification.** Complexity Tracking is omitted.

## Architectural Record — Article I is satisfied differently here than in Feature 001

*Written down deliberately, before the difference drifts into precedent.*

| | Feature 001 (watcher) | Feature 002 (this engine) |
|---|---|---|
| Process | Separate, on the user's machine | **In-process with the gateway** |
| Boundary | MCP protocol over SSE | Public SDK client + gateway HTTP surfaces |
| Imports from repo | **Zero** | `langgraph_sdk`, `app.gateway.internal_auth`, Feature 001's redaction module |
| Enforcement | Ban `omniharness*`, `langgraph*` | Ban `omniharness*`, `langgraph`/`langgraph.*`; allow `langgraph_sdk` |

**Both satisfy Article I, and the distinction that makes them both legitimate is
public-surface-versus-internals — not same-repo-versus-different-repo.** `langgraph_sdk` is a
client for a server. `app.gateway.internal_auth` is the gateway's own published way for an
in-process caller to authenticate. Neither reaches into agent-core internals, which is what the
article actually prohibits.

**This is not a licence to import anything gateway-shaped.** Importing
`app.gateway.routers.*` internals, agent graph construction, or `omniharness.*` remains
prohibited and remains lint-enforced. If a future feature wants a broader exception, it argues
for it explicitly rather than citing this one.

**In-process is currently the only workable arrangement**, not merely the convenient one: the
gateway's internal token is generated per process (`secrets.token_urlsafe(32)` at import) and
validated in-process. **Future work, not this feature**: running the engine out-of-process needs
a service-account credential concept that does not exist. A 7-day user JWT is not one.

## Plan-Review Gates

*Each gate ships with a task that deliberately breaks what it guards and confirms the gate bites.
A gate never observed failing is indistinguishable from one that does nothing — the standing
convention from Feature 001, which caught three defects a green suite could not see.*

### Gate 1 — Narrowed import ban (SC-011, Article I)

**The risk, and it cuts both ways.** Feature 001 banned `langgraph*` as a glob. This feature
*requires* `langgraph_sdk`. The tempting fix — widen or delete the glob — would silently permit
`import langgraph.graph` and lose Article I's enforcement entirely.

**Resolution**: ban `langgraph` and `langgraph.*` as **exact patterns**; allow `langgraph_sdk` as
a **named exception with its rationale recorded in the config file** — it is a client for a
server, not a reach into internals.

**Verification — both directions, which is the point:**

- `import langgraph.graph` MUST fail.
- `import langgraph_sdk` MUST pass.

A one-directional test would let a later "simplification" restore the glob (breaking the build in
a way someone would then fix by deleting the ban) or drop the ban entirely, and neither would
fail. Also banned: `omniharness*`, `app.gateway.routers.*`, and direct agent-graph imports.

### Gate 2 — Blast radius (FR-030–033, SC-017/018)

**The risk.** Feature 001 got a crash boundary for free from process separation. This engine has
none: a rule that raises or blocks the shared event loop takes the whole assistant with it.

**Resolution**: every rule evaluation runs inside its own supervised task with an exception
barrier and a timeout. Rule work never runs on a request-handling path. A rule exceeding its
bound is cancelled, reported, and backed off (FR-026).

**Verification**: a deliberately **crashing** rule and a deliberately **blocking** rule, each
proven not to affect the gateway or any other rule. Ordinary requests must be served with no
measurable added latency while the blocking rule hangs. Per FR-033, an isolation claim never
tested against a real failure is not evidence.

### Gate 3 — One release path, two entry conditions (FR-013d, FR-016c)

**The risk.** Quiet-hours release and queue-expiry release do the same thing: re-check, then
coalesce, then deliver. Implemented twice, the second copy acquires its own defects in whichever
path runs least often and is watched least.

**Resolution**: a single `release(items, reason)` mechanism. Both conditions call it. No second
delivery path exists.

**Verification**: a test asserting both entry conditions reach the *same* function, plus a
sabotage that adds a second delivery path and confirms the test fails.

### Standing convention

Every gate above ships with its observe-it-fail task, and outcomes are recorded in
`gate-verification.md` as in Feature 001 — durable, because a PR description is not.

## Project Structure

### Documentation (this feature)

```text
specs/002-trigger-scheduler-engine/
├── plan.md              # This file
├── research.md          # Phase 0
├── data-model.md        # Phase 1
├── quickstart.md        # Phase 1
├── contracts/
│   └── rule-schema.md   # Phase 1 — the rule file is this feature's public interface
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 — NOT created by /speckit-plan
```

### Source Code (repository root)

```text
backend/app/trigger_engine/
├── __init__.py
├── ruff.toml                  # Gate 1: exact langgraph ban + langgraph_sdk exception
├── config.py                  # Rule file load, validate, hot-reload (FR-005/006)
├── models.py                  # Rule, TriggerEvent, Firing, Outcome
├── engine.py                  # Supervised evaluation loop (Gate 2)
├── scheduler.py               # Event-driven cron arithmetic, no busy-poll (FR-027)
├── sources/
│   ├── base.py                # TriggerSource interface
│   ├── cron.py                # Scheduled times (FR-018)
│   ├── watcher.py             # Feature 001 events over MCP (FR-028: may be remote)
│   └── completion.py          # Long-running task completion
├── fingerprint.py             # Event identity + daily reset (FR-017a/b/c)
├── injector.py                # Turn injection via SDK; provenance marking (FR-009/010)
├── threads.py                 # Durable rule-id -> thread-id map (FR-011a/b/c)
├── presence.py                # Last non-synthetic turn (FR-022/023)
├── politeness/
│   ├── quiet_hours.py         # Suppress + defer (FR-013a-d)
│   ├── coalesce.py            # Merge window (FR-015)
│   ├── interrupt.py           # Mid-exchange detection + queue (FR-016a-c)
│   └── release.py             # THE single release path (Gate 3)
└── destinations/
    ├── base.py                # OutputDestination port (FR-019/020)
    ├── remote.py              # Telegram
    └── quiet.py               # Record without delivering

backend/tests/trigger_engine/
├── fixtures/
├── test_config_reload.py      ├── test_fingerprint.py
├── test_scheduler.py          ├── test_injection_provenance.py
├── test_threads_mapping.py    ├── test_presence.py
├── test_quiet_hours.py        ├── test_coalesce.py
├── test_interrupt_queue.py    ├── test_release_path.py
├── test_redaction_boundary.py ├── test_blast_radius.py
├── test_no_banned_imports.py  └── test_us1_blocked_session.py
```

**Structure Decision**: `backend/app/trigger_engine/` — under `app/`, alongside `gateway/` and
`channels/`, because it runs in that process and is a peer of the channel manager rather than a
standalone package like the watcher. This is inside `^backend/`, so the existing pre-commit hooks
apply with no config change (the Feature 001 placement lesson).

## Post-Design Constitution Re-Check

*Re-evaluated after Phase 1. Artifacts: [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/rule-schema.md](./contracts/rule-schema.md),
[quickstart.md](./quickstart.md).*

All ten articles hold. Three became **stronger** once the design was concrete:

- **Article III** — provenance is not only enforced, it is *load-bearing elsewhere*: presence
  derives from the absence of the synthetic marker (R4). A regression that weakened provenance
  would break presence routing too, which makes it far more likely to be noticed.
- **Article VII** — the four politeness requirements converge on one `release()` path (Gate 3)
  rather than being scattered across delivery sites, so there is a single place they can be
  verified and a single place they could be bypassed.
- **Article VIII** — the audit-log obligation that Feature 001 deferred is discharged here, and
  FR-012 already required the data it needs.

**One design decision flagged for review**, not a violation: the engine imports Feature 001's
redaction module directly. That is a cross-feature code dependency the watcher does not have in
reverse. It is the right call — two implementations of a security control is how one ends up
weaker — but it means the redactor is now shared infrastructure rather than one feature's
internal detail, and a change to it affects both. Worth extracting to a shared location if a
third consumer appears.

**No violations. Complexity Tracking below remains empty.**

## Complexity Tracking

No constitutional violations require justification. Section intentionally empty.
