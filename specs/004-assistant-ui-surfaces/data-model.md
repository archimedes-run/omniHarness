# Phase 1 Data Model — Feature 004

Existing shapes are described as they are, verified by reading. **Changes** are marked,
and there are only three.

## Existing, unchanged

### PendingAction (`app/policy/models.py`)
`id`, `plan_text`, `tool_name`, `arguments`, `targets`, `tier_at_statement`,
`expires_at`, `thread_id`, `requester`, `delegation_chain`, `outcome`, `claimed_by`.

- `open_actions(now)` returns unresolved and unexpired actions — expiry is filtered at
  read time, so no sweep is needed for display to be correct.
- `claim()` links a file and returns the claimed action to exactly one caller. The
  return value is the action, not a boolean, which removes a read-after-write race.
- Resolvable once. `Outcome` ∈ EXECUTED, DECLINED, EXPIRED, UNRECOGNISED,
  TARGETS_DRIFTED, SUPERSEDED. **DECLINED and SUPERSEDED are never produced today** —
  nothing can decline what nothing can confirm. Phase 1 makes DECLINED reachable.

### Session (`session_watcher/models.py`)
`SessionState` with `WAITING_ON_USER`, `IDLE`, and others; `IdleReason` ∈ COMPLETED,
STALLED. The model already encodes the distinction the UI must show: **COMPLETED is an
observed fact, STALLED is an inference**, and STALLED is deliberately not terminal.

### Observability (`session_watcher/registry.py`)
LIVE, STALE, NEVER_OBSERVED — "the three conditions that must never collapse into two".
The UI adds a fourth, **UNREACHABLE**, which belongs to the gateway↔watcher transport
and not to the registry. Keeping it outside the enum is deliberate: it is a different
kind of fact and merging it would undo what the enum exists for.

### Firing / Outcome (`app/trigger_engine/models.py`)
`rule_id`, `event`, `prompt`, `thread_id`, `reply`, `outcome`, `reason`.
`Outcome` ∈ DELIVERED, SUPPRESSED, QUEUED, EXPIRED, FAILED. Every non-DELIVERED outcome
must carry a reason — enforced in `resolve()`.

## Changes

### C1 — `Firing.batch_id` *(FR-021)*
Optional identifier shared by every firing delivered in one message after coalescing.
Written at release; absent for single deliveries and for all historical rows.

**Not an outcome.** A coalesced firing was delivered. Adding a COALESCED member would
make the audit log assert something untrue about what happened.

### C2 — Rule evaluation record *(FR-020)*
`last_evaluated_at` per rule, updated whenever a rule is evaluated regardless of whether
it fires. Stored alongside existing engine state.

Distinguishes three states the UI must separate: never evaluated, evaluated and never
fired, fired recently. Only the third is currently visible.

### C3 — `PolicyRuleSet.threshold_targets` *(FR-009)*
Integer, default **10 — a stated guess** (Article X; no production distribution of target
counts exists, because the confirmation path has never run). Above it, confirmation
requires the typed target count.

## Derived, not stored

- **Time remaining** — computed from `expires_at`; never persisted, so it cannot go stale.
- **Tier decision** — `(tier, deciding_rule, from_default)` from `explain()`. `from_default`
  is what separates unclassified-defaults-to-Tier-3 from explicitly-classified-as-Tier-3.
- **Batch siblings** — other firings sharing a `batch_id`, resolved at read time.
