# Phase 1 Data Model: Trigger & Scheduler Engine

**Date**: 2026-08-21 | **Plan**: [plan.md](./plan.md) | **Research**: [research.md](./research.md)

Two things persist — the rule→thread map and the fingerprint store — both JSON-file-backed with
atomic writes. Everything else is in-memory.

---

## Rule

Declared by the user in the rule file. See [contracts/rule-schema.md](./contracts/rule-schema.md).

| Field | Type | Notes |
|---|---|---|
| `id` | str | Unique; **the mapping key**, so a duplicate is a load-time error (FR-006) |
| `type` | `CRON \| WATCHER \| COMPLETION` | `CALENDAR` reserved, unimplemented (FR-003) |
| `match` | dict | Type-specific criteria |
| `prompt` | str | Template; interpolates event fields (FR-004) |
| `destination` | `REMOTE \| QUIET \| AUTO` | `LOCAL` reserved for the voice feature |
| `urgent` | bool = False | Explicit per-rule quiet-hours override (FR-014) |
| `enabled` | bool = True | |

**Validation**: unique ids; a template referencing a field the event type cannot supply is a
load-time error, not a render-time surprise (edge case).

---

## TriggerEvent

| Field | Type | Notes |
|---|---|---|
| `type` | TriggerType | |
| `event_id` | str | Natural key: scheduled instant, session id, task id |
| `at` | datetime | |
| `fields` | dict | Interpolation source |
| `fingerprint_inputs` | dict | **Only** non-drifting fields — see below |

---

## Fingerprint

The identity that makes FR-017's at-most-once guarantee mean something.

```
key = (rule_id, event_id, sha256(canonical(fingerprint_inputs)))
```

**Permitted inputs, per type — the enumeration is the requirement (FR-017b):**

| Type | Inputs | Explicitly excluded |
|---|---|---|
| `WATCHER` | pending question text (or its hash), session state, idle reason | elapsed time, last-activity, quiet duration |
| `CRON` | the scheduled instant | evaluation time, drift |
| `COMPLETION` | task id, terminal status | duration, finish time |

**A drifting input is the failure this table exists to prevent.** Include `last_activity_at` and
every evaluation yields a "new" event, producing an alert per cycle — the inverse of the failure
FR-017 guards, and the worse one, because it is the version that gets the feature muted.

**Retention**: cleared on a daily reset (FR-017c), the same interval Feature 001's FR-005f now
defines for sticky membership. Anchoring to it is what revealed that 001 referenced a retention
reset it never defined.

---

## Firing

| Field | Type | Notes |
|---|---|---|
| `rule_id` / `event` / `prompt` | | |
| `thread_id` | str | From the durable map |
| `reply` | str \| None | None until the turn completes |
| `outcome` | `DELIVERED \| SUPPRESSED \| QUEUED \| EXPIRED \| FAILED` | FR-012 |
| `reason` | str | Required for every non-`DELIVERED` outcome |

**Every outcome carries a reason.** A firing that vanished without one is indistinguishable from
a firing that never happened — the same class of defect as an empty registry reading as "no
sessions running".

---

## RuleThreadMap  *(durable)*

`rule_id → thread_id`, JSON-backed, atomically written (R5).

**Persistence is the requirement, not an optimisation** (FR-011b): held in memory, every restart
orphans the thread and starts fresh, which presents as a stable thread and behaves as a fresh
one. The failure is invisible until someone reads the conversation and finds it has no past.

Trimmed to a rolling window of recent firings (FR-011c) so continuity does not become ballast.

---

## FingerprintStore  *(durable)*

`fingerprint key → first-seen timestamp`. Cleared daily. Durable because a restart must not
re-fire everything already delivered.

---

## PresenceSignal

| Member | Notes |
|---|---|
| `last_user_turn_at` | Most recent turn **lacking** the synthetic marker (R4) |
| `is_present(now)` | `now - last_user_turn_at < threshold` (heuristic default) |

Derived from provenance rather than tracked separately, so there is no second source of truth to
drift. Never from host idle time (FR-022) — the engine's own machine says nothing about the user.

---

## OutputDestination *(port)*

| Implementation | This feature | Notes |
|---|---|---|
| `RemoteDestination` | yes | Telegram |
| `QuietDestination` | yes | Records, delivers nothing |
| `LocalDestination` | **no** | Registers against this port in the voice feature (FR-020) |

`AUTO` resolves to local when present, remote otherwise; with no local registered it resolves to
remote (FR-021).

---

## ReleaseRequest — the single path (Gate 3)

```
release(items: list[Firing], reason: QUIET_HOURS_ENDED | QUEUE_EXPIRED | IMMEDIATE)
  -> re-check conditions   (FR-013b; un-recheckable types EXPIRE, FR-013c)
  -> coalesce survivors    (FR-013d, FR-015)
  -> redact                (FR-008a, fail closed FR-008b)
  -> deliver
```

**Three entry conditions, one mechanism.** Implemented twice, the copy that runs least often
acquires defects nobody sees.

---

## Entity relationships

```
Rule ──1:1── RuleThreadMap entry ──> thread_id
 │
 └──fires──> Firing ──> Fingerprint (suppresses repeats)
                │
                └──> release() ──> coalesce ──> redact ──> OutputDestination
```
