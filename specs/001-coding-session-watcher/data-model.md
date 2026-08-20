# Phase 1 Data Model: Read-Only Coding-Session Watcher

**Date**: 2026-08-20 | **Plan**: [plan.md](./plan.md) | **Research**: [research.md](./research.md)

All entities are in-memory. Nothing is persisted; nothing is written to observed files (FR-019).

---

## Session

The central entity. Discovered, never created by this feature (FR-001).

| Field | Type | Source | Notes |
|---|---|---|---|
| `session_id` | str | observed `sessionId` | Adopted verbatim; never minted by us (R2). Alias fallback `session_id`. |
| `project` | str | observed `cwd` + `gitBranch` | Preferred over the directory slug, which carries a leading hyphen (R2). |
| `state` | `SessionState` | derived | See state machine below. |
| `idle_reason` | `IdleReason \| None` | derived | Required when `state is IDLE`; `None` otherwise (FR-003a). |
| `last_message` | str | most recent `assistant` record | Passes through redaction before ever leaving the process (FR-011c). |
| `started_at` | datetime | first record timestamp | |
| `last_activity_at` | datetime | most recent record timestamp | Drives the inactivity timeout (FR-006a). |
| `sticky` | bool | set on first observed activity | Once true, exempt from the recency window until terminal (FR-005c). |
| `events` | list[SessionEvent] | derived | Ordered; bounded ring buffer. |

**Validation rules**

- `idle_reason` is non-`None` **iff** `state is IDLE` — enforced at construction, because the
  whole point of FR-003a is that the two never drift apart.
- `session_id` is non-empty; a record without one is skipped at debug level (FR-009).
- `last_activity_at >= started_at`.
- A session is never removed while `sticky` and non-terminal (FR-005c).

### SessionState

```
WORKING | WAITING_ON_USER | IDLE | FAILED | UNKNOWN
```

`COMPLETED` is deliberately **not** a top-level state — it is an `IdleReason`. This is the
structural expression of the Q1 clarification: completed and stalled are both idle, and the
difference between them must survive rather than collapse.

### IdleReason

| Value | Meaning | Epistemic status |
|---|---|---|
| `COMPLETED` | An end-of-turn / stop record was **observed** | Fact |
| `STALLED` | The inactivity period elapsed with **no** such record | Inference |

`FR-016a` binds the wording each produces. `UNKNOWN` state is distinct from `STALLED`: unknown
means the records could not be interpreted at all (FR-006), stalled means they were interpreted
and showed nothing.

### State transitions

| From | To | Trigger | Requirement |
|---|---|---|---|
| *(discovered)* | WORKING / IDLE | initial parse | FR-001 |
| WORKING | IDLE(COMPLETED) | end-of-turn record observed | FR-006a — marker first |
| WORKING | IDLE(STALLED) | inactivity period elapsed, no marker | FR-006a — time as fallback |
| WORKING | WAITING_ON_USER | latest record is `assistant`, none follows, within timeout | R2 finding 3 — **inferred** |
| WAITING_ON_USER | WORKING | a `user` record follows | FR-010 event cleared |
| WAITING_ON_USER | IDLE(STALLED) | inactivity period elapses | |
| *any* | FAILED | failure record observed | FR-007 |
| *any* | UNKNOWN | records present but uninterpretable | FR-006 |

**The marker-first ordering is a hard invariant**, not an optimisation: a session that recorded
an end-of-turn must never be reported as stalled just because the timeout also elapsed.

---

## SessionEvent

| Field | Type | Notes |
|---|---|---|
| `kind` | `STARTED \| PROGRESS \| QUESTION \| COMPLETED \| FAILED` | The normalized vocabulary (FR-007) |
| `at` | datetime | |
| `summary` | str | One line (FR-008) |
| `summary_provenance` | `MODEL \| MECHANICAL` | FR-008c — lets a future speaking consumer treat them differently |

Belongs to exactly one Session, ordered within it. `QUESTION` events are what a future trigger
engine subscribes to (FR-010); nothing consumes them this phase.

---

## SessionRegistry

| Field | Type | Notes |
|---|---|---|
| `sessions` | dict[str, Session] | Keyed by `session_id` |
| `last_heartbeat_at` | datetime | FR-024a |
| `heartbeat_interval_s` | int = 30 | Configurable |
| `staleness_threshold_s` | int = 90 | Configurable; tolerates two missed beats |

**`is_stale`** = `now - last_heartbeat_at > staleness_threshold_s`.

**The registry must distinguish three conditions and never collapse them** (FR-011a):

| Condition | Meaning | Never rendered as |
|---|---|---|
| populated + fresh | live data | — |
| **empty + fresh** | genuinely no sessions | — |
| **empty or populated + stale** | cannot currently observe | "no sessions running" |

That middle/bottom distinction is the entire content of FR-011a. An empty-and-stale registry is
the failure case: it renders as "you have no sessions running" through an entirely normal code
path unless liveness is checked first.

---

## RecordSource

The **single seam** through which every session record is opened (plan Gate 3).

| Member | Type | Notes |
|---|---|---|
| `open(path)` | contextmanager | The only permitted way to open a record |
| `stats.records_opened` | int | Incremented per open — the assertion target for SC-004i |
| `stats.records_skipped` | int | Unparseable entries (FR-009) |
| `select_candidates(window)` | list[Path] | Filters by **mtime before parsing** (FR-005d) |

Direct `open()` / `Path.read_text` inside the adapter is banned by ruff `banned-api`, so the
counter cannot be bypassed. A counter with a second path around it measures nothing.

---

## SummarizerPort

| Implementation | Resident cost | Default | Requirement |
|---|---|---|---|
| `MechanicalSummarizer` | none | **yes** | FR-008b |
| `OnDemandModelSummarizer` | during batch only | opt-in | FR-008a, Gate 2 |

Contract: `summarize(records) -> list[Summary]`, where `Summary` carries text and provenance.
The model handle must not outlive the call — asserted by weakref (Gate 2).

---

## Redactor

| Member | Notes |
|---|---|
| `redact(text, channel) -> str` | Runs on **every** channel (FR-011c) |
| `Channel` | `LOCAL \| REMOTE` — governs aggressiveness, not whether it runs |
| failure behaviour | Raises; caller suppresses the send (FR-011e) — **fails closed** |
| marker | Visible `[redacted]`, never a silent removal (FR-011f) |

Remote additionally shortens paths and trims code fragments (FR-011c, SC-004m).

---

## SessionAdapter

The only format-aware boundary (FR-023).

```
discover(window) -> list[SessionRef]
parse(record) -> SessionEvent | None      # None = skip at debug level (FR-009)
```

Adding a second coding agent is a new implementation of this interface and **must not change the
MCP tool surface** — a second agent appears as more sessions in the same replies, not as new
tools (FR-023, FR-018b).
