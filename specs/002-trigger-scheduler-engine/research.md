# Phase 0 Research: Trigger & Scheduler Engine

**Date**: 2026-08-21 | **Plan**: [plan.md](./plan.md)

All Technical Context unknowns resolved. No `NEEDS CLARIFICATION` remains.

---

## R1. Turn injection — verified, not assumed

**Decision**: inject via `langgraph_sdk`'s `client.runs.wait(thread_id, assistant_id, input=...,
config=..., context=...)`, with `runs.stream()` available where incremental output is wanted.

**Rationale**: this is not a proposed mechanism, it is the one the Telegram channel uses in
production today (`app/channels/manager.py:749`). The engine is a second caller of an existing,
exercised path rather than the first user of a new one.

**Alternatives considered**: the HTTP surface directly (`POST /api/threads/{id}/runs`) — equally
viable and useful for an out-of-process future, but the SDK gives typed results and the same
retry semantics the channel manager already relies on; a bespoke internal call into the agent
graph — rejected outright as an Article I violation.

**Why this was verified first**: Feature 001 planned against a gateway tool-registration API that
did not exist, costing a cycle. The rule adopted from that: where a plan depends on a mechanism,
read the code before planning on it.

---

## R2. Auth — works, in-process only

**Decision**: `create_internal_auth_headers()`, accepted by the auth middleware, which sets
`request.state.auth` to the internal user (`auth_middleware.py:85-114`).

**Constraint discovered**: `_INTERNAL_AUTH_TOKEN = secrets.token_urlsafe(32)` is generated at
module import and validated in-process. **A different process cannot produce a matching token.**
In-process is therefore not merely convenient — it is the only arrangement that works today.

**Alternatives considered**: a user JWT via `create_access_token()` — works off-process but
carries a 7-day expiry and no rotation story, and there is no service-account concept. Recorded
as **future work**, and as the concrete blocker should the engine ever need to run separately.

---

## R3. Mid-exchange detection — and a first reading that was wrong

**Decision**: query `GET /api/threads/{thread_id}/state`, whose `status` is derived live from the
checkpoint via `_derive_thread_status()` (`routers/threads.py:412`). Treat a `ConflictError` /
"already running a task" on injection as the race fallback, exactly as the channel manager does
(`manager.py:78`).

**Correction worth recording**: a first pass found only the error path and concluded there was no
query surface. That was wrong — the status field is populated, not a default. The wrong reading
would have produced a design that could only discover busyness by causing a failure.

**The consequence that survives either reading**: both signals are **pull, not push**. Nothing
calls back when an exchange ends. For a hung or abandoned run, no signal will ever arrive — which
independently confirms FR-016b's ruling that the queued-turn bound is the *primary* release path
and not a fallback for a rare case.

---

## R3b. The Phase 1 spike, and why status codes are not evidence

**Run 2026-08-21. Result: PASS**, after correcting three assumptions that would otherwise have
surfaced in Phase 3.

| Assumption | Reality |
|---|---|
| `assistant_id: "agent"` | **`lead_agent`**. The wrong value returned HTTP 200 with `messages: 0` and a `FileNotFoundError: Agent directory not found` buried in the server log. |
| tool body field `tool_ids` | **`sources`**. The wrong field returned **HTTP 200** and saved nothing. |
| marker readable from the reply | **No.** Absent from the `runs/wait` body; observable on the run record via `/state` and `/runs`. |

### The generalisable lesson: assert on resulting state, not on the response code

The tool-selection call is the sharp example. `PUT /threads/{id}/tools` with the wrong field name
returned **200 OK**. Nothing errored. A spike that checked `status_code == 200` would have passed,
recorded "tool configuration works", and the failure would have surfaced at T057 as an agent that
mysteriously lacked its tools — a long way from the typo that caused it.

What caught it was reading the **response body**, which echoed the saved selection and showed the
requested source missing. The same shape applies to the `assistant_id` error: 200, an empty
message list, and the real cause only in the server's log.

**Rule for future spikes: verify the state the call was supposed to produce, not the status of the
call.** A 200 means the request was understood well enough not to error. It does not mean it did
what you asked. This generalises past these two endpoints — anywhere a write is followed by a read
that could confirm it, the read is the assertion.

This pairs with the lesson already recorded for the transport spike: confirming the chosen option
works is not the same as establishing that the rejected one fails. Together they say a spike
should be designed around **what would falsify it**, not around what would demonstrate it.

---

## R4. Presence — derived from provenance, not tracked separately

**Decision**: presence is the timestamp of the most recent turn *lacking* the synthetic-trigger
marker required by FR-009.

**Rationale**: FR-009 already requires trigger turns to be structurally distinguishable from user
turns. Given that, a turn without the marker *is* a user turn, and its time is exactly the signal
FR-022 asks for — derived from channel interaction, never from host idleness. No second
mechanism, and nothing to fall out of sync with the first.

**Alternatives considered**: a dedicated last-seen tracker updated by each channel — more moving
parts and a second source of truth; thread `updated_at` — rejected, it advances on assistant
replies too, so it would report the *engine's own* activity as user presence, which is precisely
the self-referential error FR-022 exists to prevent.

---

## R5. Durable maps — reuse the existing pattern

**Decision**: JSON-file-backed stores with atomic writes for the rule-id → thread-id map and the
fingerprint store, following `ChannelStore` (`app/channels/store.py`).

**Rationale**: the repo already solved persist-a-small-map-durably, in the same process, for the
same class of data. FR-011b needs the same shape with a different key.

**Alternatives considered**: SQLite — heavier than the data warrants; in-memory — the failure
FR-011b names explicitly, presenting as a stable thread and behaving as a fresh one.

---

## R6. Scheduling without busy-poll

**Decision**: compute the next due time across all rules, sleep until it, wake, evaluate, and
recompute. Persist last-fired times so a missed schedule fires once on resume (FR-018, SC-004).

**Rationale**: FR-027 forbids busy-polling and Article VI caps idle cost. One timer to the next
due moment is O(1) work while idle.

**Alternatives considered**: a one-second tick loop — simple and disqualified by FR-027; an OS
scheduler — an external dependency, and it does not survive Article VI's no-hard-Docker rule
cleanly.

**Clock-jump handling**: due-times are computed from wall clock and de-duplicated by the
scheduled instant, so sleep/wake, NTP correction, and DST each yield at most one fire.

---

## R7. Redaction — reuse Feature 001's, widened

**Decision**: import Feature 001's `redaction` module at the delivery boundary for every
destination; widen the recognized-pattern set (FR-008c); keep the honesty wording (FR-008d).

**Rationale**: the module already fails closed, marks visibly, and is honest about its limits. It
was tuned for session-record text; agent-composed output is a wider input, which justifies more
patterns and **not** a stronger claim.

**Alternatives considered**: a second redactor for this feature — two implementations of a
security control is how one of them ends up weaker; restricting proactive output to state and
timing only — considered and rejected in clarification 3 as safe and useless.

---

## R8. Blast radius

**Decision**: each rule evaluation runs in a supervised task with an exception barrier and a
timeout; rule work never runs on a request-handling path.

**Rationale**: Feature 001's crash boundary came free from process separation. Sharing the
gateway process removes it, so it has to be rebuilt deliberately (FR-030–033).

**Alternatives considered**: a thread pool — adds GIL contention on a shared event loop for work
that is IO-bound anyway; a subprocess per rule — restores the boundary but forfeits the
in-process auth path (R2) and the Article VI budget.

---

## Resolved deferrals

| Item | Resolution |
|---|---|
| Thread-tool availability (FR-011) | `PUT /api/threads/{thread_id}/tools`; pinned servers need no action. Solvable, not blocked. |
| Audit-log obligation | Activates here — the agent acts without a human in the loop. Every firing and outcome is logged (plan, Article VIII note). |
| Out-of-process operation | Future work, blocked on a service-account concept that does not exist. |
