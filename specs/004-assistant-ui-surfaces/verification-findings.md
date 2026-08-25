# Feature 004 — Pre-Plan Verification Findings

**Status**: PLANNING HALTED. One load-bearing premise is false.
**Date**: 2026-08-25

Every mechanism the plan would rest on was checked against the running code before
planning on it. Six held. One did not, and it is the one Surface 1 is built on.

## BLOCKING — Tier 3 confirmation has no completion path in production

**The gate is half-wired.** The half that refuses works and is installed. The half that
grants has no production caller at all.

| Half | State | Evidence |
|---|---|---|
| Classify, refuse to execute, state the plan, record a `PendingAction` | **Works, installed** | `app/gateway/app.py:313` calls `install_policy()`; `PolicyMiddleware._require_confirmation` saves the action and returns the plan text as the tool result |
| Recognise a reply, claim the action, execute it | **No production caller** | Every caller of `recognise()`, `open_actions()`, `claim()` and `execute_confirmed()` is a test |

Verified exhaustively: `grep -rn` across the backend for each of the four symbols returns
only `tests/` and `app/policy/` definitions. Nothing outside `app/policy` touches policy
pending actions — the one `PendingStore` reference in the gateway belongs to the trigger
engine, a different class in `app/trigger_engine/persistence.py`.

**Consequence for a user today:** an assistant proposing a Tier 3 action states the plan
and durably records it. A user replying "yes, delete them" gets nothing. The action sits
until it expires. Tier 3 is currently **deny-with-explanation**, not
**confirm-to-proceed**.

**Why it happened structurally, not carelessly.** `PolicyMiddleware` hangs off
`wrap_tool_call`, which fires only when the model requests a tool. A bare confirmation
reply produces no tool call, so the middleware never runs on it. There was no hook where
recognition could have happened, which is exactly why `recognise()` was written,
unit-tested, and never called. This is the third instance of this shape in the project.

**The real seam.** `AgentMiddleware` in the installed langchain 1.2.17 exposes:

```
before_agent  before_model  wrap_model_call  wrap_tool_call  after_model  after_agent
(+ the a* async variants of each)
```

`before_model` / `abefore_model` run before each model call with access to state, so they
can read the latest human turn, call `recognise()` against `open_actions()`, `claim()`,
and `execute_confirmed()`. That is where a chat confirmation path belongs. Enumerated
from the installed package, not remembered.

## What this does to the specification

- **FR-004 has no referent.** It requires confirming through the UI to be "the same
  recognised act as confirming in chat". There is no chat confirmation to be the same
  as. The UI would be the FIRST completion route, not a second one.
- **SC-002 is currently untestable.** "Confirmed simultaneously through the UI and
  through chat executes once, not twice" presupposes the missing path.
- **Phase order changes.** A third backend prerequisite exists, ahead of FR-020 and
  FR-021 and more fundamental than either: Surface 1 is P1 and cannot be built on a path
  that does not exist.

## Two ways forward — this is a scope decision

**Option A — wire chat confirmation as part of 004, via `before_model`.** Both routes
then call one recognition-and-claim implementation, which is what FR-004 actually wants.
Adds backend scope to a UI feature, and makes SC-002 meaningful.

**Option B — make the UI the only confirmation route.** Rewrite FR-004 to say so and
drop SC-002. Smaller, and honest about what exists.

Option A is recommended for one reason: FR-004's real purpose is that exactly one
recognition-and-claim implementation exists. If chat is wired later, by someone else, a
second implementation is precisely what appears — and the atomic claim is the only thing
standing between that and a double execution.

## Verified as holding

| Premise | Evidence |
|---|---|
| Policy audit log is readable | `PolicyAuditLog.entries()` |
| Trigger audit log is readable | `AuditLog.entries()`, entries carry outcome + reason |
| Session registry exposes health and staleness | `SessionRegistry.observability()`, `.staleness_seconds()`; LIVE / STALE / never-observed |
| `explain()` shares the live dispatch path | calls the same `classify()` |
| Atomic claim is real | `claim()` links a file and returns the claimed action |
| Frontend conventions | `@tanstack/react-query` v5, hooks per domain at `src/core/<domain>/hooks.ts`, routes under `src/app/workspace/<area>/` |

## New integration point, not blocking but worth planning around

The session watcher runs as a **separate process**, exposing `list_sessions` and
`session_status` as MCP tools over SSE plus a `/health` route. The gateway imports only
`session_watcher.redaction`. Surface 2 therefore cannot read the registry in-process —
it needs the gateway to reach the watcher's server, or the watcher to publish somewhere
shared. A design decision for the plan, not a false premise.

---

## Addendum — requirements scoped by their heading (2026-08-25)

Prompted by C1: FR-009's content was correct and its *location* scoped it. Under
"Functional Requirements — Pending confirmations (Surface 1)", a rule meant to govern
confirmation everywhere reached only the UI. A structure defect, not a content one.

Audited 001–004 for the same shape.

| Feature | Requirement headings | Finding |
|---|---|---|
| 001 | one flat `### Functional Requirements` | Cannot have the defect |
| 002 | one flat `### Functional Requirements` | Cannot have the defect |
| 003 | Policy Engine / Workers / Calendar Triggers | **One instance — FR-023** |
| 004 | five per-surface headings | FR-004, FR-009 — fixed |

**003 FR-023**: *"The assistant MUST describe its own limits honestly. Where a capability
is absent (FR-012) or an action requires confirmation, the user-facing wording MUST say
what is actually true and MUST NOT imply a capability the assistant does not have."*

It sits under **Workers**. Its subject is not workers — it names confirmation wording
explicitly, which is Policy Engine territory, and it is a direct expression of Article X.
Located where it is, it reaches the email and calendar tools' wording and nothing else.

**Consequence for 004**: this feature adds four surfaces of user-facing wording — expiry
notices, drift explanations, `threshold_not_met`, "the watcher cannot be reached". Under
its current heading FR-023 does not reach any of them. It is not re-scoped here, because
editing a shipped feature's spec to widen a requirement is a change to what 003 claims to
have delivered, and that is a decision rather than a correction. Recorded so the choice is
visible.

The general lesson, worth applying at spec time rather than at analyze time: **a
requirement under a scoping heading inherits that scope silently.** When a requirement's
subject is broader than the section it sits in, the section wins, and nothing in the
document says so.
